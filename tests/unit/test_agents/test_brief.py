"""Daily Brief with a scripted LLM and a fake warehouse (spec v1.1 BRIEF-01..05, AI-06)."""

from datetime import date
from typing import Any

import pytest

from src.agents.research import brief as brief_module
from src.agents.research.brief import build_brief_plan, generate_brief
from src.common.exceptions import LLMError
from src.services.llm import LLMResult, LLMUsage

TODAY = date(2026, 10, 26)
DATA_AS_OF = date(2026, 10, 25)
TABLES = ("MART_ASSET_DAILY", "MART_MACRO_DAILY", "MART_CHAIN_TVL_DAILY", "MART_RISK_SIGNAL_DAILY",
          "MART_ASSET_UNIVERSE", "MART_CPI_MONTHLY", "MART_MARKET_MACRO_DAILY")  # fmt: skip
METADATA = [
    {"TABLE_NAME": t, "TABLE_COMMENT": "", "COLUMN_NAME": "X", "DATA_TYPE": "NUMBER",
     "COLUMN_COMMENT": "", "LATEST_TRADE_DATE": DATA_AS_OF}
    for t in TABLES
]  # fmt: skip


def asset(symbol: str, chain: str | None, status: str = "ready", through=DATA_AS_OF) -> dict:
    return {"SYMBOL": symbol, "BASE_ASSET": symbol[:-4], "DISPLAY_NAME": symbol[:-4],
            "IS_CORE": symbol in ("BTCUSDT", "ETHUSDT"), "CHAIN_SLUG": chain, "STATUS": status,
            "DATA_FROM": date(2019, 1, 1), "DATA_THROUGH": through}  # fmt: skip


UNIVERSE = [asset("BTCUSDT", "Bitcoin"), asset("ETHUSDT", "Ethereum")]


def snapshot_row(symbol: str, ret: float) -> dict:
    return {"SYMBOL": symbol, "LAST_CLOSE": 100.0, "PERIOD_RETURN": ret,
            "ANNUALIZED_VOLATILITY": 0.5, "MAX_DRAWDOWN": -0.1, "N_DAYS": 30,
            "DATA_THROUGH": DATA_AS_OF}  # fmt: skip


RESULTS = {
    "days_stale": lambda symbols: [
        {
            "SYMBOL": s,
            "DATA_FROM": date(2019, 1, 1),
            "DATA_THROUGH": DATA_AS_OF,
            "N_DAYS": 2490,
            "DAYS_STALE": 0,
        }
        for s in symbols
    ],  # fmt: skip
    "running_peak": lambda symbols: [
        snapshot_row(s, r) for s, r in zip(symbols, [0.052, -0.031, 0.01], strict=False)
    ],
    "AS symbol_a": lambda symbols: [
        {"SYMBOL_A": "BTCUSDT", "SYMBOL_B": "ETHUSDT", "RETURN_CORRELATION": 0.93, "N_DAYS": 30}
    ],
    "MART_RISK_SIGNAL_DAILY": lambda symbols: [
        {
            "SYMBOL": "ETHUSDT",
            "SIGNAL_ID": "abnormal_move",
            "DAYS_FIRED": 1,
            "LAST_FIRED": date(2026, 10, 10),
            "LAST_VALUE": 3.47,
            "THRESHOLD": 3,
            "UNIT": "sigma",
        }
    ],  # fmt: skip
    "TREASURY_10Y_CHANGE_BPS": lambda symbols: [
        {
            "TREASURY_10Y_START": 4.1,
            "TREASURY_10Y_END": 4.0,
            "TREASURY_10Y_CHANGE_BPS": -10.0,
            "FED_FUNDS_RATE_START": 4.1,
            "FED_FUNDS_RATE_END": 3.9,
            "TREASURY_10Y_END_SOURCE_DATE": date(2026, 10, 23),
            "N_DAYS": 30,
        }
    ],  # fmt: skip
    "CPI_YOY": lambda symbols: [
        {
            "CPI_YOY_START": 0.029,
            "CPI_YOY_END": 0.03,
            "CPI_YOY_CHANGE_POINTS": 0.001,
            "CPI_MONTH_START": date(2026, 6, 1),
            "CPI_MONTH_END": date(2026, 9, 1),
            "N_RELEASES": 3,
        }
    ],  # fmt: skip
    "TVL_CHANGE": lambda symbols: [
        {"TVL_START": 5e10, "TVL_END": 4.5e10, "TVL_CHANGE": -0.1, "N_DAYS": 30}
    ],
}


class FakeWarehouse:
    def __init__(self, universe: list[dict] | None = None) -> None:
        self.universe = UNIVERSE if universe is None else universe
        self.queries: list[str] = []

    def execute(self, sql: str, params: Any = None, max_rows: int | None = None) -> list[Any]:
        if "INFORMATION_SCHEMA" in sql:
            return METADATA
        if "MART_ASSET_UNIVERSE\norder by" in sql:
            return self.universe
        self.queries.append(sql)
        symbols = [s for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT") if f"'{s}'" in sql]
        marker = next(key for key in RESULTS if key.upper() in sql.upper())
        return RESULTS[marker](symbols)


class WriterLLM:
    """Only the writer may be called: a brief never asks the model for a plan."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls = 0

    def generate_json(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> LLMResult:
        self.calls += 1
        assert kwargs["schema_name"] == "research_findings"
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return LLMResult(answer, LLMUsage(2000, 300, 0.0013), "gpt-4.1-mini", 0.8)


FINDINGS = {
    "findings": [
        {
            "claim": "BTC gained 5.20% over the 30 days while ETH fell 3.10%.",
            "evidence_ids": ["ev2"],
        },
        {
            "claim": "BTC and ETH moved together, with a correlation of 0.93.",
            "evidence_ids": ["ev3"],
        },
    ],
    "caveats": [],
}


def run(**kwargs: Any) -> Any:
    kwargs.setdefault("warehouse", FakeWarehouse())
    return generate_brief(["BTCUSDT", "ETHUSDT"], today=TODAY, **kwargs)


def test_the_plan_is_built_in_code_from_the_watchlist() -> None:
    # BRIEF-01: fixed order, TVL only for mapped chains, within the 10-task budget.
    tasks = build_brief_plan(["BTCUSDT", "ETHUSDT"], date(2026, 9, 26), DATA_AS_OF, tuple(UNIVERSE))

    assert [t["metric_id"] for t in tasks] == [
        "data_status", "watchlist_snapshot", "return_correlation_matrix", "risk_signals",
        "macro_rate_change", "inflation_change", "tvl_change", "tvl_change",
    ]  # fmt: skip
    assert [t["params"]["chain"] for t in tasks if t["metric_id"] == "tvl_change"] == [
        "Bitcoin",
        "Ethereum",
    ]
    assert tasks[5]["params"]["start_date"] == "2026-07-25"  # CPI looks back 92 days


def test_a_brief_runs_the_research_graph_without_a_planner_call() -> None:
    llm = WriterLLM(FINDINGS)

    brief = run(llm=llm)

    assert llm.calls == 1  # the writer only
    assert brief.status == "complete"
    assert len(brief.research.findings) == 2
    assert brief.start == date(2026, 9, 26) and brief.end == DATA_AS_OF
    assert [s["signal_id"] for s in brief.signals] == ["abnormal_move", "high_correlation"]


def test_an_asset_that_is_not_ready_is_left_out_and_named() -> None:
    # BRIEF-02
    universe = [*UNIVERSE, asset("SOLUSDT", "Solana", through=date(2026, 10, 1))]

    brief = generate_brief(
        ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ARBUSDT"],
        today=TODAY,
        llm=WriterLLM(FINDINGS),
        warehouse=FakeWarehouse(universe),
    )

    assert brief.symbols == ("BTCUSDT", "ETHUSDT")
    assert brief.excluded == (
        {"symbol": "SOLUSDT", "reason": "stale"},
        {"symbol": "ARBUSDT", "reason": "loading"},
    )
    assert brief.status == "partial"
    assert "Not included: SOLUSDT (stale)." in brief.markdown


def test_when_the_writer_fails_the_tables_and_evidence_remain() -> None:
    # BRIEF-03
    brief = run(llm=WriterLLM(LLMError("OpenAI call failed: 500")))

    assert brief.status == "partial" and brief.research.findings == []
    assert "| BTCUSDT |" in brief.markdown and "the writer failed" in brief.markdown
    assert "```sql" in brief.markdown


def test_without_the_llm_nothing_is_called_and_the_brief_is_still_built() -> None:
    llm = WriterLLM()

    brief = run(llm=llm, use_llm=False)

    assert llm.calls == 0
    assert brief.status == "partial"
    assert brief.research.usage.cost_usd == 0
    assert "the LLM was not used" in brief.markdown


def test_past_the_time_budget_tasks_stop_with_a_reason(monkeypatch) -> None:
    # BRIEF-04 and AI-06: no SQL after the budget, every skipped task says why.
    monkeypatch.setattr(brief_module, "MAX_SECONDS", -1.0)
    warehouse = FakeWarehouse()

    brief = run(llm=WriterLLM(), warehouse=warehouse)

    assert warehouse.queries == []
    assert brief.status == "error"
    assert {t["reason"] for t in brief.research.plan} == {"time budget spent"}


def test_the_markdown_has_every_section_and_the_disclaimer() -> None:
    # BRIEF-05
    markdown = run(llm=WriterLLM(FINDINGS)).markdown

    for heading in ("Market overview", "Watchlist performance", "Risk signals",
                    "Crypto–macro context", "Findings", "Data status",
                    "Evidence and SQL"):  # fmt: skip
        assert f"## {heading}" in markdown
    assert "not investment advice" in markdown
    assert "Best: BTCUSDT 5.20%; worst: ETHUSDT -3.10%" in markdown
    assert "3.47 sd" in markdown


def test_a_vietnamese_brief_has_vietnamese_headings() -> None:
    markdown = run(llm=WriterLLM(FINDINGS), language="vi").markdown

    assert "## Tín hiệu rủi ro" in markdown and "không phải khuyến nghị" in markdown


@pytest.mark.parametrize("symbols, window", [([], 30), (["BTCUSDT"] * 11, 30), (["BTCUSDT"], 3)])
def test_requests_outside_the_limits_are_refused(symbols: list[str], window: int) -> None:
    symbols = [f"X{i}USDT" for i in range(11)] if len(symbols) == 11 else symbols
    with pytest.raises(ValueError):
        generate_brief(symbols, window_days=window, warehouse=FakeWarehouse(), llm=WriterLLM())


def test_a_brief_of_a_past_day_ends_on_that_day() -> None:
    brief = run(llm=WriterLLM(FINDINGS), as_of=date(2025, 12, 31))

    assert (brief.start, brief.end) == (date(2025, 12, 2), date(2025, 12, 31))
