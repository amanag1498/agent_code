"""LLM provider abstractions."""

from __future__ import annotations

import abc
from typing import TypeVar

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


class ProviderBase(abc.ABC):
    """Base provider for structured LLM calls."""

    @abc.abstractmethod
    def generate_structured(self, prompt: str, response_model: type[TModel]) -> TModel:
        """Generate a structured response for a prompt."""


class LocalProvider(ProviderBase):
    """Placeholder for future local models."""

    def generate_structured(self, prompt: str, response_model: type[TModel]) -> TModel:
        raise NotImplementedError("LocalProvider is not implemented yet.")
