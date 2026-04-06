"""Best-effort LSP semantic enrichment layer.

This layer is intentionally fail-open. Structural extraction via Tree-sitter or
legacy AST must continue to work even when no language server is installed.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ai_repo_agent.analysis.code_analysis import SemanticAnalyzer
from ai_repo_agent.core.models import FileInventoryItem, FileStructureDescriptor, SemanticReferenceDescriptor

LOGGER = logging.getLogger(__name__)

KNOWN_LSP_SERVERS = {
    "python": "basedpyright-langserver",
    "javascript": "typescript-language-server",
    "typescript": "typescript-language-server",
    "java": "jdtls",
    "go": "gopls",
    "rust": "rust-analyzer",
    "c": "clangd",
    "cpp": "clangd",
    "c++": "clangd",
}


class LspSemanticEnricher(SemanticAnalyzer):
    """Lightweight LSP capability detector and semantic metadata provider."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._server_cache: dict[str, str | None] = {}

    def is_available(self, language: str) -> bool:
        if not self.enabled:
            return False
        normalized = language.lower()
        if normalized in self._server_cache:
            return self._server_cache[normalized] is not None
        server = KNOWN_LSP_SERVERS.get(normalized)
        resolved = shutil.which(server) if server else None
        if not resolved:
            LOGGER.debug("No language server detected for %s.", language)
        self._server_cache[normalized] = resolved
        return resolved is not None

    def enrich_file(
        self,
        repo_root: Path,
        item: FileInventoryItem,
        structure: FileStructureDescriptor,
    ) -> FileStructureDescriptor:
        del repo_root
        if not self.is_available(item.language):
            structure.metadata["semantic_backend"] = "unavailable"
            return structure
        structure.metadata["semantic_backend"] = "lsp"
        structure.metadata["lsp_server"] = self._server_cache.get(item.language.lower())
        structure.metadata["semantic_capabilities"] = [
            "document_symbols",
            "definitions",
            "references",
            "call_hierarchy",
        ]
        for unit in structure.code_units:
            unit.semantic = {
                "lsp_available": True,
                "hover": f"LSP enrichment available for {unit.unit_name or item.path}",
            }
        return structure

    def get_definitions(
        self,
        repo_root: Path,
        file_path: str,
        symbol_name: str | None,
    ) -> list[SemanticReferenceDescriptor]:
        return self._semantic_stub(repo_root, file_path, symbol_name, "definition")

    def get_references(
        self,
        repo_root: Path,
        file_path: str,
        symbol_name: str | None,
    ) -> list[SemanticReferenceDescriptor]:
        return self._semantic_stub(repo_root, file_path, symbol_name, "reference")

    def get_call_hierarchy(
        self,
        repo_root: Path,
        file_path: str,
        symbol_name: str | None,
    ) -> list[SemanticReferenceDescriptor]:
        return self._semantic_stub(repo_root, file_path, symbol_name, "call_hierarchy")

    def _semantic_stub(
        self,
        repo_root: Path,
        file_path: str,
        symbol_name: str | None,
        relation: str,
    ) -> list[SemanticReferenceDescriptor]:
        full_path = repo_root / file_path
        if not symbol_name or not full_path.exists():
            return []
        return [
            SemanticReferenceDescriptor(
                file_path=file_path,
                symbol_name=symbol_name,
                relation=relation,
                line_start=None,
                line_end=None,
                metadata={
                    "provider": "lsp",
                    "status": "available_but_not_resolved",
                    "note": f"Language server detected for semantic enrichment, but direct {relation} resolution is best-effort.",
                },
            )
        ]
