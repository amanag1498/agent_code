"""Patch suggestion orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

from ai_repo_agent.db.repositories import EmbeddingStore, FindingStore, PatchSuggestionStore, ReviewStore
from ai_repo_agent.llm.gemini_provider import GeminiProvider
from ai_repo_agent.llm.workflows import PatchSuggestionLLMService

LOGGER = logging.getLogger(__name__)


class PatchOrchestrator:
    """Generate and persist patch suggestions for findings."""

    def __init__(
        self,
        finding_store: FindingStore,
        embedding_store: EmbeddingStore,
        review_store: ReviewStore,
        patch_store: PatchSuggestionStore,
        provider: GeminiProvider | None,
    ) -> None:
        self.finding_store = finding_store
        self.embedding_store = embedding_store
        self.review_store = review_store
        self.patch_store = patch_store
        self.provider = provider

    def suggest(self, repo_root: str, snapshot_id: int, finding_id: int) -> str:
        if not self.provider:
            return "Gemini is not configured. Add an API key in Settings to generate patch suggestions."
        findings = self.finding_store.list_for_snapshot(snapshot_id)
        finding = next((item for item in findings if item.id == finding_id), None)
        if not finding:
            return "Finding not found for patch generation."
        chunks = self.embedding_store.list_for_snapshot(snapshot_id)
        related = [chunk for chunk in chunks if chunk.file_path == finding.file_path][:6]
        LOGGER.info(
            "Starting patch suggestion generation: snapshot_id=%s finding_id=%s related_chunks=%s",
            snapshot_id,
            finding_id,
            len(related),
        )
        service = PatchSuggestionLLMService(self.provider, self.review_store, self.patch_store)
        patch = service.suggest(Path(repo_root), finding, related, snapshot_id)
        LOGGER.info("Patch suggestion generated for finding_id=%s", finding_id)
        return patch.suggested_diff
