"""Unit tests for the semantic layer (semantic/*.yml) and the retriever that picks what to show."""

from pathlib import Path

import pytest

from src.common.exceptions import ConfigError
from src.semantic.layer import SEMANTIC_DIR, load_semantic_layer
from src.semantic.retriever import format_context, mentions, normalize, retrieve

LAYER = load_semantic_layer()


def concept_ids(question: str) -> set[str]:
    return {match.concept.id for match in retrieve(question, LAYER).matches}


# --- The files themselves --------------------------------------------------------------------


def test_the_real_semantic_layer_loads() -> None:
    symbols = {a.symbol for a in LAYER.coverage.assets}
    assert symbols == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"}
    assert "annualized_volatility" in {c.id for c in LAYER.concepts}
    assert LAYER.verified_queries


def test_one_word_synonyms_are_long_enough_to_be_specific() -> None:
    # Without accents "mà", "má", "mã" all become "ma": a synonym "ma" would match them all.
    for concept in LAYER.concepts:
        for synonym in concept.synonyms:
            words = normalize(synonym).split()
            assert len(words) > 1 or len(words[0]) >= 3, f"{concept.id}: {synonym!r} is too short"


def write_layer(
    directory: Path, concept_line: str = "", example_concept: str = "close_price"
) -> None:
    """A minimal semantic layer on disk; the arguments inject one mistake at a time."""

    (directory / "glossary.yml").write_text(
        "coverage:\n"
        "  assets: [{symbol: BTCUSDT, name: Bitcoin, synonyms: [bitcoin]}]\n"
        "  macro_series: []\n"
        "  not_covered: Stocks.\n"
        "terms:\n"
        "  - {id: close_price, name: Close, synonyms: [close], definition: Close price."
        f"{concept_line}}}\n",
        encoding="utf-8",
    )
    (directory / "metrics.yml").write_text("metrics: []\n", encoding="utf-8")
    (directory / "verified_queries.yml").write_text(
        "verified_queries:\n"
        f"  - {{id: q, question: Q, concepts: [{example_concept}], sql: SELECT 1, "
        "explanation: E}\n",
        encoding="utf-8",
    )


def test_a_small_valid_layer_loads(tmp_path: Path) -> None:
    write_layer(tmp_path)

    assert [c.id for c in load_semantic_layer(tmp_path).concepts] == ["close_price"]


def test_an_example_must_name_concepts_that_exist(tmp_path: Path) -> None:
    write_layer(tmp_path, example_concept="no_such_metric")

    with pytest.raises(ConfigError, match="no_such_metric"):
        load_semantic_layer(tmp_path)


def test_a_misspelled_key_is_an_error_not_silently_ignored(tmp_path: Path) -> None:
    write_layer(tmp_path, concept_line=", pitfall: typo")  # the field is "pitfalls"

    with pytest.raises(ConfigError, match="pitfall"):
        load_semantic_layer(tmp_path)


def test_the_default_directory_is_the_repository_semantic_folder() -> None:
    assert SEMANTIC_DIR.name == "semantic" and (SEMANTIC_DIR / "metrics.yml").exists()


# --- Matching words --------------------------------------------------------------------------


def test_normalize_drops_case_accents_and_punctuation() -> None:
    assert normalize("Lợi suất 10-NĂM của Đô la?") == "loi suat 10 nam cua do la"
    assert normalize("volatility_30d") == "volatility 30d"


def test_a_synonym_matches_with_or_without_accents_and_longer_word_endings() -> None:
    assert mentions(normalize("độ biến động của ETH"), "biến động")
    assert mentions(normalize("do bien dong cua ETH"), "biến động")
    assert mentions(normalize("average daily returns"), "daily return")


def test_a_synonym_needs_its_words_next_to_each_other() -> None:
    # "biên độ giá đóng cửa" has "bien" and "dong", but not the phrase "bien dong".
    assert not mentions(normalize("Biên độ giá đóng cửa"), "biến động")
    # A word may go on at its end, never at its start: "return" is not inside "overreturn".
    assert not mentions(normalize("overreturn"), "return")


# --- Retrieval -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What was the annualized volatility of BNB in 2024?", {"annualized_volatility"}),
        ("Độ biến động của SOL năm ngoái?", {"annualized_volatility"}),
        ("do bien dong quy ra nam cua SOL", {"annualized_volatility"}),
        ("Which asset had the highest 30-day volatility?", {"volatility_30d"}),
        ("Show the 20-day moving average of BTC", {"moving_average"}),
        ("Tổng lợi nhuận của ETH trong năm 2025?", {"period_return"}),
        ("Lãi suất Fed hiện tại là bao nhiêu?", {"fed_funds_rate"}),
        ("Days when the 10-year yield rose from the previous day",
         {"treasury_10y", "previous_day_change"}),
        ("Khối lượng giao dịch của BNB tháng trước", {"trading_volume"}),
    ],
)
def test_the_question_retrieves_the_concepts_it_needs(question: str, expected: set[str]) -> None:
    assert expected <= concept_ids(question)


def test_the_30_day_column_question_also_sees_the_period_definition() -> None:
    # "volatility" is a synonym of both, so the model sees both and their pitfalls tell them apart.
    assert concept_ids("30-day volatility of ETH") >= {"volatility_30d", "annualized_volatility"}


def test_a_question_without_known_words_retrieves_no_definitions_or_examples() -> None:
    retrieved = retrieve("Hello, who are you?", LAYER)

    assert retrieved.matches == () and retrieved.examples == ()


def test_examples_sharing_the_most_concepts_come_first_and_at_most_two() -> None:
    retrieved = retrieve("7-day moving average of the BTC closing price", LAYER)

    assert retrieved.examples[0].id == "eth_moving_average_given_week"
    assert len(retrieved.examples) <= 2


def test_a_loosely_related_example_is_not_shown() -> None:
    # Both examples that use daily_return demonstrate two more concepts this question lacks.
    retrieved = retrieve("So sánh lợi nhuận trung bình mỗi ngày của BTC và ETH", LAYER)

    assert {m.concept.id for m in retrieved.matches} == {"daily_return"}
    assert retrieved.examples == ()


def test_ids_name_what_was_retrieved_for_logs_and_eval_reports() -> None:
    retrieved = retrieve("30-day moving average close of ETH", LAYER)

    assert "moving_average" in retrieved.ids
    assert "eth_moving_average_given_week" in retrieved.ids


# --- What the model reads --------------------------------------------------------------------


def test_coverage_is_always_in_the_context() -> None:
    text = format_context(retrieve("Hello, who are you?", LAYER))

    assert "# Available data" in text
    assert "BTCUSDT: Bitcoin" in text and "treasury_10y" in text
    assert "Not in the data: Stocks" in text
    assert "# Business definitions" not in text and "# Verified examples" not in text


def test_matched_definitions_bring_their_sql_and_pitfalls_and_nothing_else() -> None:
    text = format_context(retrieve("Độ biến động quy ra năm của ETH", LAYER))

    assert "STDDEV_SAMP(log_return) * SQRT(365)" in text
    assert "Never AVG(volatility_30d)" in text
    assert 'question says: "độ biến động", "biến động", "quy ra năm"' in text
    assert "EXP(SUM(log_return))" not in text.split("# Verified examples")[0]  # period_return
