"""Provider factory for configured LLM backends."""

from __future__ import annotations

from ai_repo_agent.core.models import AppSettings
from ai_repo_agent.llm.gemini_provider import GeminiProvider
from ai_repo_agent.llm.openai_compatible_provider import OpenAICompatibleProvider
from ai_repo_agent.llm.openrouter_provider import OpenRouterProvider
from ai_repo_agent.llm.provider import LocalProvider, ProviderBase


def create_provider(settings: AppSettings) -> ProviderBase | None:
    """Create the configured LLM provider, or return None if unusable."""
    provider_name = settings.llm_provider.strip().lower()
    if provider_name == "none":
        return None
    if provider_name == "gemini":
        if not settings.llm_api_key:
            return None
        return GeminiProvider(
            api_key=settings.llm_api_key,
            model_name=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            retry_count=settings.llm_retry_count,
        )
    if provider_name in {"openai", "openai_compatible"}:
        if not settings.llm_api_key or not settings.llm_base_url:
            return None
        return OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            model_name=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            retry_count=settings.llm_retry_count,
        )
    if provider_name == "openrouter":
        if not settings.llm_api_key:
            return None
        return OpenRouterProvider(
            api_key=settings.llm_api_key,
            model_name=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            retry_count=settings.llm_retry_count,
        )
    if provider_name == "local":
        return LocalProvider()
    raise RuntimeError(f"Unsupported LLM provider '{settings.llm_provider}'.")
