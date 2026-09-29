"""FinSight AI in the browser: ask a question, see the answer, chart, data and SQL (spec §26).

A thin client. It calls the API's POST /ask and displays the response; it imports nothing from
src/ and holds no Snowflake or OpenAI secret. The screen follows the spec top to bottom:
ANSWER, CHART, RESULT DATA, GENERATED SQL, HOW THIS SQL WORKS. The SQL is never hidden.

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


def ask_api(question: str) -> dict[str, Any]:
    response = httpx.post(f"{API_URL}/ask", json={"question": question}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.6g}"
    return str(value)


def use_example() -> None:
    if st.session_state.example:
        st.session_state.question = st.session_state.example


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


st.set_page_config(page_title="FinSight AI", layout="wide")
st.title("FinSight AI")
st.caption(
    "Ask about Bitcoin, Ethereum, Solana and BNB and the US macro backdrop (Fed Funds rate, "
    "10-year Treasury yield). Every answer comes with the SQL that produced it."
)
st.selectbox("Example questions", EXAMPLES, key="example", on_change=use_example)
question = st.text_area("Your question", key="question", max_chars=500)

if st.button("Ask", type="primary") and question.strip():
    with st.spinner("Reading the schema, writing SQL, checking it and running it on Snowflake..."):
        try:
            # Kept in session_state: Streamlit reruns this whole script on every click.
            st.session_state.answer = ask_api(question)
        except httpx.HTTPStatusError as err:
            st.session_state.pop("answer", None)
            st.error(f"The API answered {err.response.status_code}: {err.response.text}")
        except httpx.HTTPError:
            st.session_state.pop("answer", None)
            st.error(f"Cannot reach the API at {API_URL}. Is it running (make run)?")

if "answer" in st.session_state:
    show(st.session_state.answer)
