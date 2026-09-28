"""Unit tests for LLMClient with a fake OpenAI client: no network, no tokens spent."""

from types import SimpleNamespace
from typing import Any

import pytest

from src.common.config import Settings
from src.common.exceptions import ConfigError, LLMError
from src.services.llm import LLMClient

SCHEMA = {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}


class FakeCompletions:
    """Stands in for client.chat.completions; records the request, returns a canned reply."""

    def __init__(
        self, content: str | None, finish_reason: str = "stop", refusal: str | None = None
    ) -> None:
        self.reply = SimpleNamespace(
            model="gpt-4o-mini-2024-07-18",
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(content=content, refusal=refusal),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200),
        )
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        return self.reply


def make_llm(completions: FakeCompletions) -> LLMClient:
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = Settings(_env_file=None, llm_model="gpt-4o-mini")
    return LLMClient(settings=settings, client=fake_client)


def test_asks_for_strict_json_at_temperature_zero_with_a_token_cap() -> None:
    completions = FakeCompletions('{"sql": "SELECT 1"}')

    make_llm(completions).generate_json("rules", "question", "sql_answer", SCHEMA, 300)

    request = completions.requests[0]
    assert request["model"] == "gpt-4o-mini"
    assert request["temperature"] == 0
    assert request["max_tokens"] == 300
    assert request["response_format"]["json_schema"]["strict"] is True
    assert [m["role"] for m in request["messages"]] == ["system", "user"]


def test_returns_parsed_json_and_cost() -> None:
    result = make_llm(FakeCompletions('{"sql": "SELECT 1"}')).generate_json("r", "q", "s", SCHEMA)

    assert result.data == {"sql": "SELECT 1"}
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 200)
    # 1000 × $0.15/1M + 200 × $0.60/1M = $0.00027
    assert result.usage.cost_usd == pytest.approx(0.00027)


def test_cut_off_answer_is_an_error() -> None:
    with pytest.raises(LLMError, match="cut off"):
        make_llm(FakeCompletions('{"sql": "SEL', finish_reason="length")).generate_json(
            "r", "q", "s", SCHEMA
        )


def test_refusal_is_an_error() -> None:
    with pytest.raises(LLMError, match="refused"):
        make_llm(FakeCompletions(None, refusal="I can't help with that")).generate_json(
            "r", "q", "s", SCHEMA
        )


def test_missing_api_key_fails_before_any_call() -> None:
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        LLMClient(settings=Settings(_env_file=None))
