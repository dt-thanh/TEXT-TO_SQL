"""Load the semantic layer: what the data MEANS, written once in semantic/*.yml (spec §24).

The YAML files are data, edited by people. This module turns them into typed objects and checks
them when they are loaded, so a typo fails loudly here instead of silently giving the model a
wrong or missing definition:
- unknown keys are rejected (extra="forbid"): "pitfall:" instead of "pitfalls:" is an error;
- concept ids are unique, and every verified query names concepts that exist;
- a metric with a research `template` declares every parameter the template uses, the column
  that holds its sample size, and the unit of every result column.
"""

import string
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from src.common.exceptions import ConfigError

SEMANTIC_DIR = Path(__file__).resolve().parents[2] / "semantic"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Asset(Strict):
    symbol: str
    name: str
    synonyms: list[str]


class MacroSeries(Strict):
    column: str
    name: str


class DefiChain(Strict):
    chain: str  # DefiLlama slug as stored in MART_CHAIN_TVL_DAILY.chain
    name: str
    synonyms: list[str]


class Coverage(Strict):
    """Everything the data contains. Always shown: it is how the model knows what to decline."""

    assets: list[Asset]
    macro_series: list[MacroSeries]
    defi_chains: list[DefiChain] = []
    not_covered: str


Unit = Literal[
    "fraction",
    "fraction_per_year",
    "ratio",
    "count",
    "percent",
    "bps",
    "usd",
    "date",
    "sigma",
    "text",
    "price",
]


class Param(Strict):
    """One parameter of a research template. Values are checked before they reach SQL."""

    name: str
    # symbol_list: 1 to MAX_SYMBOLS distinct symbols, comma-separated ("BTCUSDT,ETHUSDT").
    type: Literal["symbol", "symbol_list", "chain", "date", "number", "integer"]
    description: str
    minimum: float | None = None
    maximum: float | None = None


class Output(Strict):
    """One result column of a research template."""

    column: str  # as Snowflake returns it (upper case)
    unit: Unit
    description: str
    # When the unit differs per row (risk signals: sigma, ratio or fraction), the result column
    # that holds each row's unit.
    unit_column: str | None = None


class GoldenCase(Strict):
    """Parameters and the values the template must return for them (checked by hand)."""

    params: dict[str, str]
    expected: dict[str, float] = {}
    # Multi-row templates: one dict per expected row, its key columns (text) and values.
    rows: list[dict[str, str | float]] = []
    # Allowed difference: absolute for values below 1 in size (returns, correlations), relative
    # above (prices, TVL), so one setting works for both. Raise it for data that may be revised.
    tolerance: float = 1e-6

    def matches(self, column: str, actual: float) -> bool:
        expected = self.expected[column]
        return abs(actual - expected) <= self.tolerance * max(1.0, abs(expected))


class Concept(Strict):
    """A metric (metrics.yml) or a glossary term (glossary.yml): shown when a synonym matches.

    A metric with a `template` can also be used by research mode (src/agents/research): the
    planner picks it with parameters and the template, not the model, writes the SQL.
    """

    id: str
    name: str
    synonyms: list[str]
    definition: str
    sql: str | None = None
    unit: str | None = None
    pitfalls: str | None = None
    # Research mode only.
    sources: list[Literal["binance", "fred", "defillama"]] = []
    template: str | None = None
    params: list[Param] = []
    outputs: list[Output] = []
    sample_column: str | None = None  # result column with the number of observations
    min_observations: int = 1  # per row for a multi-row template
    # Multi-row templates (one row per asset or pair): the columns that name a row. Empty: the
    # template returns one row.
    row_key: list[str] = []
    allow_empty: bool = False  # no row is an answer (no risk signal fired), not missing data
    pit_mode: Literal["as_known", "latest", "retrospective"] | None = None
    golden_case: GoldenCase | None = None

    @model_validator(mode="after")
    def check_template(self) -> "Concept":
        if self.template is None:
            return self
        used = {name for _, name, _, _ in string.Formatter().parse(self.template) if name}
        declared = {p.name for p in self.params}
        if used != declared:
            message = f"template uses {sorted(used)}, declares {sorted(declared)}"
            raise ValueError(f"{self.id}: {message}")
        columns = {o.column for o in self.outputs}
        if not self.outputs or self.sample_column not in columns:
            raise ValueError(f"{self.id}: sample_column must be one of the declared outputs")
        if not self.sources or self.pit_mode is None:
            raise ValueError(f"{self.id}: a research metric needs sources and pit_mode")
        if self.golden_case and set(self.golden_case.params) != declared:
            raise ValueError(f"{self.id}: golden_case must give every parameter")
        if not set(self.row_key) <= columns:
            raise ValueError(f"{self.id}: row_key columns must be declared outputs")
        if self.golden_case and bool(self.row_key) != bool(self.golden_case.rows):
            raise ValueError(f"{self.id}: a multi-row template needs golden rows, and only it")
        return self


class VerifiedQuery(Strict):
    id: str
    question: str
    concepts: list[str]  # ids of the metrics/terms this example demonstrates
    sql: str
    explanation: str


class SemanticLayer(Strict):
    coverage: Coverage
    metrics: list[Concept]
    terms: list[Concept]
    verified_queries: list[VerifiedQuery]

    @property
    def concepts(self) -> list[Concept]:
        return [*self.metrics, *self.terms]

    @property
    def research_metrics(self) -> list[Concept]:
        """Metrics research mode may plan with: the ones that carry a SQL template."""

        return [m for m in self.metrics if m.template]

    @model_validator(mode="after")
    def check_ids(self) -> "SemanticLayer":
        concept_ids = [c.id for c in self.concepts]
        query_ids = [q.id for q in self.verified_queries]
        for ids in (concept_ids, query_ids):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate ids: {', '.join(duplicates)}")
        for query in self.verified_queries:
            unknown = sorted(set(query.concepts) - set(concept_ids))
            if unknown:
                raise ValueError(f"verified query {query.id} names unknown concepts: {unknown}")
        return self


def read_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as err:
        raise ConfigError(f"Cannot read {path}: {err}") from err


@lru_cache
def load_semantic_layer(directory: Path = SEMANTIC_DIR) -> SemanticLayer:
    """Read and check semantic/{glossary,metrics,verified_queries}.yml. Cached per directory."""

    glossary = read_yaml(directory / "glossary.yml")
    try:
        return SemanticLayer(
            coverage=glossary.get("coverage"),
            terms=glossary.get("terms", []),
            metrics=read_yaml(directory / "metrics.yml").get("metrics", []),
            verified_queries=read_yaml(directory / "verified_queries.yml").get(
                "verified_queries", []
            ),
        )
    except ValidationError as err:
        raise ConfigError(f"Invalid semantic layer in {directory}:\n{err}") from err


def with_universe(layer: SemanticLayer, universe: Sequence[Mapping[str, Any]]) -> SemanticLayer:
    """The layer with coverage.assets = the ready assets of MART_ASSET_UNIVERSE.

    The glossary keeps hand-written names and synonyms for the core assets; an added coin gets
    its ticker and name as synonyms. Without universe rows (table not built yet, offline tests)
    the glossary list is used as it is.
    """

    ready = [row for row in universe if row.get("STATUS") == "ready"]
    if not ready:
        return layer
    curated = {asset.symbol: asset for asset in layer.coverage.assets}
    assets = []
    for row in sorted(ready, key=lambda r: (not r.get("IS_CORE"), r["SYMBOL"])):
        symbol = row["SYMBOL"]
        if symbol in curated:
            assets.append(curated[symbol])
            continue
        base, name = str(row["BASE_ASSET"]), str(row.get("DISPLAY_NAME") or row["BASE_ASSET"])
        synonyms = sorted({base.lower(), name.lower()})
        assets.append(Asset(symbol=symbol, name=name, synonyms=synonyms))
    coverage = layer.coverage.model_copy(update={"assets": assets})
    return layer.model_copy(update={"coverage": coverage})
