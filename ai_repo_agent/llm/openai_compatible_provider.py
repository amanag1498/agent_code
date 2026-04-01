"""OpenAI-compatible structured LLM provider."""

from __future__ import annotations

import json
import logging
import time
from typing import TypeVar

import requests
from pydantic import BaseModel, ValidationError

from ai_repo_agent.llm.provider import ProviderBase

LOGGER = logging.getLogger(__name__)
TModel = TypeVar("TModel", bound=BaseModel)


class OpenAICompatibleProvider(ProviderBase):
    """Provider for OpenAI-compatible chat completions endpoints."""

    provider_name = "openai_compatible"

    def __init__(self, api_key: str, model_name: str, base_url: str, timeout_seconds: int = 60, retry_count: int = 2) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count

    def generate_structured(self, prompt: str, response_model: type[TModel]) -> TModel:
        if not self.api_key:
            raise RuntimeError("LLM API key is not configured.")
        if not self.base_url:
            raise RuntimeError("LLM base URL is not configured for the OpenAI-compatible provider.")

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.retry_count + 1):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=self.timeout_seconds)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f"LLM temporary error: {response.status_code} {response.text[:200]}")
                response.raise_for_status()
                text = self._extract_text(response.json())
                data = json.loads(text)
                return response_model.model_validate(data)
            except (requests.RequestException, ValidationError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                LOGGER.warning("OpenAI-compatible call attempt %s failed: %s", attempt + 1, exc)
                if attempt < self.retry_count:
                    time.sleep(min(2**attempt, 5))
        raise RuntimeError(f"OpenAI-compatible request failed: {last_error}")

    @staticmethod
    def _extract_text(payload: dict) -> str:
        choices = payload.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI-compatible provider returned no choices.")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            content = "".join(parts)
        if not content:
            raise RuntimeError("OpenAI-compatible provider returned empty content.")
        return str(content)
