"""Symbol extraction with Python AST support."""

from __future__ import annotations

import ast
from pathlib import Path

from ai_repo_agent.core.models import FileInventoryItem, SymbolDescriptor


class SymbolIndexer:
    """Extract lightweight symbols for local memory and context retrieval."""

    def index(self, files: list[FileInventoryItem]) -> list[SymbolDescriptor]:
        symbols: list[SymbolDescriptor] = []
        for item in files[:1000]:
            symbols.extend(self._index_file(item))
        return symbols

    def _index_file(self, item: FileInventoryItem) -> list[SymbolDescriptor]:
        if item.language != "python" or item.is_binary:
            return [
                SymbolDescriptor(
                    file_path=item.path,
                    symbol_name=Path(item.path).name,
                    symbol_kind="file",
                    line_start=1,
                    line_end=item.lines,
                )
            ]
        try:
            source = Path(item.absolute_path).read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except Exception:
            return [
                SymbolDescriptor(
                    file_path=item.path,
                    symbol_name=Path(item.path).name,
                    symbol_kind="file",
                    line_start=1,
                    line_end=item.lines,
                )
            ]
        symbols: list[SymbolDescriptor] = [
            SymbolDescriptor(
                file_path=item.path,
                symbol_name=Path(item.path).stem,
                symbol_kind="module",
                line_start=1,
                line_end=item.lines,
            )
        ]
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append(
                    SymbolDescriptor(
                        file_path=item.path,
                        symbol_name=node.name,
                        symbol_kind="class",
                        line_start=getattr(node, "lineno", None),
                        line_end=getattr(node, "end_lineno", None),
                    )
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    SymbolDescriptor(
                        file_path=item.path,
                        symbol_name=node.name,
                        symbol_kind="function",
                        line_start=getattr(node, "lineno", None),
                        line_end=getattr(node, "end_lineno", None),
                    )
                )
        return symbols
