"""Application context wiring."""

from __future__ import annotations

import os
import sqlite3

from ai_repo_agent.core.logging_config import configure_logging, set_logging_level
from ai_repo_agent.db.database import connect_database
from ai_repo_agent.db.repositories import (
    ChatStore,
    DependencyStore,
    EmbeddingStore,
    FileStore,
    FindingStore,
    PatchSuggestionStore,
    RepositoryStore,
    ReviewStore,
    ScanRunStore,
    SettingsStore,
    SnapshotStore,
    SymbolStore,
)


class AppContext:
    """Service locator for the web app."""

    def __init__(self, database_path: str) -> None:
        configure_logging()
        self.connection: sqlite3.Connection = connect_database(database_path)
        self.repositories = RepositoryStore(self.connection)
        self.snapshots = SnapshotStore(self.connection)
        self.files = FileStore(self.connection)
        self.dependencies = DependencyStore(self.connection)
        self.symbols = SymbolStore(self.connection)
        self.embeddings = EmbeddingStore(self.connection)
        self.findings = FindingStore(self.connection)
        self.scan_runs = ScanRunStore(self.connection)
        self.reviews = ReviewStore(self.connection)
        self.chat = ChatStore(self.connection)
        self.patches = PatchSuggestionStore(self.connection)
        self.settings = SettingsStore(self.connection)
        loaded = self.settings.load()
        loaded.llm_provider = os.getenv("LLM_PROVIDER", loaded.llm_provider)
        if not loaded.llm_api_key:
            loaded.llm_api_key = os.getenv("LLM_API_KEY", os.getenv("GEMINI_API_KEY", ""))
        loaded.llm_model = os.getenv("LLM_MODEL", os.getenv("GEMINI_MODEL", loaded.llm_model))
        loaded.llm_base_url = os.getenv("LLM_BASE_URL", loaded.llm_base_url)
        set_logging_level(loaded.logging_level)
        self.settings.save(loaded)
