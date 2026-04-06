"""OpenRouter structured LLM provider."""

from __future__ import annotations

from ai_repo_agent.llm.openai_compatible_provider import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    """Provider for OpenRouter's OpenAI-compatible chat completions API."""

    provider_name = "openrouter"
    default_base_url = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str = "",
        timeout_seconds: int = 60,
        retry_count: int = 2,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model_name=model_name,
            base_url=base_url or self.default_base_url,
            timeout_seconds=timeout_seconds,
            retry_count=retry_count,
            extra_headers={
                "HTTP-Referer": "http://127.0.0.1:8000",
                "X-OpenRouter-Title": "AI Repo Analyst",
            },
        )
