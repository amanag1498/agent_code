"""Chunking facade backed by the configured code analyzer."""

from __future__ import annotations

from pathlib import Path

from ai_repo_agent.analysis.code_analysis import CodeStructureAnalyzer
from ai_repo_agent.core.models import ChunkDescriptor, FileInventoryItem


class ChunkBuilder:
    """Create bounded text chunks for retrieval using structural code units."""

    def __init__(self, analyzer: CodeStructureAnalyzer) -> None:
        self.analyzer = analyzer

    def build(self, repo_root: Path, files: list[FileInventoryItem], max_lines: int = 80) -> list[ChunkDescriptor]:
        return self.analyzer.extract_chunks(repo_root, files, max_lines=max_lines)
