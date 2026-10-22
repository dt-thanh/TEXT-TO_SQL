"""Unit tests for research mode, with a scripted LLM and a fake warehouse: no tokens, no network."""

from datetime import date
from typing import Any

import pytest

from src.agents.research.catalog import TaskError, resolve
from src.agents.research.grounding import normalize_number, ungrounded
from src.agents.research.report import to_markdown
from src.agents.research.workflow import answer_research
from src.semantic.layer import load_semantic_layer
from src.services.llm import LLMResult, LLMUsage

LAYER = load_semantic_layer()
TODAY = date(2026, 10, 22)
DATA_AS_OF = date(2026, 10, 21)
METADATA = [
    {"TABLE_NAME": name, "TABLE_COMMENT": "", "COLUMN_NAME": "X", "DATA_TYPE": "NUMBER",
     "COLUMN_COMMENT": "", "LATEST_TRADE_DATE": DATA_AS_OF}
    for name in ("MART_ASSET_DAILY", "MART_MACRO_DAILY", "MART_MARKET_MACRO_DAILY",
                 "MART_CHAIN_TVL_DAILY")
]  # fmt: skip
ROWS = {
    "PERIOD_RETURN": {"PERIOD_RETURN": -0.10969566598158, "N_DAYS": 365},
    "RETURN_CORRELATION": {"RETURN_CORRELATION": 0.815578027405349, "N_DAYS": 365},
    "N_EVENTS": {"N_EVENTS": 2, "AVG_RETURN_AFTER_EVENTS": 0.17, "MEDIAN_RETURN_AFTER_EVENTS": 0.07,
                 "AVG_RETURN_ALL_DAYS": 0.02, "N_ALL_DAYS": 365},
}  # fmt: skip
YEAR = [{"name": "start_date", "value": "2025-01-01"}, {"name": "end_date", "value": "2025-12-31"}]
ETH = {"name": "symbol", "value": "ETHUSDT"}
ETH_RETURN = {"metric_id": "period_return", "params": [ETH, *YEAR]}
CORRELATION = {
    "metric_id": "return_correlation",
    "params": [{"name": "symbol_a", "value": "BTCUSDT"}, {"name": "symbol_b", "value": "ETHUSDT"}]
    + YEAR,
}
GOOD_FINDINGS = [
    {"claim": "ETH returned -10.97% in 2025 (365 days).", "evidence_ids": ["ev1"]},
    {"claim": "BTC and ETH daily returns had a correlation of 0.82.", "evidence_ids": ["ev2"]},
]


class ScriptedLLM:
    """Plays back JSON answers in order: the plan first, then each version of the findings."""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def generate_json(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> LLMResult:
        self.prompts.append(user_prompt)
        usage = LLMUsage(input_tokens=1500, output_tokens=200, cost_usd=0.0009)
        return LLMResult(self.answers.pop(0), usage, "gpt-4.1-mini", 0.5)


class FakeWarehouse:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute(self, sql: str, params: Any = None, max_rows: int | None = None) -> list[Any]:
        if "INFORMATION_SCHEMA" in sql:
            return METADATA
        self.queries.append(sql)
        marker = next(key for key in ROWS if key in sql.upper())
        return [ROWS[marker]]


def plan(*tasks: dict[str, Any], decline: str = "") -> dict[str, Any]:
    return {"tasks": list(tasks), "decline_reason": decline}


def findings(*items: dict[str, Any], caveats: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"findings": list(items), "caveats": list(caveats)}


def research(llm: ScriptedLLM, warehouse: FakeWarehouse | None = None) -> Any:
    question = "How did ETH do in 2025, and how did it move with BTC?"
    return answer_research(question, llm=llm, warehouse=warehouse or FakeWarehouse(), today=TODAY)


# --- The workflow ----------------------------------------------------------------------------


def test_a_two_metric_question_runs_two_verified_queries_and_grounded_findings() -> None:
    llm = ScriptedLLM(plan(ETH_RETURN, CORRELATION), findings(*GOOD_FINDINGS))
    warehouse = FakeWarehouse()

    answer = research(llm, warehouse)

    assert answer.status == "complete"
    assert len(llm.prompts) == 2  # one plan, one set of findings
    assert len(warehouse.queries) == 2
    assert "symbol = 'ETHUSDT'" in warehouse.queries[0]  # the template, with checked values
    assert [f["claim"] for f in answer.findings] == [f["claim"] for f in GOOD_FINDINGS]
    assert answer.evidence[0]["values"][0]["value"] == pytest.approx(-0.10969566598158)
    assert answer.analysis_window == ("2025-01-01", "2025-12-31")
    assert any("co-movement" in c for c in answer.caveats)  # added by code, not the model


def test_the_planner_sees_the_whole_catalog_and_the_newest_data_day() -> None:
    llm = ScriptedLLM(plan(ETH_RETURN), findings(GOOD_FINDINGS[0]))

    research(llm)

    assert "Latest day with data (UTC): 2026-10-21" in llm.prompts[0]
    assert all(f"## {m.id}:" in llm.prompts[0] for m in LAYER.research_metrics)


def test_a_question_outside_the_catalog_is_declined_without_any_query() -> None:
    llm = ScriptedLLM(plan(decline="There is no stock data."))
    warehouse = FakeWarehouse()

    answer = research(llm, warehouse)

    assert answer.status == "declined" and answer.decline_reason == "There is no stock data."
    assert warehouse.queries == [] and len(llm.prompts) == 1


def test_an_invented_number_gets_one_rewrite_then_the_finding_is_dropped() -> None:
    invented = {"claim": "ETH returned -25% in 2025.", "evidence_ids": ["ev1"]}
    llm = ScriptedLLM(plan(ETH_RETURN), findings(invented), findings(invented))

    answer = research(llm)

    assert len(llm.prompts) == 3  # plan, findings, one rewrite
    assert "-25%" in llm.prompts[2]  # the rewrite is told which number was rejected
    assert answer.findings == [] and answer.dropped_findings[0]["rejected_numbers"] == ["-25%"]
    assert answer.status == "partial"


def test_a_rewrite_that_fixes_the_number_completes() -> None:
    invented = {"claim": "ETH returned -25% in 2025.", "evidence_ids": ["ev1"]}
    llm = ScriptedLLM(plan(ETH_RETURN), findings(invented), findings(GOOD_FINDINGS[0]))

    answer = research(llm)

    assert answer.status == "complete" and len(answer.findings) == 1


def test_a_finding_that_cites_no_evidence_is_dropped() -> None:
    uncited = {"claim": "ETH returned -10.97% in 2025.", "evidence_ids": []}
    llm = ScriptedLLM(plan(ETH_RETURN), findings(uncited), findings(uncited))

    assert research(llm).findings == []


def test_too_few_observations_is_insufficient_data_and_the_writer_is_not_called() -> None:
    event_study = {
        "metric_id": "forward_return_after_yield_move",
        "params": [ETH, {"name": "min_change_bps", "value": "10"},
                   {"name": "horizon_days", "value": "30"}, *YEAR],
    }  # fmt: skip
    llm = ScriptedLLM(plan(event_study))

    answer = research(llm)

    assert answer.status == "insufficient_data"  # 2 events < min_observations 3
    assert len(llm.prompts) == 1
    assert "not enough data" in answer.plan[0]["reason"]


def test_a_bad_parameter_fails_its_task_and_the_rest_still_runs() -> None:
    tesla = {"metric_id": "period_return", "params": [{"name": "symbol", "value": "TSLA"}, *YEAR]}
    llm = ScriptedLLM(plan(ETH_RETURN, tesla), findings(GOOD_FINDINGS[0]))

    answer = research(llm)

    assert answer.status == "partial"
    assert answer.plan[1]["status"] == "failed" and "TSLA" in answer.plan[1]["reason"]


def test_the_report_shows_findings_evidence_sql_and_caveats() -> None:
    llm = ScriptedLLM(plan(ETH_RETURN, CORRELATION), findings(*GOOD_FINDINGS))

    report = to_markdown(research(llm))

    assert "## Findings" in report and "-10.97%" in report
    assert "```sql" in report and "FINSIGHT.MART.MART_ASSET_DAILY" in report
    assert "## Caveats" in report


# --- Resolving parameters --------------------------------------------------------------------


def test_values_become_quoted_literals_only_after_their_checks() -> None:
    params = {"symbol": "ethusdt", "start_date": "2025-01-01", "end_date": "2025-12-31"}

    task = resolve("period_return", params, LAYER, DATA_AS_OF)

    assert task.params["symbol"] == "ETHUSDT"
    assert "symbol = 'ETHUSDT'" in task.sql
    assert "BETWEEN '2025-01-01' AND '2025-12-31'" in task.sql


@pytest.mark.parametrize(
    ("metric_id", "params", "message"),
    [
        ("drop_table", {}, "not a research metric"),
        ("period_return", {"symbol": "BTCUSDT' OR '1'='1", "start_date": "2025-01-01",
                           "end_date": "2025-12-31"}, "is not one of"),
        ("period_return", {"symbol": "BTCUSDT", "start_date": "2025-01-01"}, "missing"),
        ("period_return", {"symbol": "BTCUSDT", "start_date": "2026-11-01",
                           "end_date": "2026-11-30"}, "after the newest data"),
        ("period_return", {"symbol": "BTCUSDT", "start_date": "2025-12-31",
                           "end_date": "2025-01-01"}, "start_date is after end_date"),
        ("forward_return_after_yield_move", {"symbol": "ETHUSDT", "min_change_bps": "1e9",
                                             "horizon_days": "30", "start_date": "2025-01-01",
                                             "end_date": "2025-12-31"}, "above"),
        ("tvl_change", {"chain": "Polygon", "start_date": "2025-01-01",
                        "end_date": "2025-12-31"}, "is not one of"),
    ],
    ids=["unknown-metric", "injection", "missing-param", "future", "reversed", "out-of-range",
         "unknown-chain"],
)  # fmt: skip
def test_tasks_the_catalog_cannot_run_are_refused(
    metric_id: str, params: dict[str, str], message: str
) -> None:
    with pytest.raises(TaskError, match=message):
        resolve(metric_id, params, LAYER, DATA_AS_OF)


def test_every_catalog_template_resolves_with_its_golden_parameters() -> None:
    for metric in LAYER.research_metrics:
        assert metric.golden_case, f"{metric.id} has no golden case"
        resolve(metric.id, metric.golden_case.params, LAYER, DATA_AS_OF)


# --- Grounding -------------------------------------------------------------------------------

EVIDENCE = [{
    "id": "ev1", "params": {"symbol": "ETHUSDT", "start_date": "2025-01-01"}, "n": 239,
    "values": [{"value": 0.001425, "unit": "fraction"},
               {"value": 0.5366, "unit": "fraction_per_year"},
               {"value": 28456740243.0, "unit": "usd"}, {"value": -41.0, "unit": "bps"}],
}]  # fmt: skip
QUESTION = "ETH khi lợi suất 10 năm trên 4.5% trong năm 2025?"


@pytest.mark.parametrize(
    "claim",
    [
        "ETH had 239 such days in 2025, with volatility of 53.7% a year.",
        "Average daily return was +0.14% (n = 239).",
        "TVL was $28.46 billion; the 10-year yield fell 41 bps.",
        "TVL đạt 28,5 tỷ USD, biến động 53,66%/năm khi lợi suất trên 4.5%.",
    ],
)
def test_numbers_from_the_evidence_question_or_parameters_are_grounded(claim: str) -> None:
    assert ungrounded(claim, EVIDENCE, QUESTION, EVIDENCE) == []


@pytest.mark.parametrize(
    ("claim", "rejected"),
    [
        ("Volatility was 71.2% a year.", ["71.2%"]),
        ("ETH fell 41% while yields rose.", ["41%"]),  # bps are not percent
        ("TVL was 30.1 billion USD.", ["30.1 billion"]),
    ],
)
def test_numbers_that_are_not_in_the_evidence_are_rejected(claim: str, rejected: list[str]) -> None:
    assert ungrounded(claim, EVIDENCE, QUESTION, EVIDENCE) == rejected


@pytest.mark.parametrize(
    ("raw", "plain"),
    [("28,456,740,243", "28456740243"), ("28.456.740.243", "28456740243"), ("53,7", "53.7"),
     ("1,234.5", "1234.5"), ("1.234,5", "1234.5"), ("239", "239")],
)  # fmt: skip
def test_english_and_vietnamese_number_formats_are_read(raw: str, plain: str) -> None:
    assert normalize_number(raw) == plain


# --- Caveats ---------------------------------------------------------------------------------


def macro_evidence(source_date: str) -> dict[str, Any]:
    return {
        "id": "ev1", "metric_id": "macro_rate_change", "metric_name": "Rates", "n": 30,
        "params": {"start_date": "2026-09-22", "end_date": "2026-10-21"}, "pit_mode": "as_known",
        "values": [
            {"column": "TREASURY_10Y_END_SOURCE_DATE", "value": source_date, "unit": "date"}
        ],
    }  # fmt: skip


def test_a_yield_that_fred_stopped_publishing_gets_a_caveat_in_the_questions_language() -> None:
    from src.agents.research.writing import automatic_caveats

    english = automatic_caveats([macro_evidence("2026-10-02")], None, "en")
    vietnamese = automatic_caveats([macro_evidence("2026-10-02")], None, "vi")
    recent = automatic_caveats([macro_evidence("2026-10-20")], None, "en")

    assert any("2026-10-02, 19 days" in c for c in english)
    assert any("cách cuối kỳ 19 ngày" in c for c in vietnamese)
    assert not any("carried forward" in c for c in recent)


def test_a_date_among_the_results_may_be_quoted() -> None:
    item = macro_evidence("2026-10-02")

    assert ungrounded("The last yield describes 2026-10-02.", [item], "q", [item]) == []


def test_the_writer_repeating_a_shown_caveat_is_not_shown_twice() -> None:
    from src.agents.research.writing import new_caveats

    shown = ["Chỉ có 5 sự kiện biến động lợi suất; lợi nhuận đo trên các cửa sổ chồng lên nhau "
             "không độc lập, nên đây là bằng chứng yếu."]  # fmt: skip
    written = ["Chỉ có 5 sự kiện biến động lợi suất được phân tích, nên đây là bằng chứng yếu.",
               "Kết quả có thể khác nếu chọn ngưỡng 20 bps."]  # fmt: skip

    assert new_caveats(written, shown) == ["Kết quả có thể khác nếu chọn ngưỡng 20 bps."]


@pytest.mark.parametrize(
    ("value", "unit", "shown"),
    [(-0.1097, "fraction", "-10.97%"), (0.5366, "fraction_per_year", "53.66% per year"),
     (28456740243.0, "usd", "28,456,740,243 USD"), (-41.0, "bps", "-41 bps"),
     ("2026-10-02", "date", "2026-10-02"), (None, "ratio", "n/a"), (0.8156, "ratio", "0.816")],
)  # fmt: skip
def test_report_values_are_shown_in_their_units(value: Any, unit: str, shown: str) -> None:
    from src.agents.research.report import format_value

    assert format_value(value, unit) == shown


def test_an_english_caveat_that_repeats_a_shown_one_with_other_words_is_dropped() -> None:
    from src.agents.research.writing import new_caveats

    shown = ["6 yield-move event(s): returns over overlapping windows are not independent, so a "
             "few events are weak evidence."]  # fmt: skip
    written = ["The sample size of 6 events is small, so these results provide weak evidence.",
               "Returns are measured over overlapping windows, which may affect independence.",
               "A 20 bps threshold could select different days."]  # fmt: skip

    assert new_caveats(written, shown) == ["A 20 bps threshold could select different days."]


def test_a_reworded_small_sample_caveat_is_a_repeat() -> None:
    from src.agents.research.writing import new_caveats

    shown = ["6 yield-move event(s): returns over overlapping windows are not independent, so a "
             "few events are weak evidence."]  # fmt: skip
    written = ["Only 6 event days were observed, so the results provide weak evidence and should "
               "be interpreted cautiously."]  # fmt: skip

    assert new_caveats(written, shown) == []
