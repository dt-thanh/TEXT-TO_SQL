"""Turn a planned task (metric id + parameter strings) into verified SQL.

The planner is an LLM, so its output is untrusted like any model output. A task only becomes SQL
when the metric exists in the catalog (semantic/metrics.yml, metrics with a `template`), every
declared parameter is given and nothing else, and every value passes its type's check. Values are
then written into the template as SQL literals by this code; the result still goes through the
SQL guard and runs as the read-only agent role.
"""

import math
from dataclasses import dataclass
from datetime import date

from src.semantic.layer import Concept, Param, SemanticLayer

# Nothing in the marts is older than this (DefiLlama TVL starts 2018-02-12).
DATA_START = date(2018, 1, 1)
# Largest symbol_list: a watchlist (spec v1.1, 3.9).
MAX_SYMBOLS = 10


class TaskError(ValueError):
    """The task cannot run as planned; the message says why, for the report and the logs."""


@dataclass(frozen=True)
class ResolvedTask:
    metric: Concept
    params: dict[str, str]  # normalized, e.g. {"symbol": "ETHUSDT", "start_date": "2025-01-01"}
    sql: str


def metric_by_id(layer: SemanticLayer, metric_id: str) -> Concept:
    for metric in layer.research_metrics:
        if metric.id == metric_id:
            return metric
    raise TaskError(f"{metric_id} is not a research metric")


def literal(
    param: Param, raw: str, layer: SemanticLayer, data_as_of: date | None
) -> tuple[str, str]:
    """(normalized value, SQL literal) for one parameter, or TaskError."""

    value = raw.strip()
    if param.type in ("symbol", "symbol_list"):
        # coverage.assets is the ready assets of MART_ASSET_UNIVERSE (with_universe): an asset
        # still loading, unsupported or in error is refused here, before any SQL.
        symbols = {asset.symbol for asset in layer.coverage.assets}
        given = [part.strip().upper() for part in value.split(",")] if value else []
        if param.type == "symbol" and len(given) != 1:
            raise TaskError(f"{param.name}={value!r} must be one symbol")
        if not 1 <= len(given) <= MAX_SYMBOLS or len(set(given)) != len(given):
            raise TaskError(f"{param.name}: 1 to {MAX_SYMBOLS} different symbols")
        unknown = [symbol for symbol in given if symbol not in symbols]
        if unknown:
            shown = ", ".join(unknown)
            raise TaskError(f"{param.name}={shown!r} is not one of the ready {sorted(symbols)}")
        # Every symbol is one of the known pairs (letters and digits), so quoting is safe.
        return ",".join(given), ", ".join(f"'{symbol}'" for symbol in given)
    if param.type == "chain":
        chains = {chain.chain.lower(): chain.chain for chain in layer.coverage.defi_chains}
        if value.lower() not in chains:
            raise TaskError(f"{param.name}={value!r} is not one of {sorted(chains.values())}")
        return chains[value.lower()], f"'{chains[value.lower()]}'"
    if param.type == "date":
        try:
            day = date.fromisoformat(value)
        except ValueError as err:
            raise TaskError(f"{param.name}={value!r} is not a YYYY-MM-DD date") from err
        if day < DATA_START:
            raise TaskError(f"{param.name}={value} is before the data starts ({DATA_START})")
        if data_as_of and day > data_as_of:
            raise TaskError(f"{param.name}={value} is after the newest data ({data_as_of})")
        return day.isoformat(), f"'{day.isoformat()}'"

    try:
        number = int(value) if param.type == "integer" else float(value)
    except ValueError as err:
        raise TaskError(f"{param.name}={value!r} is not a {param.type}") from err
    if not math.isfinite(number):
        raise TaskError(f"{param.name}={value!r} is not a finite number")
    if param.minimum is not None and number < param.minimum:
        raise TaskError(f"{param.name}={value} is below {param.minimum}")
    if param.maximum is not None and number > param.maximum:
        raise TaskError(f"{param.name}={value} is above {param.maximum}")
    return str(number), repr(number)


def resolve(
    metric_id: str, params: dict[str, str], layer: SemanticLayer, data_as_of: date | None
) -> ResolvedTask:
    metric = metric_by_id(layer, metric_id)
    declared = {param.name for param in metric.params}
    if set(params) != declared:
        missing, extra = sorted(declared - set(params)), sorted(set(params) - declared)
        raise TaskError(f"{metric_id}: missing {missing}, unexpected {extra}")

    normalized, literals = {}, {}
    for param in metric.params:
        normalized[param.name], literals[param.name] = literal(
            param, params[param.name], layer, data_as_of
        )
    if "start_date" in normalized and normalized["start_date"] > normalized["end_date"]:
        raise TaskError(f"{metric_id}: start_date is after end_date")
    return ResolvedTask(metric, normalized, metric.template.format(**literals))
