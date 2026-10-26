"""Quick SQL and research as conversations: follow-ups, greetings and out-of-scope requests.

The Text-to-SQL agent answers ONE complete question; this module turns a chat message into one:

- greetings, "what can you do?" and requests for investment advice or forecasts are recognized by
  rules and answered at once: no LLM call, no SQL;
- the first data question goes to the agent unchanged, exactly as POST /ask (and the benchmark)
  sends it;
- a later message is first rewritten by the model into a standalone question using the earlier
  turns ("and ETH?" -> "What was ETH's average close in September 2026?"), and the rewrite is
  shown to the analyst, so a wrong reading is visible. The same call recognizes small talk and
  out-of-scope messages, which get a short reply instead of SQL.

The server keeps no conversation: the client sends the recent turns with each message. The same
logic serves research mode: only the function that answers a standalone question and the way a
result is summarized for the next turn differ.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from src.agents.research.writing import language_of
from src.agents.sql_generation import PROMPTS_DIR
from src.agents.text_to_sql import Answer, answer_question
from src.semantic.retriever import normalize
from src.services.llm import LLMClient, LLMUsage

logger = logging.getLogger(__name__)

MAX_TURNS = 4  # earlier turns given to the rewriter: enough for follow-ups, cheap in tokens

GREETING = re.compile(
    r"^(hi|hello|hey|chao|xin chao|alo|hello there|chao ban|cam on|thanks|thank you)\b.{0,20}$"
)
HELP = re.compile(
    r"\b(what can you do|how do i use|help me use|ban lam duoc gi|ban co the lam gi"
    r"|huong dan su dung|dung the nao|hoi duoc gi)\b"
)
ADVICE = re.compile(
    r"\b(nen mua|nen ban|co nen mua|co nen ban|mua hay ban|mua coin nao|dau tu vao|"
    r"should i (buy|sell|invest)|buy or sell|which coin (should|to) buy|investment advice|"
    r"du doan gia|price prediction|predict the price|forecast|gia .{0,20} se (tang|giam|len|xuong)|"
    r"will .{0,25} (go up|go down|rise|fall|pump|dump))\b"
)

REPLIES = {
    "en": {
        "smalltalk": "Hi! Ask me about crypto prices, returns and volatility, US interest rates "
        'and CPI, or DeFi TVL. For example: "What was BTC\'s average close last month?", then '
        'follow up with "and ETH?".',
        "advice": "I can't give investment advice or price forecasts. I can show what the data "
        'says, for example: "How volatile was BTC over the last 30 days?"',
    },
    "vi": {
        "smalltalk": "Chào bạn! Bạn có thể hỏi về giá, lợi nhuận, độ biến động của crypto, lãi "
        'suất và lạm phát CPI của Mỹ, hoặc TVL DeFi. Ví dụ: "Giá đóng cửa trung bình của BTC '
        'tháng trước?", rồi hỏi tiếp "còn ETH thì sao?".',
        "advice": "Mình không đưa ra lời khuyên đầu tư hay dự đoán giá. Mình có thể cho bạn xem "
        'dữ liệu, ví dụ: "Độ biến động của BTC trong 30 ngày qua là bao nhiêu?"',
    },
}

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["data", "smalltalk", "out_of_scope"]},
        "standalone_question": {"type": "string"},
        "reply": {"type": "string"},
    },
    "required": ["kind", "standalone_question", "reply"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Turn:
    """One earlier exchange, as the client sends it back."""

    question: str  # as typed
    standalone: str  # as FinSight understood it
    summary: str = ""  # a few result values, so "compared with that?" can be resolved


@dataclass(frozen=True)
class ChatReply:
    kind: str  # answer | smalltalk | declined
    message: str
    standalone: str | None = None  # the question the agent answered, when it differs
    answer: Any = None  # Answer (Quick SQL) or ResearchAnswer
    reply: str | None = None
    usage: LLMUsage = field(default_factory=lambda: LLMUsage(0, 0, 0.0))  # the rewrite only


def chat_language(text: str) -> str:
    words = set(normalize(text).split())
    return "vi" if language_of(text) == "vi" or words & {"chao", "ban", "toi", "minh"} else "en"


def by_rule(message: str) -> str | None:
    """'smalltalk' or 'advice' when a rule recognizes the message, else None."""

    text = normalize(message)
    if ADVICE.search(text):
        return "advice"
    if GREETING.match(text) or HELP.search(text):
        return "smalltalk"
    return None


@lru_cache
def rewriter_prompt() -> str:
    return (PROMPTS_DIR / "chat_rewriter.md").read_text(encoding="utf-8")


def summarize_research(answer: Any, max_findings: int = 2) -> str:
    """The first findings of a research answer, for the next rewrite."""

    claims = [finding["claim"] for finding in answer.findings[:max_findings]]
    return " ".join(claims)[:600] if claims else answer.status


def summarize(answer: Answer, max_rows: int = 3) -> str:
    """A few result values for the next rewrite: 'AVG_CLOSE_PRICE=80495.7 (1 row)'."""

    if not answer.rows:
        return answer.status
    shown = []
    for row in answer.rows[:max_rows]:
        cells = [f"{k}={v:.6g}" if isinstance(v, float) else f"{k}={v}" for k, v in row.items()]
        shown.append(", ".join(cells[:4]))
    return "; ".join(shown) + f" ({len(answer.rows)} row(s))"


def build_rewrite_message(message: str, history: list[Turn]) -> str:
    lines = ["# Earlier turns"]
    for number, turn in enumerate(history[-MAX_TURNS:], start=1):
        lines.append(f"{number}. Analyst: {turn.question[:300]}")
        lines.append(f"   Understood as: {turn.standalone[:300]}")
        if turn.summary:
            lines.append(f"   Result: {turn.summary[:300]}")
    lines += ["", "# Latest message", message]
    return "\n".join(lines)


def rewrite(message: str, history: list[Turn], llm: LLMClient) -> tuple[dict[str, str], LLMUsage]:
    result = llm.generate_json(
        system_prompt=rewriter_prompt(),
        user_prompt=build_rewrite_message(message, history),
        schema_name="chat_rewrite",
        json_schema=REWRITE_SCHEMA,
        max_output_tokens=200,
    )
    return result.data, result.usage


def chat(
    message: str,
    history: list[Turn] | None = None,
    llm: LLMClient | None = None,
    answer_fn: Callable[[str], Any] | None = None,
) -> ChatReply:
    message = message.strip()
    history = history or []
    language = chat_language(message)
    rule = by_rule(message)
    if rule:
        kind = "smalltalk" if rule == "smalltalk" else "declined"
        logger.info("chat kind=%s by rule", kind)
        return ChatReply(kind, message, reply=REPLIES[language][rule])

    answer_fn = answer_fn or answer_question
    if not history:  # a first question goes to the agent exactly as typed
        return ChatReply("answer", message, answer=answer_fn(message))

    llm = llm or LLMClient()
    decided, usage = rewrite(message, history, llm)
    if decided["kind"] != "data" or not decided["standalone_question"].strip():
        kind = "smalltalk" if decided["kind"] == "smalltalk" else "declined"
        reply = (
            decided["reply"].strip()
            or REPLIES[language]["advice" if kind == "declined" else "smalltalk"]
        )
        logger.info("chat kind=%s by the rewriter", kind)
        return ChatReply(kind, message, reply=reply, usage=usage)
    standalone = decided["standalone_question"].strip()
    logger.info("chat follow-up rewritten: %r -> %r", message[:200], standalone[:200])
    return ChatReply(
        "answer",
        message,
        standalone=standalone if standalone != message else None,
        answer=answer_fn(standalone),
        usage=usage,
    )


def to_turn(reply: ChatReply, summarize_fn: Callable[[Any], str] = summarize) -> dict[str, Any]:
    """What the client keeps and sends back with the next message."""

    if reply.answer is None:
        return {"question": reply.message, "standalone": reply.message, "summary": reply.kind}
    return {
        "question": reply.message,
        "standalone": reply.standalone or reply.message,
        "summary": summarize_fn(reply.answer),
    }
