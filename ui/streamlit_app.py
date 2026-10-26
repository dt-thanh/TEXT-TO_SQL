"""FinSight AI in the browser: chat with the data, research reports, watchlists and daily briefs.

A thin client. It calls the API and displays the response; it imports nothing from src/ and holds
no Snowflake or OpenAI secret (in a deployment, only the API's service key, server-side). Tabs,
each opening with a short guide (what it is for, how, what you get):
- Ask: a chat about the data, with follow-ups ("and ETH?"). Every answer shows its number or
  table, a chart, and the SQL that produced it. The SQL is never hidden.
- Research report: a chat too, each answer a short report with evidence and SQL for every number.
- Watchlist & Daily Brief (FinSight Pulse): watchlists, coins added on demand, the morning brief.

The interface language (VI/EN, top right) changes the labels and the default brief language;
answers follow the language of the question. It is kept in the URL (?lang=vi).

Run: make run (the API) and, in a second terminal, make ui → http://127.0.0.1:8501
"""

import os
from collections.abc import Callable
from typing import Any

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("FINSIGHT_API_URL", "http://localhost:8000")
# AUTH_MODE=deployed: the API wants this key. Read from the UI's own environment, never shown.
SERVICE_KEY = os.environ.get("FINSIGHT_SERVICE_KEY", "")
HEADERS = {"X-API-Key": SERVICE_KEY} if SERVICE_KEY else {}
DEFAULT_LANGUAGE = os.environ.get("FINSIGHT_UI_LANGUAGE", "vi")
# Two repairs mean three LLM calls and three queries; Snowflake stops each query after 30 s.
TIMEOUT_SECONDS = 120
BRIEF_TIMEOUT_SECONDS = 150  # a brief may run 90 s
CHAT_TURNS_SENT = 4  # earlier turns sent with a message, for follow-ups

TEXT = {
    "en": {
        "subtitle": "Crypto prices (BTC, ETH, SOL, BNB and the coins you add), US rates and CPI, "
        "DeFi TVL. Every number comes with the SQL that produced it.",
        "tab_chat": "💬 Ask",
        "tab_research": "🔎 Research report",
        "tab_pulse": "📋 Watchlist & Daily Brief",
        "about_chat": "**What it is for:** quick lookups of one number or one table: prices, "
        "returns, volatility, US rates and CPI, DeFi TVL.  \n**How:** ask in English or "
        "Vietnamese, then follow up (“and ETH?”, “and in August?”).  \n**You get:** the "
        "answer, a chart and the SQL that ran on Snowflake. No advice, no forecasts.",
        "about_research": "**What it is for:** analysis questions that need several metrics or "
        "sources (prices + rates + DeFi TVL), e.g. “how did BTC and ETH move when the 10-year "
        "yield jumped?”.  \n**How:** ask, then follow up as in Ask.  \n**You get:** a short "
        "report: findings, the evidence and SQL behind every number, caveats; downloadable. The "
        "AI only picks verified metrics; SQL computes every number (about 3–10 s).",
        "about_pulse": "**What it is for:** following the coins you care about, every day.  \n"
        "**How:** pick or create a watchlist, add coins (typos get suggestions), press "
        "*Generate Daily Brief*.  \n**You get:** each coin's performance, risk signals by fixed "
        "rules, rates/inflation/DeFi context; Airflow also makes one every morning. Signals "
        "describe the past: they are not advice.",
        "chat_placeholder": "Ask a question about the data…",
        "research_placeholder": "Ask a research question…",
        "chat_new": "New chat",
        "chat_examples": "Try asking:",
        "chat_working": "Reading the schema, writing and checking SQL, running it on Snowflake…",
        "research_working": "Planning, running verified SQL, checking every number…",
        "understood": "Understood as",
        "answer_rows": "{n} rows{more}: see the chart and the table.",
        "more_rows": " (the first ones; there may be more)",
        "no_rows": "The query ran and returned no rows.",
        "cannot_answer": "The data cannot answer this question.",
        "data_up_to": "Data up to {day} (UTC); today is not finished yet.",
        "no_sql": "-- no SQL: the data cannot answer this question",
        "data_and_steps": "Data and how this SQL works",
        "details": "Details: {repairs} repair(s), ${cost:.5f}, {seconds:.1f}s",
        "failed_attempt": "Failed attempt {n}: {error}",
        "unreachable": "Cannot reach the API at {url}. Is it up? (make run)",
        "period": "Period {start} to {end} (UTC). ",
        "status": "Status: {status}",
        "download_report": "Download report (Markdown)",
        "health": "Prices through {prices} · DeFi TVL through {tvl} · today's brief: {briefs} · "
        "LLM today ${spent:.4f} of ${cap:.2f}",
        "not_yet": "not yet",
        "behind": "Prices are more than a day behind: the daily pipeline may have failed.",
        "watchlist": "Watchlist",
        "new_watchlist": "New watchlist (name, then add a coin)",
        "refresh": "Refresh",
        "first_coin": "Add the first coin to create “{name}”.",
        "loading_note": "⏳ Loading: history is being backfilled (usually a few minutes). "
        "Press Refresh.",
        "add_coins": "Add coins (tickers or pairs, separated by commas or spaces)",
        "check": "Check",
        "add_valid": "Add {n} valid coin(s)",
        "done": "Done. ",
        "remove": "Remove from watchlist",
        "remove_button": "Remove selected",
        "col_asset": "asset",
        "col_status": "status",
        "col_from": "data from",
        "col_through": "data through",
        "col_note": "note",
        "col_typed": "you typed",
        "col_pair": "pair",
        "col_result": "result",
        "col_mean": "did you mean",
        "will_add": "✅ will be added",
        "core": "✅ core asset",
        "already": "✅ already added",
        "in_list": "✅ already in this watchlist",
        "brief": "Daily brief",
        "brief_days": "Period (days)",
        "brief_language": "Brief language",
        "brief_button": "Generate Daily Brief",
        "brief_working": "Building the brief: verified SQL for every asset, then the findings…",
        "made_now": "Made now · {seconds:.1f}s · ${cost:.5f}",
        "saved_briefs": "Saved briefs",
        "no_brief": "No saved brief yet: Airflow makes one each morning after the data is loaded.",
        "download_brief": "Download brief (Markdown)",
    },
    "vi": {
        "subtitle": "Giá crypto (BTC, ETH, SOL, BNB và các coin bạn thêm), lãi suất và CPI Mỹ, "
        "TVL DeFi. Mọi con số đều kèm câu SQL tạo ra nó.",
        "tab_chat": "💬 Hỏi đáp",
        "tab_research": "🔎 Báo cáo nghiên cứu",
        "tab_pulse": "📋 Watchlist & Báo cáo ngày",
        "about_chat": "**Dùng để:** tra nhanh một con số hoặc một bảng: giá, lợi nhuận, độ biến "
        "động, lãi suất và CPI Mỹ, TVL DeFi.  \n**Cách dùng:** hỏi bằng tiếng Việt hoặc tiếng "
        "Anh, rồi hỏi tiếp (“còn ETH thì sao?”, “còn tháng 8?”).  \n**Bạn nhận được:** câu trả "
        "lời, biểu đồ và câu SQL đã chạy trên Snowflake. Không tư vấn, không dự đoán giá.",
        "about_research": "**Dùng để:** câu hỏi phân tích cần nhiều chỉ số hoặc nhiều nguồn (giá "
        "+ lãi suất + TVL DeFi), ví dụ “khi lợi suất 10 năm tăng mạnh, BTC và ETH biến động ra "
        "sao?”.  \n**Cách dùng:** đặt câu hỏi, rồi hỏi tiếp như tab Hỏi đáp.  \n**Bạn nhận "
        "được:** báo cáo ngắn gồm nhận định, bằng chứng và SQL cho từng con số, các lưu ý; tải "
        "về được. AI chỉ chọn chỉ số đã kiểm chứng, SQL tính mọi con số (khoảng 3–10 giây).",
        "about_pulse": "**Dùng để:** theo dõi hằng ngày các coin bạn quan tâm.  \n**Cách dùng:** "
        "chọn hoặc tạo watchlist, thêm coin (gõ sai sẽ được gợi ý), bấm *Tạo báo cáo ngày*.  \n"
        "**Bạn nhận được:** hiệu suất từng coin, tín hiệu rủi ro theo luật cố định, bối cảnh lãi "
        "suất/lạm phát/DeFi; mỗi sáng Airflow cũng tự tạo một bản. Tín hiệu mô tả quá khứ, không "
        "phải lời khuyên.",
        "chat_placeholder": "Đặt câu hỏi về dữ liệu…",
        "research_placeholder": "Đặt câu hỏi nghiên cứu…",
        "chat_new": "Cuộc trò chuyện mới",
        "chat_examples": "Thử hỏi:",
        "chat_working": "Đang đọc schema, viết và kiểm tra SQL, chạy trên Snowflake…",
        "research_working": "Đang lập kế hoạch, chạy SQL đã kiểm chứng, kiểm tra từng con số…",
        "understood": "Hiểu là",
        "answer_rows": "{n} dòng{more}: xem biểu đồ và bảng.",
        "more_rows": " (những dòng đầu; có thể còn nữa)",
        "no_rows": "Câu SQL đã chạy nhưng không có dòng nào.",
        "cannot_answer": "Dữ liệu không trả lời được câu hỏi này.",
        "data_up_to": "Dữ liệu đến hết ngày {day} (UTC); hôm nay chưa kết thúc.",
        "no_sql": "-- không có SQL: dữ liệu không trả lời được câu hỏi này",
        "data_and_steps": "Dữ liệu và cách câu SQL hoạt động",
        "details": "Chi tiết: {repairs} lần sửa, ${cost:.5f}, {seconds:.1f}s",
        "failed_attempt": "Lần thử lỗi {n}: {error}",
        "unreachable": "Không kết nối được API tại {url}. API đã chạy chưa? (make run)",
        "period": "Kỳ {start} đến {end} (UTC). ",
        "status": "Trạng thái: {status}",
        "download_report": "Tải báo cáo (Markdown)",
        "health": "Giá đến {prices} · TVL DeFi đến {tvl} · báo cáo hôm nay: {briefs} · "
        "LLM hôm nay ${spent:.4f} / ${cap:.2f}",
        "not_yet": "chưa có",
        "behind": "Giá chậm hơn một ngày: pipeline hằng ngày có thể đã lỗi.",
        "watchlist": "Watchlist",
        "new_watchlist": "Watchlist mới (đặt tên, rồi thêm coin)",
        "refresh": "Làm mới",
        "first_coin": "Thêm coin đầu tiên để tạo “{name}”.",
        "loading_note": "⏳ Đang tải: đang nạp lịch sử giá (thường vài phút). Bấm Làm mới.",
        "add_coins": "Thêm coin (ticker hoặc cặp, cách nhau bởi dấu phẩy hoặc khoảng trắng)",
        "check": "Kiểm tra",
        "add_valid": "Thêm {n} coin hợp lệ",
        "done": "Xong. ",
        "remove": "Xoá khỏi watchlist",
        "remove_button": "Xoá các coin đã chọn",
        "col_asset": "coin",
        "col_status": "trạng thái",
        "col_from": "dữ liệu từ",
        "col_through": "dữ liệu đến",
        "col_note": "ghi chú",
        "col_typed": "bạn gõ",
        "col_pair": "cặp",
        "col_result": "kết quả",
        "col_mean": "có phải ý bạn là",
        "will_add": "✅ sẽ được thêm",
        "core": "✅ coin core",
        "already": "✅ đã thêm trước đó",
        "in_list": "✅ đã có trong watchlist",
        "brief": "Báo cáo ngày",
        "brief_days": "Kỳ (ngày)",
        "brief_language": "Ngôn ngữ báo cáo",
        "brief_button": "Tạo báo cáo ngày",
        "brief_working": "Đang tạo báo cáo: SQL đã kiểm chứng cho từng coin, rồi phần nhận định…",
        "made_now": "Vừa tạo · {seconds:.1f}s · ${cost:.5f}",
        "saved_briefs": "Báo cáo đã lưu",
        "no_brief": "Chưa có báo cáo đã lưu: Airflow tạo một bản mỗi sáng sau khi nạp dữ liệu.",
        "download_brief": "Tải báo cáo (Markdown)",
    },
}
CHAT_EXAMPLES = {
    "en": [
        "What was BTC's average close in September 2026?",
        "Which asset had the highest 30-day volatility yesterday?",
        "Show Bitcoin's 7-day moving average close for the last 14 days.",
    ],
    "vi": [
        "Giá đóng cửa trung bình của BTC tháng 9 năm 2026?",
        "Coin nào có độ biến động 30 ngày cao nhất hôm qua?",
        "ETH biến động thế nào vào những ngày lợi suất 10 năm trên 4.5%?",
    ],
}
RESEARCH_EXAMPLES = {
    "en": [
        "Short report for the last 30 days: BTC and ETH returns, the 10-year yield, Ethereum TVL.",
        "When Ethereum TVL fell more than 10% in a week, was ETH more volatile than on other days?",
        "Correlation of BTC and ETH daily returns in 2025, and their max drawdowns?",
    ],
    "vi": [
        "Báo cáo 30 ngày gần nhất: lợi nhuận BTC và ETH, lợi suất 10 năm và TVL Ethereum.",
        "Những ngày lợi suất 10 năm tăng từ 10 bps trở lên năm 2025, BTC và ETH ra sao trong 30 "
        "ngày tiếp theo?",
        "Tương quan lợi nhuận ngày của BTC và ETH năm 2025, và mức sụt giảm lớn nhất của "
        "từng đồng?",
    ],
}
STATUS_STYLE = {
    "complete": st.success,
    "partial": st.warning,
    "insufficient_data": st.warning,
    "declined": st.info,
    "error": st.error,
}
STATUS_ICON = {"ready": "🟢", "loading": "⏳", "stale": "🟠", "error": "🔴", "unsupported": "⛔",
               "disabled": "⚪"}  # fmt: skip


def lang() -> str:
    return st.session_state.get("lang", DEFAULT_LANGUAGE)


def t(key: str, **values: Any) -> str:
    text = TEXT[lang()].get(key) or TEXT["en"][key]
    return text.format(**values) if values else text


def guide(key: str) -> None:
    """The short box at the top of a tab: what it is for, how to use it, what you get."""

    with st.container(border=True):
        st.markdown(t(key))


class ApiProblem(Exception):
    pass


def api(method: str, path: str, **kwargs: Any) -> Any:
    try:
        response = httpx.request(
            method, f"{API_URL}{path}", headers=HEADERS, timeout=kwargs.pop("timeout", 30), **kwargs
        )
    except httpx.HTTPError as err:
        raise ApiProblem(t("unreachable", url=API_URL)) from err
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiProblem(f"{response.status_code}: {detail}")
    return response.json() if response.content else None


def post(path: str, body: dict[str, Any], timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """POST for the LLM routes. Errors become ApiProblem with the reason."""

    try:
        response = httpx.post(f"{API_URL}{path}", json=body, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as err:
        try:
            detail = err.response.json().get("detail", err.response.text)
        except ValueError:
            detail = err.response.text
        raise ApiProblem(f"{err.response.status_code}: {detail}") from err
    except httpx.HTTPError as err:
        raise ApiProblem(t("unreachable", url=API_URL)) from err
    return response.json()


def format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.6g}"
    return str(value)


# --- A conversation (used by Ask and Research report) -------------------------------------------


def conversation(
    key: str,
    path: str,
    examples: list[str],
    placeholder: str,
    working: str,
    show_answer: Callable[[dict[str, Any], int], None],
) -> None:
    """A chat tab: suggested questions while it is empty, messages, an input box at the bottom.

    The conversation lives in session_state[key]; each message is sent with the recent turns so
    the API can understand follow-ups. One message is one paid call.
    """

    def ask_example(text: str) -> None:
        st.session_state[f"{key}_example"] = text

    def clear() -> None:
        st.session_state[key] = []

    messages_box = st.container()  # above the input box, filled after a message is sent
    typed = st.chat_input(placeholder, max_chars=500, key=f"{key}_input")
    question = typed or st.session_state.pop(f"{key}_example", None)
    with messages_box:
        if question:
            send(key, path, question.strip(), working)
        messages = st.session_state.get(key, [])
        if not messages:
            st.caption(t("chat_examples"))
            for number, example in enumerate(examples):
                st.button(example, key=f"{key}_example_{number}", on_click=ask_example,
                          args=(example,))  # fmt: skip
        for number, message in enumerate(messages):
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.markdown(message["text"])
                elif "problem" in message:
                    st.error(message["problem"])
                else:
                    data = message["data"]
                    if data["standalone_question"]:
                        st.caption(f"↳ {t('understood')}: “{data['standalone_question']}”")
                    if data["kind"] == "answer":
                        show_answer(data, number)
                    else:
                        st.markdown(data["reply"])
    # Drawn last, so it is enabled as soon as the first message is in the conversation.
    st.button(t("chat_new"), key=f"{key}_new", on_click=clear,
              disabled=not st.session_state.get(key))  # fmt: skip


def send(key: str, path: str, text: str, working: str) -> None:
    messages = st.session_state.setdefault(key, [])
    history = [m["data"]["turn"] for m in messages if m["role"] == "assistant" and "data" in m]
    messages.append({"role": "user", "text": text})
    with st.spinner(working):
        try:
            data = post(path, {"message": text, "history": history[-CHAT_TURNS_SENT:]})
            messages.append({"role": "assistant", "data": data})
        except ApiProblem as err:
            messages.append({"role": "assistant", "problem": str(err)})


# --- Ask ----------------------------------------------------------------------------------------


def show_result(data: dict[str, Any]) -> None:
    status, rows = data["status"], data["rows"]
    if status == "declined":
        st.info(data["explanation"] or t("cannot_answer"))
    elif status in ("blocked", "failed"):
        st.error(data["error"])
    elif not rows:
        st.warning(t("no_rows"))
    elif len(rows) == 1:
        for column, cell in zip(st.columns(len(rows[0])), rows[0].items(), strict=True):
            column.metric(label=cell[0], value=format_value(cell[1]))
    else:
        more = t("more_rows") if data["truncated"] else ""
        st.success(t("answer_rows", n=len(rows), more=more))


def show_chart(data: dict[str, Any]) -> None:
    chart = data["chart"]
    if not chart:
        return
    frame = pd.DataFrame(data["rows"])
    if chart["kind"] == "line":
        frame[chart["x"]] = pd.to_datetime(frame[chart["x"]])  # ISO text back to dates
        st.line_chart(frame, x=chart["x"], y=chart["y"], color=chart["color"])
    else:
        st.bar_chart(frame, x=chart["x"], y=chart["y"])


def show_data_answer(message: dict[str, Any], number: int) -> None:
    """One Ask answer: the number or table, a chart, the SQL (never hidden), then the data, the
    explanation and the costs in an expander."""

    data = message["answer"]
    show_result(data)
    show_chart(data)
    st.code(data["sql"] or t("no_sql"), language="sql")
    if data["data_as_of"]:
        st.caption(t("data_up_to", day=data["data_as_of"]))
    usage = data["usage"]
    with st.expander(t("data_and_steps")):
        if data["rows"]:
            st.dataframe(data["rows"])
        st.markdown(data["explanation"])
        st.caption(t("details", repairs=data["repairs"], cost=usage["cost_usd"],
                     seconds=data["total_seconds"]))  # fmt: skip
        for attempt_number, attempt in enumerate(data["failed_attempts"], start=1):
            st.write(t("failed_attempt", n=attempt_number, error=attempt["error"]))
            st.code(attempt["sql"], language="sql")


def chat_tab() -> None:
    guide("about_chat")
    conversation("chat", "/chat", CHAT_EXAMPLES[lang()], t("chat_placeholder"),
                 t("chat_working"), show_data_answer)  # fmt: skip


# --- Research report ----------------------------------------------------------------------------


def show_report(message: dict[str, Any], number: int) -> None:
    data = message["research"]
    window = data["analysis_window"]
    period = t("period", start=window[0], end=window[1]) if window else ""
    as_of = t("data_up_to", day=data["data_as_of"]) if data["data_as_of"] else ""
    st.caption(period + as_of)
    STATUS_STYLE[data["status"]](t("status", status=data["status"]))
    if data["status"] == "declined":
        st.write(data["decline_reason"])
    # The report already lays out findings, evidence with SQL, and caveats; skip its title line.
    report = data["report_markdown"]
    st.markdown(report.split("\n", 1)[1] if report.startswith("# ") else report)
    st.download_button(t("download_report"), data=report, key=f"report_{number}",
                       file_name="finsight_research.md", mime="text/markdown")  # fmt: skip


def research_tab() -> None:
    guide("about_research")
    conversation("research_chat", "/research/chat", RESEARCH_EXAMPLES[lang()],
                 t("research_placeholder"), t("research_working"), show_report)  # fmt: skip


# --- Watchlist & Daily Brief (FinSight Pulse) ---------------------------------------------------


@st.cache_data(ttl=60, show_spinner=False)
def cached_get(path: str) -> Any:
    """GETs are cached a minute: Streamlit reruns the page on every click, and each GET may wake
    the Snowflake warehouse. Writes clear the cache."""

    return api("GET", path)


def changed() -> None:
    cached_get.clear()


def system_status() -> None:
    try:
        health = cached_get("/health/data")
    except ApiProblem as err:
        st.warning(str(err))
        return
    usage, sources = health["llm_usage"], health["sources"]
    briefs = ", ".join(f"{k}: {v}" for k, v in health["briefs_today"].items()) or t("not_yet")
    st.caption(t("health", prices=sources.get("prices_through"), tvl=sources.get("tvl_through"),
                 briefs=briefs, spent=usage["spent_usd"], cap=usage["cap_usd"]))  # fmt: skip
    if not health["data_ok"]:
        st.warning(t("behind"))
    for asset in health["assets_needing_attention"]:
        st.error(f"{asset['symbol']}: {asset['status']} — {asset.get('last_error') or ''}")


def show_watchlist(assets: list[dict[str, Any]]) -> None:
    rows = [
        {"": STATUS_ICON.get(a["status"], ""), t("col_asset"): a["symbol"],
         t("col_status"): a["status"], t("col_from"): a["data_from"],
         t("col_through"): a["data_through"], t("col_note"): a["error"] or ""}
        for a in assets
    ]  # fmt: skip
    st.dataframe(rows, hide_index=True)
    if any(a["status"] == "loading" for a in assets):
        st.caption(t("loading_note"))


def show_check(results: list[dict[str, Any]]) -> None:
    action = {"add": "will_add", "core": "core", "already_added": "already",
              "already_in_watchlist": "in_list"}  # fmt: skip
    rows = []
    for r in results:
        result = t(action.get(r["action"], "will_add")) if r["ok"] else "❌ " + r["message"]
        rows.append({t("col_typed"): r["input"], t("col_pair"): r["symbol"] or "—",
                     t("col_result"): result,
                     t("col_mean"): ", ".join(r.get("suggestions") or [])})  # fmt: skip
    st.dataframe(rows, hide_index=True)


def edit_watchlist(name: str, symbols: list[str]) -> None:
    """Type coins freely ('link, avax arbb'), check them against Binance, add the right ones.
    A typo is reported with what was probably meant; it never blocks the other coins."""

    left, right = st.columns(2)
    with left:
        text = st.text_input(t("add_coins"), key="coin_text", max_chars=400,
                             placeholder="link, avax, arb")  # fmt: skip
        check, add = st.columns(2)
        if check.button(t("check"), disabled=not text.strip()):
            try:
                results = api("POST", "/assets/check", json={"text": text})
                st.session_state.coin_check = {"text": text, "results": results}
            except ApiProblem as err:
                st.error(str(err))
        checked = st.session_state.get("coin_check")
        if checked and checked["text"] == text:
            show_check(checked["results"])
            valid = [r for r in checked["results"] if r["ok"]]
            if add.button(t("add_valid", n=len(valid)), type="primary", disabled=not valid):
                add_coins(name, " ".join(r["symbol"] for r in valid))
        report = st.session_state.pop("coin_added", None)
        if report:
            st.success(t("done") + "; ".join(f"{r['symbol'] or r['input']}: {r['message']}"
                                             for r in report))  # fmt: skip
    with right:
        remove = st.multiselect(t("remove"), symbols, key="coin_remove")
        if st.button(t("remove_button"), disabled=not remove or len(remove) == len(symbols)):
            save_watchlist(name, [s for s in symbols if s not in remove])


def add_coins(name: str, text: str) -> None:
    try:
        result = api("POST", f"/watchlists/{name}/add", json={"text": text})
    except ApiProblem as err:
        st.error(str(err))
        return
    st.session_state.coin_added = result["results"]
    st.session_state.pop("coin_check", None)
    changed()
    st.rerun()


def save_watchlist(name: str, symbols: list[str]) -> None:
    try:
        api("PUT", f"/watchlists/{name}", json={"symbols": symbols})
        changed()
        st.rerun()
    except ApiProblem as err:
        st.error(str(err))


def submit_brief() -> None:
    st.session_state.brief_pending = True


def brief_section(name: str) -> None:
    st.subheader(t("brief"))
    left, mid, right = st.columns(3)
    window = left.radio(t("brief_days"), [7, 30, 90, 365], index=1, horizontal=True,
                        key="brief_window")  # fmt: skip
    languages = ["vi", "en"] if lang() == "vi" else ["en", "vi"]
    language = mid.radio(t("brief_language"), languages, horizontal=True, key="brief_language")
    pending = bool(st.session_state.get("brief_pending"))
    right.button(t("brief_button"), type="primary", on_click=submit_brief, disabled=pending)
    if pending:
        with st.spinner(t("brief_working")):
            st.session_state.pop("brief_problem", None)
            try:
                body = {"watchlist": name, "window_days": window, "language": language}
                st.session_state.brief = api("POST", "/brief", json=body,
                                             timeout=BRIEF_TIMEOUT_SECONDS)  # fmt: skip
                changed()
            except ApiProblem as err:
                st.session_state.brief_problem = str(err)
        del st.session_state.brief_pending
        st.rerun()
    if "brief_problem" in st.session_state:
        st.error(st.session_state.brief_problem)

    brief = st.session_state.get("brief")
    if brief and brief.get("watchlist_name") == name:
        markdown = brief["markdown"]
        st.caption(t("made_now", seconds=brief["seconds"], cost=brief["usage"]["cost_usd"]))
    else:
        markdown = saved_brief(name)
    if markdown:
        STATUS_STYLE.get(status_of(markdown), st.info)(t("status", status=status_of(markdown)))
        st.markdown(markdown.split("\n", 1)[1] if markdown.startswith("# ") else markdown)
        st.download_button(t("download_brief"), data=markdown,
                           file_name=f"finsight_brief_{name}.md", mime="text/markdown")  # fmt: skip


def status_of(markdown: str) -> str:
    for status in STATUS_STYLE:
        if f"Status: **{status}**" in markdown:
            return status
    return "partial"


def saved_brief(name: str) -> str | None:
    """The newest saved brief of the watchlist (made by Airflow each morning), if any."""

    try:
        saved = cached_get(f"/briefs?watchlist={name}&limit=7")
    except ApiProblem as err:
        st.warning(str(err))
        return None
    if not saved:
        st.info(t("no_brief"))
        return None
    days = [b["brief_date"] for b in saved]
    day = st.selectbox(t("saved_briefs"), days, key="brief_day")
    try:
        return cached_get(f"/briefs/{day}?watchlist={name}")["markdown"]
    except ApiProblem as err:
        st.warning(str(err))
        return None


def pulse_tab() -> None:
    guide("about_pulse")
    system_status()
    try:
        lists = cached_get("/watchlists")
    except ApiProblem as err:
        st.error(str(err))
        return
    names = list(lists)
    top_left, top_mid, top_right = st.columns([2, 2, 1])
    name = top_left.selectbox(t("watchlist"), names, key="watchlist_name")
    new_name = top_mid.text_input(t("new_watchlist"), key="new_watchlist", max_chars=30,
                                  disabled=len(names) >= 3)  # fmt: skip
    if top_right.button(t("refresh")):
        changed()
        st.rerun()
    if new_name.strip() and new_name.strip().lower() not in names:
        name, symbols = new_name.strip().lower(), []
        st.caption(t("first_coin", name=name))
    else:
        symbols = [a["symbol"] for a in lists[name]]
        show_watchlist(lists[name])
    edit_watchlist(name, symbols)
    if symbols:
        brief_section(name)


# --- Page ---------------------------------------------------------------------------------------


def language_switch() -> None:
    """VI / EN at the top right; kept in the URL so a reload keeps it."""

    if "lang" not in st.session_state:
        wanted = st.query_params.get("lang", DEFAULT_LANGUAGE)
        st.session_state.lang = wanted if wanted in TEXT else "en"
    st.segmented_control("Language", ["VI", "EN"], default=lang().upper(), key="lang_switch",
                         label_visibility="collapsed", on_change=switch_language)  # fmt: skip


def switch_language() -> None:
    picked = st.session_state.lang_switch
    if picked:  # clicking the selected option again clears it: keep the language then
        st.session_state.lang = picked.lower()
        st.query_params["lang"] = picked.lower()


st.set_page_config(page_title="FinSight AI", layout="wide")
title, switch = st.columns([6, 1])
with switch:
    language_switch()
with title:
    st.title("FinSight AI")
st.caption(t("subtitle"))
chat_tab_, research_tab_, pulse_tab_ = st.tabs([t("tab_chat"), t("tab_research"), t("tab_pulse")])
with chat_tab_:
    chat_tab()
with research_tab_:
    research_tab()
with pulse_tab_:
    pulse_tab()
