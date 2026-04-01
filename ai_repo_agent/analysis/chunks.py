"""Chunking for local repo memory and retrieval."""

from __future__ import annotations

import ast
from pathlib import Path
import re

from ai_repo_agent.core.models import ChunkDescriptor, FileInventoryItem


class ChunkBuilder:
    """Create bounded text chunks for retrieval and future embeddings."""

    def build(self, files: list[FileInventoryItem], max_lines: int = 80) -> list[ChunkDescriptor]:
        chunks: list[ChunkDescriptor] = []
        for item in files:
            if item.is_binary or item.size > 250_000:
                continue
            path = Path(item.absolute_path)
            text = path.read_text(encoding="utf-8", errors="ignore")
            lines = text.splitlines()
            if not lines:
                continue
            structural = self._structural_chunks(item, text, lines, max_lines)
            if structural:
                chunks.extend(structural)
                continue
            for start in range(0, len(lines), max_lines):
                end = min(start + max_lines, len(lines))
                chunk_text = "\n".join(lines[start:end])
                chunks.append(
                    ChunkDescriptor(
                        file_path=item.path,
                        chunk_text=chunk_text,
                        metadata=self._metadata(item, start + 1, end, "window", None, self._extract_imports(item.language, text)),
                    )
                )
        return chunks

    def _structural_chunks(
        self,
        item: FileInventoryItem,
        text: str,
        lines: list[str],
        max_lines: int,
    ) -> list[ChunkDescriptor]:
        if item.language == "python":
            return self._python_chunks(item, text, lines, max_lines)
        if item.language in {"javascript", "typescript"}:
            return self._js_ts_chunks(item, text, lines, max_lines)
        return []

    def _python_chunks(self, item: FileInventoryItem, text: str, lines: list[str], max_lines: int) -> list[ChunkDescriptor]:
        try:
            tree = ast.parse(text)
        except Exception:
            return []
        imports = self._extract_imports(item.language, text)
        chunks: list[ChunkDescriptor] = []
        prelude_end = self._python_prelude_end(tree)
        if prelude_end:
            chunks.append(
                ChunkDescriptor(
                    file_path=item.path,
                    chunk_text="\n".join(lines[:prelude_end]),
                    metadata=self._metadata(item, 1, prelude_end, "module_prelude", Path(item.path).stem, imports),
                )
            )
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", None)
                if not start or not end:
                    continue
                chunk_lines = end - start + 1
                if chunk_lines <= max_lines * 2:
                    chunks.append(
                        ChunkDescriptor(
                            file_path=item.path,
                            chunk_text="\n".join(lines[start - 1 : end]),
                            metadata=self._metadata(
                                item,
                                start,
                                end,
                                "class" if isinstance(node, ast.ClassDef) else "function",
                                getattr(node, "name", None),
                                imports,
                            ),
                        )
                    )
                else:
                    chunks.extend(self._split_large_block(item, lines, start, end, getattr(node, "name", None), imports, max_lines))
        return chunks

    def _js_ts_chunks(self, item: FileInventoryItem, text: str, lines: list[str], max_lines: int) -> list[ChunkDescriptor]:
        imports = self._extract_imports(item.language, text)
        chunks: list[ChunkDescriptor] = []
        pattern = re.compile(r"^\s*(export\s+)?(async\s+function|function|class|const|let|var)\s+([A-Za-z0-9_]+)", re.MULTILINE)
        matches = list(pattern.finditer(text))
        for index, match in enumerate(matches):
            start = text[: match.start()].count("\n") + 1
            next_start = text[: matches[index + 1].start()].count("\n") + 1 if index + 1 < len(matches) else len(lines) + 1
            end = min(next_start - 1, start + (max_lines * 2) - 1)
            if end < start:
                continue
            symbol_name = match.group(3)
            symbol_kind = "class" if "class" in match.group(2) else "function"
            chunks.append(
                ChunkDescriptor(
                    file_path=item.path,
                    chunk_text="\n".join(lines[start - 1 : end]),
                    metadata=self._metadata(item, start, end, symbol_kind, symbol_name, imports),
                )
            )
        return chunks

    def _split_large_block(
        self,
        item: FileInventoryItem,
        lines: list[str],
        start: int,
        end: int,
        symbol_name: str | None,
        imports: list[str],
        max_lines: int,
    ) -> list[ChunkDescriptor]:
        chunks: list[ChunkDescriptor] = []
        for chunk_start in range(start, end + 1, max_lines):
            chunk_end = min(chunk_start + max_lines - 1, end)
            chunks.append(
                ChunkDescriptor(
                    file_path=item.path,
                    chunk_text="\n".join(lines[chunk_start - 1 : chunk_end]),
                    metadata=self._metadata(item, chunk_start, chunk_end, "block_fragment", symbol_name, imports),
                )
            )
        return chunks

    @staticmethod
    def _python_prelude_end(tree: ast.AST) -> int:
        max_end = 0
        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                max_end = max(max_end, getattr(node, "end_lineno", getattr(node, "lineno", 0)))
            else:
                break
        return max_end

    @staticmethod
    def _extract_imports(language: str, text: str) -> list[str]:
        imports: list[str] = []
        if language == "python":
            for line in text.splitlines()[:120]:
                stripped = line.strip()
                if stripped.startswith("import "):
                    imports.append(stripped.replace("import ", "", 1).split(" as ")[0].strip())
                elif stripped.startswith("from "):
                    imports.append(stripped.split(" import ")[0].replace("from ", "", 1).strip())
        elif language in {"javascript", "typescript"}:
            pattern = re.compile(r"(?:import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))")
            for match in pattern.finditer(text[:6000]):
                imports.append(match.group(1) or match.group(2) or "")
        return [item for item in imports if item][:20]

    @staticmethod
    def _metadata(
        item: FileInventoryItem,
        start: int,
        end: int,
        chunk_kind: str,
        symbol_name: str | None,
        imports: list[str],
    ) -> dict:
        return {
            "line_start": start,
            "line_end": end,
            "language": item.language,
            "file_sha256": item.sha256,
            "file_size": item.size,
            "lines": item.lines,
            "chunk_kind": chunk_kind,
            "symbol_name": symbol_name,
            "imports": imports[:12],
        }
