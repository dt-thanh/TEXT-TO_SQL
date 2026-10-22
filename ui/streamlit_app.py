"""FinSight AI in the browser: ask a question, see the answer, chart, data and SQL (spec §26).

A thin client. It calls the API (POST /ask, POST /research) and displays the response; it imports
nothing from src/ and holds no Snowflake or OpenAI secret. Two tabs:
- Quick SQL follows the spec top to bottom: ANSWER, CHART, RESULT DATA, GENERATED SQL, HOW THIS
  SQL WORKS. The SQL is never hidden.
- Research shows a short report: findings, the evidence behind each (values and SQL), caveats,
  and a Markdown download.

Run: make run (the API) and, in a second terminal, make ui → http://localhost:8501
"""

import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("FINSIGHT_API_URL", "http://localhost:8000")
# Two repairs mean three LLM calls and three queries; Snowflake stops each query after 30 s.
TIMEOUT_SECONDS = 120
EXAMPLES = [
    "",
    "Which asset had the highest 30-day volatility on 2026-09-01?",
    "Show Bitcoin's 7-day moving average closing price for the last 14 days.",
    "So sánh lợi nhuận trung bình mỗi ngày của BTC và ETH trong quý 2 năm 2025.",
    "ETH biến động thế nào vào những ngày lợi suất trái phiếu 10 năm trên 4.5%?",
]


RESEARCH_EXAMPLES = [
    "",
    "Lập báo cáo ngắn cho 30 ngày gần nhất: lợi nhuận BTC và ETH, lợi suất 10 năm và TVL Ethereum.",
    "When Ethereum TVL fell more than 10% in a week, was ETH more volatile than on other days?",
    "Trong những ngày lợi suất 10 năm tăng từ 10 bps trở lên năm 2025, BTC và ETH ra sao "
    "trong 30 ngày tiếp theo?",
    "What was the correlation of BTC and ETH daily returns in 2025, and their max drawdowns?",
]
STATUS_STYLE = {
    "complete": st.success,
    "partial": st.warning,
    "insufficient_data": st.warning,
    "declined": st.info,
    "error": st.error,
}


def call_api(path: str, question: str) -> dict[str, Any]:
    response = httpx.post(f"{API_URL}{path}", json={"question": question}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def ask_api(question: str) -> dict[str, Any]:
    return call_api("/ask", question)


def format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.6g}"
    return str(value)


def use_example() -> None:
    if st.session_state.example:
        st.session_state.question = st.session_state.example


def submit() -> None:
    """Runs before the rerun that the click starts. While `pending` is set the Ask button is
    drawn disabled, so impatient clicks cannot start more paid calls for the same question."""

    if st.session_state.question.strip():
        st.session_state.pending = st.session_state.question.strip()


def show_answer(data: dict[str, Any]) -> None:
    status, rows = data["status"], data["rows"]
    if status == "declined":
        st.info(data["explanation"] or "The data cannot answer this question.")
    elif status in ("blocked", "failed"):
        st.error(data["error"])
    elif not rows:
        st.warning("The query ran and returned no rows.")
    elif len(rows) == 1:
        for column, cell in zip(st.columns(len(rows[0])), rows[0].items(), strict=True):
            column.metric(label=cell[0], value=format_value(cell[1]))
    else:
        more = " (the first ones; there may be more)" if data["truncated"] else ""
        st.success(f"{len(rows)} rows{more}: see the chart and the table below.")


def show_chart(data: dict[str, Any]) -> None:
    chart = data["chart"]
    if not chart:
        return
    st.subheader("Chart")
    frame = pd.DataFrame(data["rows"])
    if chart["kind"] == "line":
        frame[chart["x"]] = pd.to_datetime(frame[chart["x"]])  # ISO text back to dates
        st.line_chart(frame, x=chart["x"], y=chart["y"], color=chart["color"])
    else:
        st.bar_chart(frame, x=chart["x"], y=chart["y"])


def show_details(data: dict[str, Any]) -> None:
    usage = data["usage"]
    with st.expander(f"Details: {data['repairs']} repair(s), ${usage['cost_usd']:.5f}"):
        st.write(
            f"Tokens: {usage['input_tokens']} in + {usage['output_tokens']} out. "
            f"Total {data['total_seconds']:.1f}s (LLM {data['llm_seconds']:.1f}s, "
            f"Snowflake {data['sql_seconds']:.1f}s)."
        )
        st.write("Semantic context used: " + (", ".join(data["retrieved"]) or "none"))
        for number, attempt in enumerate(data["failed_attempts"], start=1):
            st.write(f"Failed attempt {number}: {attempt['error']}")
            st.code(attempt["sql"], language="sql")


def show(data: dict[str, Any]) -> None:
    if data["data_as_of"]:
        st.caption(f"Data up to {data['data_as_of']} (UTC). The current day is not finished yet.")
    st.subheader("Answer")
    show_answer(data)
    show_chart(data)
    if data["rows"]:
        st.subheader("Result data")
        st.dataframe(data["rows"])
    st.subheader("Generated SQL")
    st.code(data["sql"] or "-- no SQL: the data cannot answer this question", language="sql")
    st.subheader("How this SQL works")
    st.markdown(data["explanation"])
    show_details(data)


def run_pending(prefix: str, path: str) -> None:
    """Call the API for the pending question of one tab, keep the result, redraw the screen.

    Results live in session_state: Streamlit reruns this whole script on every interaction.
    While `pending` is set the tab's button is drawn disabled, so impatient clicks cannot start
    more paid calls for the same question.
    """

    pending = st.session_state.get(f"{prefix}pending")
    if not pending:
        return
    with st.spinner("Working: reading the schema, running verified SQL on Snowflake..."):
        st.session_state.pop(f"{prefix}answer", None)
        st.session_state.pop(f"{prefix}problem", None)
        try:
            st.session_state[f"{prefix}answer"] = call_api(path, pending)
        except httpx.HTTPStatusError as err:
            st.session_state[f"{prefix}problem"] = (
                f"The API answered {err.response.status_code}: {err.response.text}"
            )
        except httpx.HTTPError:
            message = f"Cannot reach the API at {API_URL}. Is it up? (make run)"
            st.session_state[f"{prefix}problem"] = message
    del st.session_state[f"{prefix}pending"]
    st.rerun()  # draw the button enabled again


def quick_sql_tab() -> None:
    st.selectbox("Example questions", EXAMPLES, key="example", on_change=use_example)
    st.text_area("Your question", key="question", max_chars=500)
    pending = bool(st.session_state.get("pending"))
    st.button("Ask", type="primary", on_click=submit, disabled=pending)
    run_pending("", "/ask")
    if "problem" in st.session_state:
        st.error(st.session_state.problem)
    if "answer" in st.session_state:
        show(st.session_state.answer)


def use_research_example() -> None:
    if st.session_state.research_example:
        st.session_state.research_question = st.session_state.research_example


def submit_research() -> None:
    if st.session_state.research_question.strip():
        st.session_state.research_pending = st.session_state.research_question.strip()


def show_research(data: dict[str, Any]) -> None:
    window = data["analysis_window"]
    period = f"Period {window[0]} to {window[1]} (UTC). " if window else ""
    as_of = f"Data up to {data['data_as_of']} (UTC)." if data["data_as_of"] else ""
    st.caption(period + as_of)
    STATUS_STYLE[data["status"]](f"Status: {data['status']}")
    if data["status"] == "declined":
        st.write(data["decline_reason"])
    # The report already lays out findings, evidence with SQL, and caveats; skip its title line.
    report = data["report_markdown"]
    st.markdown(report.split("\n", 1)[1] if report.startswith("# ") else report)
    st.download_button(
        "Download report (Markdown)",
        data=report,
        file_name="finsight_research.md",
        mime="text/markdown",
    )


def research_tab() -> None:
    st.caption(
        "Multi-step questions across prices, US rates and DeFi TVL. The model only plans; every "
        "number comes from verified SQL shown in the report."
    )
    st.selectbox(
        "Example research questions",
        RESEARCH_EXAMPLES,
        key="research_example",
        on_change=use_research_example,
    )
    st.text_area("Your research question", key="research_question", max_chars=500)
    pending = bool(st.session_state.get("research_pending"))
    st.button("Research", type="primary", on_click=submit_research, disabled=pending)
    run_pending("research_", "/research")
    if "research_problem" in st.session_state:
        st.error(st.session_state.research_problem)
    if "research_answer" in st.session_state:
        show_research(st.session_state.research_answer)


st.set_page_config(page_title="FinSight AI", layout="wide")
st.title("FinSight AI")
st.caption(
    "Ask about Bitcoin, Ethereum, Solana and BNB, the US macro backdrop (Fed Funds rate, "
    "10-year Treasury yield) and DeFi TVL. Every answer comes with the SQL that produced it."
)
quick_tab, research_tab_ = st.tabs(["Quick SQL", "Research"])
with quick_tab:
    quick_sql_tab()
with research_tab_:
    research_tab()
