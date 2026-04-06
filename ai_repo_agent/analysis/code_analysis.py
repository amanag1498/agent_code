"""Analyzer abstractions and backend selection for code structure extraction.

Migration note:
- Legacy AST parsing previously powered Python symbol extraction and chunking.
- The scan pipeline now depends on `CodeStructureAnalyzer` instead of directly
  importing `ast`-based indexers/builders.
- Snapshots, memory persistence, diffing, findings, patch generation, and UI
  contracts remain unchanged; only the producer for symbols/chunks/context has
  been swapped behind this abstraction.
- The legacy AST implementation remains available behind `legacy_ast`.
"""

from __future__ import annotations

import abc
import logging
from pathlib import Path

from ai_repo_agent.core.models import (
    AppSettings,
    ChunkDescriptor,
    CodeUnitDescriptor,
    FileInventoryItem,
    FileStructureDescriptor,
    SemanticReferenceDescriptor,
    SymbolDescriptor,
)

LOGGER = logging.getLogger(__name__)


class SemanticAnalyzer(abc.ABC):
    """Optional semantic enrichment layer."""

    @abc.abstractmethod
    def is_available(self, language: str) -> bool:
        """Return whether semantic enrichment is available for a language."""

    @abc.abstractmethod
    def enrich_file(
        self,
        repo_root: Path,
        item: FileInventoryItem,
        structure: FileStructureDescriptor,
    ) -> FileStructureDescriptor:
        """Enrich a structural result with semantic references."""

    @abc.abstractmethod
    def get_definitions(
        self,
        repo_root: Path,
        file_path: str,
        symbol_name: str | None,
    ) -> list[SemanticReferenceDescriptor]:
        """Resolve definitions for a symbol when supported."""

    @abc.abstractmethod
    def get_references(
        self,
        repo_root: Path,
        file_path: str,
        symbol_name: str | None,
    ) -> list[SemanticReferenceDescriptor]:
        """Resolve references for a symbol when supported."""

    @abc.abstractmethod
    def get_call_hierarchy(
        self,
        repo_root: Path,
        file_path: str,
        symbol_name: str | None,
    ) -> list[SemanticReferenceDescriptor]:
        """Resolve call hierarchy for a symbol when supported."""


class NullSemanticAnalyzer(SemanticAnalyzer):
    """No-op semantic enrichment."""

    def is_available(self, language: str) -> bool:
        return False

    def enrich_file(
        self,
        repo_root: Path,
        item: FileInventoryItem,
        structure: FileStructureDescriptor,
    ) -> FileStructureDescriptor:
        del repo_root, item
        return structure

    def get_definitions(self, repo_root: Path, file_path: str, symbol_name: str | None) -> list[SemanticReferenceDescriptor]:
        del repo_root, file_path, symbol_name
        return []

    def get_references(self, repo_root: Path, file_path: str, symbol_name: str | None) -> list[SemanticReferenceDescriptor]:
        del repo_root, file_path, symbol_name
        return []

    def get_call_hierarchy(self, repo_root: Path, file_path: str, symbol_name: str | None) -> list[SemanticReferenceDescriptor]:
        del repo_root, file_path, symbol_name
        return []


class CodeStructureAnalyzer(abc.ABC):
    """Structural code analysis interface used by the rest of the pipeline."""

    backend_name: str = "unknown"

    def __init__(self, semantic_analyzer: SemanticAnalyzer | None = None) -> None:
        self.semantic_analyzer = semantic_analyzer or NullSemanticAnalyzer()

    @abc.abstractmethod
    def supports(self) -> bool:
        """Return whether the backend can run in the current environment."""

    @abc.abstractmethod
    def parse_file(self, repo_root: Path, item: FileInventoryItem) -> FileStructureDescriptor:
        """Parse a file into normalized structural descriptors."""

    def extract_symbols(self, repo_root: Path, files: list[FileInventoryItem]) -> list[SymbolDescriptor]:
        symbols: list[SymbolDescriptor] = []
        for item in files[:1000]:
            structure = self.parse_file(repo_root, item)
            symbols.extend(structure.symbols)
        return symbols

    def extract_code_units(self, repo_root: Path, files: list[FileInventoryItem]) -> list[CodeUnitDescriptor]:
        units: list[CodeUnitDescriptor] = []
        for item in files:
            structure = self.parse_file(repo_root, item)
            units.extend(structure.code_units)
        return units

    def extract_chunks(self, repo_root: Path, files: list[FileInventoryItem], max_lines: int = 80) -> list[ChunkDescriptor]:
        chunks: list[ChunkDescriptor] = []
        for item in files:
            structure = self.parse_file(repo_root, item)
            chunks.extend(self._structure_to_chunks(item, structure, max_lines))
        return chunks

    def get_patch_context(
        self,
        repo_root: Path,
        item: FileInventoryItem,
        line_start: int | None,
        line_end: int | None,
    ) -> dict:
        structure = self.parse_file(repo_root, item)
        focus_line = line_start or 1
        parent = next(
            (
                unit
                for unit in structure.code_units
                if unit.line_start <= focus_line <= unit.line_end
            ),
            None,
        )
        neighbors = [
            unit
            for unit in structure.code_units
            if parent and unit.file_path == parent.file_path and unit is not parent
        ]
        symbol_name = parent.unit_name if parent else None
        return {
            "imports": structure.imports[:16],
            "comments": structure.comments[:8],
            "parent_code_unit": self._unit_to_payload(parent),
            "neighbor_units": [self._unit_to_payload(unit) for unit in neighbors[:4]],
            "definitions": [ref.metadata | {"file_path": ref.file_path, "line_start": ref.line_start, "line_end": ref.line_end} for ref in self.semantic_analyzer.get_definitions(repo_root, item.path, symbol_name)[:6]],
            "references": [ref.metadata | {"file_path": ref.file_path, "line_start": ref.line_start, "line_end": ref.line_end} for ref in self.semantic_analyzer.get_references(repo_root, item.path, symbol_name)[:8]],
            "call_hierarchy": [ref.metadata | {"file_path": ref.file_path, "line_start": ref.line_start, "line_end": ref.line_end} for ref in self.semantic_analyzer.get_call_hierarchy(repo_root, item.path, symbol_name)[:8]],
        }

    def _structure_to_chunks(
        self,
        item: FileInventoryItem,
        structure: FileStructureDescriptor,
        max_lines: int,
    ) -> list[ChunkDescriptor]:
        if item.is_binary or item.size > 250_000:
            return []
        text = Path(item.absolute_path).read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        if not lines:
            return []
        chunks: list[ChunkDescriptor] = []
        if structure.code_units:
            for unit in structure.code_units:
                start = max(1, unit.line_start)
                end = min(len(lines), unit.line_end)
                if end < start:
                    continue
                if end - start + 1 <= max_lines * 2:
                    chunks.append(
                        ChunkDescriptor(
                            file_path=item.path,
                            chunk_text="\n".join(lines[start - 1 : end]),
                            metadata={
                                "line_start": start,
                                "line_end": end,
                                "language": item.language,
                                "file_sha256": item.sha256,
                                "file_size": item.size,
                                "lines": item.lines,
                                "chunk_kind": unit.unit_kind,
                                "symbol_name": unit.unit_name,
                                "imports": unit.imports[:12],
                                "comments": unit.comments[:6],
                                "parent_name": unit.parent_name,
                                "semantic": unit.semantic,
                            },
                        )
                    )
                else:
                    for chunk_start in range(start, end + 1, max_lines):
                        chunk_end = min(chunk_start + max_lines - 1, end)
                        chunks.append(
                            ChunkDescriptor(
                                file_path=item.path,
                                chunk_text="\n".join(lines[chunk_start - 1 : chunk_end]),
                                metadata={
                                    "line_start": chunk_start,
                                    "line_end": chunk_end,
                                    "language": item.language,
                                    "file_sha256": item.sha256,
                                    "file_size": item.size,
                                    "lines": item.lines,
                                    "chunk_kind": "block_fragment",
                                    "symbol_name": unit.unit_name,
                                    "imports": unit.imports[:12],
                                    "comments": unit.comments[:6],
                                    "parent_name": unit.parent_name,
                                    "semantic": unit.semantic,
                                },
                            )
                        )
        else:
            imports = structure.imports[:12]
            for start in range(0, len(lines), max_lines):
                end = min(start + max_lines, len(lines))
                chunks.append(
                    ChunkDescriptor(
                        file_path=item.path,
                        chunk_text="\n".join(lines[start:end]),
                        metadata={
                            "line_start": start + 1,
                            "line_end": end,
                            "language": item.language,
                            "file_sha256": item.sha256,
                            "file_size": item.size,
                            "lines": item.lines,
                            "chunk_kind": "window",
                            "symbol_name": None,
                            "imports": imports,
                            "comments": structure.comments[:6],
                            "parent_name": None,
                            "semantic": {},
                        },
                    )
                )
        return chunks

    @staticmethod
    def _unit_to_payload(unit: CodeUnitDescriptor | None) -> dict | None:
        if unit is None:
            return None
        return {
            "file_path": unit.file_path,
            "unit_name": unit.unit_name,
            "unit_kind": unit.unit_kind,
            "line_start": unit.line_start,
            "line_end": unit.line_end,
            "imports": unit.imports[:12],
            "comments": unit.comments[:4],
            "parent_name": unit.parent_name,
            "semantic": unit.semantic,
        }


def create_code_analyzer(settings: AppSettings) -> CodeStructureAnalyzer:
    """Create the configured analysis backend with safe fallback."""
    from ai_repo_agent.analysis.legacy_ast_analyzer import LegacyAstCodeAnalyzer
    from ai_repo_agent.analysis.lsp_semantic import LspSemanticEnricher
    from ai_repo_agent.analysis.treesitter_analyzer import TreeSitterCodeAnalyzer

    semantic = LspSemanticEnricher(enabled=settings.lsp_enabled)
    requested = settings.analyzer_backend.strip().lower()
    treesitter = TreeSitterCodeAnalyzer(semantic_analyzer=semantic)
    legacy = LegacyAstCodeAnalyzer(semantic_analyzer=semantic)

    if requested == "legacy_ast":
        LOGGER.info("Using legacy AST analyzer backend.")
        return legacy
    if requested == "treesitter":
        if treesitter.supports():
            LOGGER.info("Using Tree-sitter analyzer backend.")
            return treesitter
        LOGGER.warning("Tree-sitter backend requested but unavailable; falling back to legacy AST.")
        return legacy
    if requested == "hybrid":
        if treesitter.supports():
            LOGGER.info("Using hybrid analyzer backend (Tree-sitter + optional LSP).")
            return treesitter
        LOGGER.warning("Hybrid backend unavailable because Tree-sitter is missing; falling back to legacy AST.")
        return legacy
    LOGGER.warning("Unknown analyzer backend '%s'; falling back to legacy AST.", settings.analyzer_backend)
    return legacy
