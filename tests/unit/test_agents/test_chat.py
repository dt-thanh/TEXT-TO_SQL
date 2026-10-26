"""Quick SQL as a conversation: rules, follow-up rewriting, out-of-scope (no tokens, no network)."""

from typing import Any

import pytest

from src.agents.chat import Turn, by_rule, chat, summarize, to_turn
from src.agents.text_to_sql import Answer
from src.services.llm import LLMResult, LLMUsage


def answer(question: str) -> Answer:
    return Answer(
        question=question, sql="SELECT 1", explanation="", rows=[{"AVG_CLOSE": 80495.68}],
        truncated=False, usage=LLMUsage(2000, 100, 0.0017), llm_seconds=1.0, sql_seconds=0.3,
    )  # fmt: skip


class Rewriter:
    def __init__(self, data: dict[str, str]) -> None:
        self.data, self.prompts = data, []

    def generate_json(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> LLMResult:
        self.prompts.append(user_prompt)
        return LLMResult(self.data, LLMUsage(400, 30, 0.0002), "gpt-4.1-mini", 0.4)


class NoLLM:
    def generate_json(self, *args: Any, **kwargs: Any) -> LLMResult:  # pragma: no cover
        raise AssertionError("no LLM call expected")


HISTORY = [Turn("BTC đóng cửa trung bình tháng 9/2026?", "BTC đóng cửa trung bình tháng 9/2026?",
                "AVG_CLOSE=80495.7 (1 row(s))")]  # fmt: skip


@pytest.mark.parametrize(
    "message, rule",
    [
        ("chào bạn", "smalltalk"), ("Hello!", "smalltalk"), ("Bạn làm được gì?", "smalltalk"),
        ("có nên mua BTC không?", "advice"), ("Should I buy ETH now?", "advice"),
        ("Giá BTC tháng sau sẽ tăng không?", "advice"), ("dự đoán giá ETH", "advice"),
        ("BTC đóng cửa trung bình tháng 9?", None), ("ETH volatility last 30 days", None),
    ],
)  # fmt: skip
def test_greetings_and_advice_are_recognized_by_rules(message: str, rule: str | None) -> None:
    assert by_rule(message) == rule


def test_advice_is_declined_without_any_llm_call_or_sql() -> None:
    ran: list[str] = []

    reply = chat("Có nên mua SOL không?", HISTORY, llm=NoLLM(), answer_fn=ran.append)

    assert reply.kind == "declined" and "lời khuyên đầu tư" in reply.reply
    assert ran == [] and reply.usage.cost_usd == 0


def test_a_first_question_goes_to_the_agent_exactly_as_typed() -> None:
    asked: list[str] = []

    reply = chat("BTC average close in September 2026?", [], llm=NoLLM(),
                 answer_fn=lambda q: asked.append(q) or answer(q))  # fmt: skip

    assert asked == ["BTC average close in September 2026?"] and reply.standalone is None


def test_a_follow_up_is_rewritten_with_the_earlier_turns_and_shown() -> None:
    eth = "ETH đóng cửa trung bình tháng 9/2026?"
    rewriter = Rewriter({"kind": "data", "reply": "", "standalone_question": eth})
    asked: list[str] = []

    reply = chat("còn ETH thì sao?", HISTORY, llm=rewriter,
                 answer_fn=lambda q: asked.append(q) or answer(q))  # fmt: skip

    assert asked == ["ETH đóng cửa trung bình tháng 9/2026?"]
    assert reply.kind == "answer" and reply.standalone == "ETH đóng cửa trung bình tháng 9/2026?"
    assert "Understood as: BTC đóng cửa" in rewriter.prompts[0]
    assert "AVG_CLOSE=80495.7" in rewriter.prompts[0]  # the result, for "compared with that?"


def test_an_out_of_scope_follow_up_gets_a_reply_and_no_sql() -> None:
    no_news = "FinSight has no news. Try: BTC volatility last week?"
    rewriter = Rewriter({"kind": "out_of_scope", "standalone_question": "", "reply": no_news})
    ran: list[str] = []

    reply = chat("why did it fall, any news?", HISTORY, llm=rewriter, answer_fn=ran.append)

    assert reply.kind == "declined" and reply.reply.startswith("FinSight has no news")
    assert ran == []


def test_only_the_last_turns_are_sent_and_the_turn_to_keep_is_compact() -> None:
    rewriter = Rewriter({"kind": "data", "reply": "", "standalone_question": "X?"})
    history = [Turn(f"q{i}", f"standalone {i}", "") for i in range(10)]

    reply = chat("and then?", history, llm=rewriter, answer_fn=answer)

    assert "standalone 9" in rewriter.prompts[0] and "standalone 5" not in rewriter.prompts[0]
    assert to_turn(reply) == {"question": "and then?", "standalone": "X?",
                              "summary": summarize(reply.answer)}  # fmt: skip
