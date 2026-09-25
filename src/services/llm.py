"""Provide a small abstraction over OpenAI and Anthropic clients.

TODO: Implement provider selection, retries, timeouts, and structured output.
"""

from src.common.config import Settings, get_settings


class LLMClient:
    """Declare the low-temperature text generation interface.

    TODO: Initialize only the selected provider and redact secrets from logs.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.temperature = 0.0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate text from provider-neutral prompt inputs.

        TODO: Call OpenAI or Anthropic using self.settings.llm_provider.
        """

        _ = (system_prompt, user_prompt)
        raise NotImplementedError("TODO: implement the external LLM API call")
