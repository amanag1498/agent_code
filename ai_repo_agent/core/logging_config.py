"""Logging helpers."""

from __future__ import annotations

from collections import deque
import logging
from pathlib import Path
from threading import Lock


class InMemoryLogHandler(logging.Handler):
    """Thread-safe in-memory log buffer for the local UI."""

    def __init__(self, max_entries: int = 500) -> None:
        super().__init__()
        self._entries: deque[str] = deque(maxlen=max_entries)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        with self._lock:
            self._entries.append(message)

    def get_entries(self) -> list[str]:
        with self._lock:
            return list(self._entries)


_MEMORY_HANDLER: InMemoryLogHandler | None = None


def get_memory_log_handler() -> InMemoryLogHandler:
    """Return the shared in-memory log handler."""
    global _MEMORY_HANDLER
    if _MEMORY_HANDLER is None:
        _MEMORY_HANDLER = InMemoryLogHandler()
    return _MEMORY_HANDLER


def configure_logging(level: str = "INFO") -> None:
    """Configure application logging."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    if not any(isinstance(handler, logging.StreamHandler) and not isinstance(handler, InMemoryLogHandler) for handler in root_logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    memory_handler = get_memory_log_handler()
    memory_handler.setFormatter(formatter)
    if memory_handler not in root_logger.handlers:
        root_logger.addHandler(memory_handler)

    log_path = Path("ai_repo_analyst.log")
    if not any(isinstance(handler, logging.FileHandler) for handler in root_logger.handlers):
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def set_logging_level(level: str) -> None:
    """Update the root logging level at runtime."""
    logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))
