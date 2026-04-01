"""Gemini provider implementation."""

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


class GeminiProvider(ProviderBase):
    """Gemini provider using the public REST API."""

    def __init__(self, api_key: str, model_name: str, timeout_seconds: int = 20, retry_count: int = 2) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count

    def generate_structured(self, prompt: str, response_model: type[TModel]) -> TModel:
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured.")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
            f"?key={self.api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        last_error: Exception | None = None
        for attempt in range(self.retry_count + 1):
            try:
                response = requests.post(url, json=payload, timeout=self.timeout_seconds)
                if response.status_code == 404:
                    raise RuntimeError(
                        f"Gemini model '{self.model_name}' was not found for generateContent. "
                        "Check the configured model name."
                    )
                if response.status_code in {429, 500, 503}:
                    raise RuntimeError(f"Gemini temporary error: {response.status_code} {response.text[:200]}")
                response.raise_for_status()
                text = self._extract_text(response.json())
                data = json.loads(text)
                return response_model.model_validate(data)
            except (requests.RequestException, ValidationError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                LOGGER.warning("Gemini call attempt %s failed: %s", attempt + 1, exc)
                if attempt < self.retry_count:
                    time.sleep(min(2**attempt, 5))
        raise RuntimeError(f"Gemini request failed: {last_error}")

    @staticmethod
    def _extract_text(payload: dict) -> str:
        candidates = payload.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidates.")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise RuntimeError("Gemini returned empty content.")
        return parts[0].get("text", "{}")
