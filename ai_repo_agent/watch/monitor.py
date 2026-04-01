"""Filesystem watch service."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

LOGGER = logging.getLogger(__name__)


class DebouncedEventHandler(FileSystemEventHandler):
    """Debounce filesystem events before calling back."""

    def __init__(self, callback, debounce_seconds: float = 1.5) -> None:
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self._timer: threading.Timer | None = None

    def on_any_event(self, event) -> None:  # type: ignore[override]
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.debounce_seconds, self.callback)
        self._timer.start()


class RepoWatchService:
    """Watch a repository path and signal changes."""

    def __init__(self) -> None:
        self.observer: Observer | None = None

    def start(self, path: Path, callback) -> None:
        self.stop()
        self.observer = Observer()
        self.observer.schedule(DebouncedEventHandler(callback), str(path), recursive=True)
        self.observer.start()
        LOGGER.info("Started watcher for %s", path)

    def stop(self) -> None:
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=2)
            self.observer = None
