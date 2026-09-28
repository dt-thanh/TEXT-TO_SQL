"""Pick the semantic knowledge one question needs, and write it for the prompt (spec §25).

Retrieval here is lexical: a metric or term is relevant when the question uses one of its
synonyms. With a dozen hand-written concepts this is free, instant, deterministic and easy to
debug (the log says which words matched). Its limit: a paraphrase that no synonym covers is
missed, which embeddings would catch. Revisit when the layer grows to hundreds of entries.

What is shown:
- coverage (assets, macro series, what is NOT in the data): always, it is small;
- metrics and terms whose synonyms appear in the question;
- up to MAX_EXAMPLES verified queries that share the most concepts with the question, and only
  when at least half of what the example demonstrates is in the question. A loosely related
  example is a distractor: the model copies its shape (found on the benchmark: an example about
  one asset made the model answer a two-asset comparison in one row).
"""

import re
import unicodedata
from dataclasses import dataclass

from src.semantic.layer import Concept, Coverage, SemanticLayer, VerifiedQuery

MAX_EXAMPLES = 2


def normalize(text: str) -> str:
    """Lower case, no accents, words separated by one space: 'Lợi suất 10-NĂM' → 'loi suat 10 nam'.

    Analysts type Vietnamese with and without accents, so both must match the same synonym.
    """

    text = text.lower().replace("đ", "d")  # đ is its own letter, not d + an accent
    # NFD splits "ệ" into "e" + two accent marks (category Mn); dropping the marks keeps "e".
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def mentions(normalized_question: str, synonym: str) -> bool:
    """Does the question contain the synonym's words, next to each other and in order?

    Each word must start a word of the question and may go on ("return" matches "returns").
    """

    words = [re.escape(word) for word in normalize(synonym).split()]
    pattern = r"\b" + r"[a-z0-9]*\s".join(words)
    return re.search(pattern, normalized_question) is not None


@dataclass(frozen=True)
class Match:
    concept: Concept
    synonyms: tuple[str, ...]  # the synonyms found in the question, as written in the YAML


@dataclass(frozen=True)
class RetrievedContext:
    coverage: Coverage
    matches: tuple[Match, ...]
    examples: tuple[VerifiedQuery, ...]

    @property
    def ids(self) -> tuple[str, ...]:
        """What was retrieved, for logs and eval reports."""

        return tuple(m.concept.id for m in self.matches) + tuple(q.id for q in self.examples)


def retrieve(
    question: str, layer: SemanticLayer, max_examples: int = MAX_EXAMPLES
) -> RetrievedContext:
    text = normalize(question)
    matches = []
    for concept in layer.concepts:
        found = tuple(s for s in concept.synonyms if mentions(text, s))
        if found:
            matches.append(Match(concept, found))

    matched_ids = {m.concept.id for m in matches}
    # Most shared concepts first; sorted() is stable, so ties keep the order of the YAML file.
    def shared(query: VerifiedQuery) -> int:
        return len(matched_ids.intersection(query.concepts))

    ranked = sorted(layer.verified_queries, key=shared, reverse=True)
    examples = [q for q in ranked if shared(q) > 0 and 2 * shared(q) >= len(q.concepts)]
    examples = examples[:max_examples]
    return RetrievedContext(layer.coverage, tuple(matches), tuple(examples))


def format_context(context: RetrievedContext) -> str:
    """The semantic part of the user message: coverage, then definitions, then examples."""

    coverage = context.coverage
    lines = ["# Available data", "Assets (the only ones in the data; use the exact symbol):"]
    for asset in coverage.assets:
        lines.append(f"- {asset.symbol}: {asset.name} ({', '.join(asset.synonyms)})")
    lines.append("Macro series (columns):")
    lines += [f"- {series.column}: {series.name}" for series in coverage.macro_series]
    lines.append(f"Not in the data: {coverage.not_covered.strip()}")

    if context.matches:
        lines += ["", "# Business definitions"]
    for match in context.matches:
        concept = match.concept
        said = ", ".join(f'"{s}"' for s in match.synonyms)
        lines.append(f"## {concept.id}: {concept.name} (question says: {said})")
        lines.append(f"Meaning: {concept.definition.strip()}")
        if concept.sql:
            lines.append(f"SQL: {' '.join(concept.sql.split())}")
        if concept.unit:
            lines.append(f"Unit: {concept.unit}")
        if concept.pitfalls:
            lines.append(f"Pitfall: {concept.pitfalls.strip()}")

    if context.examples:
        lines += ["", "# Verified examples"]
    for example in context.examples:
        lines.append(f"Question: {example.question}")
        lines.append(f"SQL:\n{example.sql.strip()}")
        lines.append(f"Explanation:\n{example.explanation.strip()}")
        lines.append("")
    return "\n".join(lines).strip()
