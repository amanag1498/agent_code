"""Legacy AST-backed analyzer preserved for backwards compatibility."""

from __future__ import annotations

import ast
from pathlib import Path

from ai_repo_agent.analysis.code_analysis import CodeStructureAnalyzer
from ai_repo_agent.core.models import CodeUnitDescriptor, FileInventoryItem, FileStructureDescriptor, SymbolDescriptor


class LegacyAstCodeAnalyzer(CodeStructureAnalyzer):
    """Python AST-backed analyzer used as a compatibility fallback."""

    backend_name = "legacy_ast"

    def supports(self) -> bool:
        return True

    def parse_file(self, repo_root: Path, item: FileInventoryItem) -> FileStructureDescriptor:
        if item.is_binary:
            return self._file_only(item)
        source = Path(item.absolute_path).read_text(encoding="utf-8", errors="ignore")
        if item.language != "python":
            return self._non_python_structure(item, source)
        try:
            tree = ast.parse(source)
        except Exception:
            return self._non_python_structure(item, source)
        imports = self._extract_imports(source)
        comments = self._extract_comments(source)
        symbols = [
            SymbolDescriptor(
                file_path=item.path,
                symbol_name=Path(item.path).stem,
                symbol_kind="module",
                line_start=1,
                line_end=item.lines,
            )
        ]
        code_units: list[CodeUnitDescriptor] = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
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
                code_units.append(
                    CodeUnitDescriptor(
                        file_path=item.path,
                        unit_name=node.name,
                        unit_kind="class",
                        line_start=getattr(node, "lineno", 1),
                        line_end=getattr(node, "end_lineno", item.lines),
                        imports=imports,
                        comments=comments,
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
                code_units.append(
                    CodeUnitDescriptor(
                        file_path=item.path,
                        unit_name=node.name,
                        unit_kind="function",
                        line_start=getattr(node, "lineno", 1),
                        line_end=getattr(node, "end_lineno", item.lines),
                        imports=imports,
                        comments=comments,
                    )
                )
        structure = FileStructureDescriptor(
            file_path=item.path,
            language=item.language,
            symbols=symbols,
            imports=imports,
            comments=comments,
            code_units=code_units,
            metadata={"backend": self.backend_name},
        )
        return self.semantic_analyzer.enrich_file(repo_root, item, structure)

    def _file_only(self, item: FileInventoryItem) -> FileStructureDescriptor:
        return FileStructureDescriptor(
            file_path=item.path,
            language=item.language,
            symbols=[
                SymbolDescriptor(
                    file_path=item.path,
                    symbol_name=Path(item.path).name,
                    symbol_kind="file",
                    line_start=1,
                    line_end=item.lines,
                )
            ],
            imports=[],
            comments=[],
            code_units=[],
            metadata={"backend": self.backend_name, "binary": True},
        )

    def _non_python_structure(self, item: FileInventoryItem, source: str) -> FileStructureDescriptor:
        imports = self._extract_imports(source)
        comments = self._extract_comments(source)
        return FileStructureDescriptor(
            file_path=item.path,
            language=item.language,
            symbols=[
                SymbolDescriptor(
                    file_path=item.path,
                    symbol_name=Path(item.path).name,
                    symbol_kind="file",
                    line_start=1,
                    line_end=item.lines,
                )
            ],
            imports=imports,
            comments=comments,
            code_units=[],
            metadata={"backend": self.backend_name},
        )

    @staticmethod
    def _extract_imports(source: str) -> list[str]:
        imports: list[str] = []
        for line in source.splitlines()[:120]:
            stripped = line.strip()
            if stripped.startswith("import "):
                imports.append(stripped.replace("import ", "", 1).split(" as ")[0].strip())
            elif stripped.startswith("from "):
                imports.append(stripped.split(" import ")[0].replace("from ", "", 1).strip())
        return imports[:20]

    @staticmethod
    def _extract_comments(source: str) -> list[str]:
        comments = [line.strip() for line in source.splitlines()[:80] if line.strip().startswith("#")]
        return comments[:10]
