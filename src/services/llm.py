"""Call the language model and get back JSON of a fixed shape, plus what the call cost.

Only OpenAI is implemented (LLM_PROVIDER=openai). Callers never touch the OpenAI SDK directly,
so switching provider later means changing this file only.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import openai

from src.common.config import Settings, get_settings
from src.common.exceptions import ConfigError, LLMError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMUsage:
    """Tokens one call used and what they cost (at the prices in Settings)."""

    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class LLMResult:
    """The parsed JSON the model returned, and the bill."""

    data: dict[str, Any]
    usage: LLMUsage
    model: str
    seconds: float


class LLMClient:
    """Low-temperature, JSON-only calls with a hard cap on output tokens."""

    def __init__(self, settings: Settings | None = None, client: Any = None) -> None:
        self.settings = settings or get_settings()
        if self.settings.llm_provider != "openai":
            raise ConfigError("Only LLM_PROVIDER=openai is implemented")
        api_key = self.settings.openai_api_key.get_secret_value()
        if client is None and not api_key:
            raise ConfigError("Missing OPENAI_API_KEY in .env")
        # The SDK retries timeouts and 429/5xx twice by itself; 30 s caps a stuck call.
        self._client = client or openai.OpenAI(api_key=api_key, timeout=30.0, max_retries=2)

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        json_schema: dict[str, Any],
        max_output_tokens: int = 500,
    ) -> LLMResult:
        """Ask the model for one JSON object that matches `json_schema` exactly.

        Structured Outputs (strict JSON schema) makes the API guarantee the shape, so there is
        no fragile parsing of ```sql fences like in code/first_loop.py.
        """

        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self.settings.llm_model,
                temperature=0,
                max_tokens=max_output_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
                },
            )
        except openai.OpenAIError as err:
            raise LLMError(f"OpenAI call failed: {err}") from err
        seconds = time.perf_counter() - started

        choice = response.choices[0]
        if choice.message.refusal:
            raise LLMError(f"The model refused: {choice.message.refusal}")
        if choice.finish_reason == "length":
            raise LLMError(f"The answer was cut off at max_output_tokens={max_output_tokens}")
        try:
            data = json.loads(choice.message.content)
        except (TypeError, json.JSONDecodeError) as err:
            content = choice.message.content
            raise LLMError(f"The model did not return JSON: {content!r:.200}") from err

        usage = self._usage(response.usage.prompt_tokens, response.usage.completion_tokens)
        logger.info(
            "LLM %s: %d in + %d out tokens, $%.5f, %.1fs",
            response.model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cost_usd,
            seconds,
        )
        return LLMResult(data=data, usage=usage, model=response.model, seconds=seconds)

    def _usage(self, input_tokens: int, output_tokens: int) -> LLMUsage:
        cost = (
            input_tokens * self.settings.llm_input_usd_per_1m
            + output_tokens * self.settings.llm_output_usd_per_1m
        ) / 1_000_000
        return LLMUsage(input_tokens, output_tokens, cost)
