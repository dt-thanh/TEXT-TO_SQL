"""Load the semantic layer: what the data MEANS, written once in semantic/*.yml (spec §24).

The YAML files are data, edited by people. This module turns them into typed objects and checks
them when they are loaded, so a typo fails loudly here instead of silently giving the model a
wrong or missing definition:
- unknown keys are rejected (extra="forbid"): "pitfall:" instead of "pitfalls:" is an error;
- concept ids are unique, and every verified query names concepts that exist.
"""

from functools import lru_cache
from pathlib import Path

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


class Coverage(Strict):
    """Everything the data contains. Always shown: it is how the model knows what to decline."""

    assets: list[Asset]
    macro_series: list[MacroSeries]
    not_covered: str


class Concept(Strict):
    """A metric (metrics.yml) or a glossary term (glossary.yml): shown when a synonym matches."""

    id: str
    name: str
    synonyms: list[str]
    definition: str
    sql: str | None = None
    unit: str | None = None
    pitfalls: str | None = None


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
