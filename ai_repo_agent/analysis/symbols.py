"""Symbol extraction facade backed by the configured code analyzer."""

from __future__ import annotations

from pathlib import Path

from ai_repo_agent.analysis.code_analysis import CodeStructureAnalyzer
from ai_repo_agent.core.models import FileInventoryItem, SymbolDescriptor


class SymbolIndexer:
    """Extract normalized symbols for local memory and context retrieval."""

    def __init__(self, analyzer: CodeStructureAnalyzer) -> None:
        self.analyzer = analyzer

    def index(self, repo_root: Path, files: list[FileInventoryItem]) -> list[SymbolDescriptor]:
        return self.analyzer.extract_symbols(repo_root, files)
