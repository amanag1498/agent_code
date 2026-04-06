"""Best-effort LSP semantic enrichment layer.

This layer is intentionally fail-open. Structural extraction via Tree-sitter or
legacy AST must continue to work even when no language server is installed.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from ai_repo_agent.analysis.code_analysis import SemanticAnalyzer
from ai_repo_agent.core.models import FileInventoryItem, FileStructureDescriptor, SemanticReferenceDescriptor

LOGGER = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")

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
        self._workspace_index_cache: dict[str, dict[str, list[SemanticReferenceDescriptor]]] = {}

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
            definitions = self.get_definitions(repo_root, item.path, unit.unit_name)
            references = self.get_references(repo_root, item.path, unit.unit_name)
            calls = self.get_call_hierarchy(repo_root, item.path, unit.unit_name)
            unit.semantic = {
                "lsp_available": True,
                "hover": f"{item.language} {unit.unit_kind} {unit.unit_name or item.path}",
                "type_info": unit.unit_kind,
                "definitions": [ref.metadata | {"file_path": ref.file_path, "line_start": ref.line_start, "line_end": ref.line_end} for ref in definitions[:4]],
                "references": [ref.metadata | {"file_path": ref.file_path, "line_start": ref.line_start, "line_end": ref.line_end} for ref in references[:6]],
                "call_hierarchy": [ref.metadata | {"file_path": ref.file_path, "line_start": ref.line_start, "line_end": ref.line_end} for ref in calls[:6]],
            }
            structure.semantic_references.extend(definitions[:2] + references[:3] + calls[:3])
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
        index = self._workspace_index(repo_root)
        if relation == "definition":
            return index.get(f"def:{symbol_name}", [])[:8]
        if relation == "reference":
            return index.get(f"ref:{symbol_name}", [])[:12]
        if relation == "call_hierarchy":
            return index.get(f"call:{symbol_name}", [])[:12]
        return []

    def _workspace_index(self, repo_root: Path) -> dict[str, list[SemanticReferenceDescriptor]]:
        key = str(repo_root.resolve())
        cached = self._workspace_index_cache.get(key)
        if cached is not None:
            return cached
        index: dict[str, list[SemanticReferenceDescriptor]] = {}
        for path in repo_root.rglob("*"):
            if not path.is_file():
                continue
            rel_path = str(path.relative_to(repo_root))
            if any(part in {".git", "node_modules", "dist", "build", "target", "vendor", "__pycache__"} for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                definition = self._definition_name(stripped)
                if definition:
                    index.setdefault(f"def:{definition}", []).append(
                        SemanticReferenceDescriptor(
                            file_path=rel_path,
                            symbol_name=definition,
                            relation="definition",
                            line_start=line_number,
                            line_end=line_number,
                            metadata={"provider": "lsp", "status": "best_effort", "source": "workspace_index"},
                        )
                    )
                for token in TOKEN_RE.findall(stripped):
                    if definition and token == definition:
                        continue
                    index.setdefault(f"ref:{token}", []).append(
                        SemanticReferenceDescriptor(
                            file_path=rel_path,
                            symbol_name=token,
                            relation="reference",
                            line_start=line_number,
                            line_end=line_number,
                            metadata={"provider": "lsp", "status": "best_effort", "source": "workspace_index"},
                        )
                    )
                for call_name in re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", stripped):
                    index.setdefault(f"call:{call_name}", []).append(
                        SemanticReferenceDescriptor(
                            file_path=rel_path,
                            symbol_name=call_name,
                            relation="call_hierarchy",
                            line_start=line_number,
                            line_end=line_number,
                            metadata={"provider": "lsp", "status": "best_effort", "source": "workspace_index"},
                        )
                    )
        self._workspace_index_cache[key] = index
        return index

    @staticmethod
    def _definition_name(line: str) -> str | None:
        patterns = [
            r"^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            r"^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            r"^\s*function\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            r"^\s*(?:public|private|protected|static|\s)*\s*(?:class|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*func\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*fn\s+([A-Za-z_][A-Za-z0-9_]*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
        return None
