"""Patch suggestion orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

from ai_repo_agent.analysis.code_analysis import create_code_analyzer
from ai_repo_agent.core.models import AppSettings, FileInventoryItem
from ai_repo_agent.db.repositories import EmbeddingStore, FindingStore, PatchSuggestionStore, ReviewStore, SymbolStore
from ai_repo_agent.llm.provider import ProviderBase
from ai_repo_agent.llm.workflows import PatchSuggestionLLMService

LOGGER = logging.getLogger(__name__)


class PatchOrchestrator:
    """Generate and persist patch suggestions for findings."""

    def __init__(
        self,
        finding_store: FindingStore,
        embedding_store: EmbeddingStore,
        symbol_store: SymbolStore,
        review_store: ReviewStore,
        patch_store: PatchSuggestionStore,
        provider: ProviderBase | None,
        settings: AppSettings,
    ) -> None:
        self.finding_store = finding_store
        self.embedding_store = embedding_store
        self.symbol_store = symbol_store
        self.review_store = review_store
        self.patch_store = patch_store
        self.provider = provider
        self.analyzer = create_code_analyzer(settings)

    def suggest(self, repo_root: str, snapshot_id: int, finding_id: int) -> str:
        if not self.provider:
            return "No LLM provider is configured. Update the LLM settings to generate patch suggestions."
        findings = self.finding_store.list_for_snapshot(snapshot_id)
        finding = next((item for item in findings if item.id == finding_id), None)
        if not finding:
            return "Finding not found for patch generation."
        chunks = self.embedding_store.list_for_snapshot(snapshot_id)
        symbols = self.symbol_store.list_for_snapshot(snapshot_id)
        related = [chunk for chunk in chunks if self._is_related_chunk(chunk.file_path, finding.file_path)]
        related.sort(
            key=lambda chunk: (
                0 if self._contains_line(chunk.metadata_json, finding.line_start) else 1,
                0 if chunk.file_path == finding.file_path else 1,
                abs(self._line_start(chunk.metadata_json) - (finding.line_start or 1)),
            )
        )
        related = related[:8]
        related_symbols = [
            symbol for symbol in symbols if self._is_related_symbol(symbol.file_path, finding.file_path, finding.line_start)
        ][:24]
        patch_context = self._build_patch_context(repo_root, finding)
        LOGGER.info(
            "Starting patch suggestion generation: snapshot_id=%s finding_id=%s related_chunks=%s",
            snapshot_id,
            finding_id,
            len(related),
        )
        service = PatchSuggestionLLMService(self.provider, self.review_store, self.patch_store)
        patch = service.suggest(Path(repo_root), finding, related, related_symbols, patch_context, snapshot_id)
        LOGGER.info("Patch suggestion generated for finding_id=%s", finding_id)
        return patch.suggested_diff

    def _build_patch_context(self, repo_root: str, finding) -> dict:
        if not finding.file_path:
            return {}
        full_path = Path(repo_root) / finding.file_path
        if not full_path.exists():
            return {}
        source = full_path.read_text(encoding="utf-8", errors="ignore")
        lines = source.splitlines()
        item = self.analyzer.get_patch_context(
            Path(repo_root),
            FileInventoryItem(
                path=finding.file_path,
                absolute_path=str(full_path),
                size=full_path.stat().st_size,
                sha256="",
                language=self._infer_language(finding.file_path),
                is_binary=False,
                lines=len(lines),
            ),
            finding.line_start,
            finding.line_end,
        )
        start = max((finding.line_start or 1) - 8, 1)
        end = min((finding.line_end or finding.line_start or 1) + 8, len(lines))
        item["surrounding_lines"] = {
            "line_start": start,
            "line_end": end,
            "snippet": "\n".join(lines[start - 1 : end]),
        }
        return item

    @staticmethod
    def _is_related_chunk(chunk_path: str, finding_path: str | None) -> bool:
        if not finding_path:
            return False
        if chunk_path == finding_path:
            return True
        chunk_parts = Path(chunk_path).parts
        finding_parts = Path(finding_path).parts
        if chunk_parts[:-1] == finding_parts[:-1]:
            return True
        return len(chunk_parts) > 1 and len(finding_parts) > 1 and chunk_parts[0] == finding_parts[0]

    @staticmethod
    def _is_related_symbol(symbol_path: str, finding_path: str | None, line_start: int | None) -> bool:
        if not finding_path:
            return False
        if symbol_path == finding_path:
            return True
        if Path(symbol_path).parent == Path(finding_path).parent:
            return True
        return False

    @staticmethod
    def _contains_line(metadata_json: str, line: int | None) -> bool:
        if not line:
            return False
        start = PatchOrchestrator._line_start(metadata_json)
        end = PatchOrchestrator._line_end(metadata_json)
        return start <= line <= end

    @staticmethod
    def _line_start(metadata_json: str) -> int:
        import json

        try:
            return int(json.loads(metadata_json).get("line_start") or 0)
        except Exception:
            return 0

    @staticmethod
    def _line_end(metadata_json: str) -> int:
        import json

        try:
            return int(json.loads(metadata_json).get("line_end") or 0)
        except Exception:
            return 0

    @staticmethod
    def _infer_language(file_path: str) -> str:
        suffix = Path(file_path).suffix.lower()
        return {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".c": "c",
            ".cc": "cpp",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }.get(suffix, "text")
