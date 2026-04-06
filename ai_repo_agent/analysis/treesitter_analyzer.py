"""Tree-sitter-backed structural analyzer."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from ai_repo_agent.analysis.code_analysis import CodeStructureAnalyzer
from ai_repo_agent.core.models import CodeUnitDescriptor, FileInventoryItem, FileStructureDescriptor, SymbolDescriptor

LOGGER = logging.getLogger(__name__)


LANGUAGE_ALIASES = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "tsx": "tsx",
    "java": "java",
    "go": "go",
    "rust": "rust",
    "c": "c",
    "cpp": "cpp",
    "c++": "cpp",
}

IMPORT_NODE_TYPES = {
    "import_statement",
    "import_from_statement",
    "import_declaration",
    "use_declaration",
    "preproc_include",
    "package_clause",
}

SYMBOL_NODE_MAP = {
    "class_definition": "class",
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_item": "trait",
    "struct_item": "struct",
    "struct_specifier": "struct",
    "enum_declaration": "enum",
    "enum_item": "enum",
    "function_definition": "function",
    "function_declaration": "function",
    "function_item": "function",
    "method_definition": "method",
    "method_declaration": "method",
    "impl_item": "impl",
    "type_declaration": "type",
    "lexical_declaration": "binding",
    "variable_declaration": "binding",
}


class TreeSitterCodeAnalyzer(CodeStructureAnalyzer):
    """Structural extractor based on Tree-sitter when available."""

    backend_name = "treesitter"
    _cached_language_provider = None
    _provider_checked = False

    def __init__(self, semantic_analyzer=None) -> None:
        super().__init__(semantic_analyzer=semantic_analyzer)
        self._language_provider = self._load_language_provider()

    def supports(self) -> bool:
        return self._language_provider is not None

    def parse_file(self, repo_root: Path, item: FileInventoryItem) -> FileStructureDescriptor:
        if item.is_binary:
            return self._file_only(item)
        text = Path(item.absolute_path).read_text(encoding="utf-8", errors="ignore")
        if self._should_skip(item, text):
            return self._file_only(item, skipped=True)
        parser = self._get_parser(item.language)
        if parser is None:
            return self._fallback_structure(item, text)
        tree = parser.parse(text.encode("utf-8"))
        root = tree.root_node
        imports = self._collect_imports(root, text)
        comments = self._collect_comments(root, text)
        symbols = self._collect_symbols(item, root, text)
        code_units = self._collect_code_units(item, root, text, imports, comments)
        structure = FileStructureDescriptor(
            file_path=item.path,
            language=item.language,
            symbols=symbols or [
                SymbolDescriptor(
                    file_path=item.path,
                    symbol_name=Path(item.path).stem,
                    symbol_kind="module" if item.language == "python" else "file",
                    line_start=1,
                    line_end=item.lines,
                )
            ],
            imports=imports[:24],
            comments=comments[:12],
            code_units=code_units,
            metadata={"backend": self.backend_name, "parser_language": LANGUAGE_ALIASES.get(item.language, item.language)},
        )
        return self.semantic_analyzer.enrich_file(repo_root, item, structure)

    def _get_parser(self, language: str):
        if self._language_provider is None:
            return None
        normalized = LANGUAGE_ALIASES.get(language.lower())
        if not normalized:
            return None
        try:
            return self._language_provider(normalized)
        except Exception as exc:
            LOGGER.debug("Tree-sitter parser unavailable for %s: %s", language, exc)
            return None

    def _collect_symbols(self, item: FileInventoryItem, root, text: str) -> list[SymbolDescriptor]:
        symbols: list[SymbolDescriptor] = [
            SymbolDescriptor(
                file_path=item.path,
                symbol_name=Path(item.path).stem,
                symbol_kind="module" if item.language == "python" else "file",
                line_start=1,
                line_end=item.lines,
            )
        ]
        for node in self._walk(root):
            kind = SYMBOL_NODE_MAP.get(node.type)
            if not kind:
                continue
            name = self._node_name(node, text)
            if not name:
                continue
            symbols.append(
                SymbolDescriptor(
                    file_path=item.path,
                    symbol_name=name,
                    symbol_kind=kind,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                )
            )
        return self._dedupe_symbols(symbols)

    def _collect_code_units(self, item: FileInventoryItem, root, text: str, imports: list[str], comments: list[str]) -> list[CodeUnitDescriptor]:
        units: list[CodeUnitDescriptor] = []
        for node in self._walk(root):
            kind = SYMBOL_NODE_MAP.get(node.type)
            if kind not in {"class", "interface", "trait", "struct", "enum", "function", "method", "impl", "type"}:
                continue
            name = self._node_name(node, text)
            if not name:
                continue
            units.append(
                CodeUnitDescriptor(
                    file_path=item.path,
                    unit_name=name,
                    unit_kind=kind,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    imports=imports[:16],
                    comments=self._leading_comments_for(node, comments),
                    parent_name=self._parent_symbol_name(node, text),
                )
            )
        return self._dedupe_units(units)

    def _collect_imports(self, root, text: str) -> list[str]:
        imports: list[str] = []
        for node in self._walk(root):
            if node.type in IMPORT_NODE_TYPES:
                imports.append(text[node.start_byte : node.end_byte].strip())
        return imports[:24]

    def _collect_comments(self, root, text: str) -> list[str]:
        comments: list[str] = []
        for node in self._walk(root):
            if node.type in {"comment", "line_comment", "block_comment"}:
                comments.append(text[node.start_byte : node.end_byte].strip())
        return comments[:20]

    def _fallback_structure(self, item: FileInventoryItem, text: str) -> FileStructureDescriptor:
        imports = [line.strip() for line in text.splitlines()[:60] if line.strip().startswith(("import ", "from ", "#include", "use "))]
        comments = [line.strip() for line in text.splitlines()[:80] if line.strip().startswith(("#", "//", "/*", "*"))]
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
            imports=imports[:16],
            comments=comments[:10],
            code_units=[],
            metadata={"backend": self.backend_name, "fallback": True},
        )

    @staticmethod
    def _should_skip(item: FileInventoryItem, text: str) -> bool:
        path = item.path.lower()
        skip_terms = ("node_modules/", "dist/", "build/", "target/", ".git/", "vendor/")
        if any(term in path for term in skip_terms):
            return True
        if item.size > 350_000:
            return True
        if len(text.splitlines()) <= 2 and len(text) > 4000:
            return True
        if path.endswith((".min.js", ".min.css", ".lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "cargo.lock")):
            return True
        return False

    @staticmethod
    def _walk(node):
        stack = [node]
        while stack:
            current = stack.pop()
            yield current
            stack.extend(reversed(list(current.children)))

    @staticmethod
    def _node_name(node, text: str) -> str | None:
        for child in node.children:
            if child.type in {"identifier", "type_identifier", "property_identifier", "field_identifier", "name"}:
                value = text[child.start_byte : child.end_byte].strip()
                if value:
                    return value
        named = getattr(node, "child_by_field_name", lambda _: None)("name")
        if named is not None:
            value = text[named.start_byte : named.end_byte].strip()
            if value:
                return value
        if node.end_byte <= node.start_byte:
            return None
        raw_snippet = text[node.start_byte : min(node.end_byte, node.start_byte + 120)]
        if not raw_snippet:
            return None
        lines = [line.strip() for line in raw_snippet.splitlines() if line.strip()]
        if not lines:
            compact = " ".join(raw_snippet.split())
            return compact[:80] or None
        return lines[0][:80] or None

    @staticmethod
    def _parent_symbol_name(node, text: str) -> str | None:
        parent = node.parent
        while parent is not None:
            if parent.type in SYMBOL_NODE_MAP:
                return TreeSitterCodeAnalyzer._node_name(parent, text)
            parent = parent.parent
        return None

    @staticmethod
    def _leading_comments_for(node, comments: list[str]) -> list[str]:
        del node
        return comments[:4]

    @staticmethod
    def _dedupe_symbols(symbols: list[SymbolDescriptor]) -> list[SymbolDescriptor]:
        seen: set[tuple] = set()
        result: list[SymbolDescriptor] = []
        for symbol in symbols:
            key = (symbol.file_path, symbol.symbol_name, symbol.symbol_kind, symbol.line_start, symbol.line_end)
            if key in seen:
                continue
            seen.add(key)
            result.append(symbol)
        return result

    @staticmethod
    def _dedupe_units(units: list[CodeUnitDescriptor]) -> list[CodeUnitDescriptor]:
        seen: set[tuple] = set()
        result: list[CodeUnitDescriptor] = []
        for unit in units:
            key = (unit.file_path, unit.unit_name, unit.unit_kind, unit.line_start, unit.line_end)
            if key in seen:
                continue
            seen.add(key)
            result.append(unit)
        return result

    @staticmethod
    def _file_only(item: FileInventoryItem, skipped: bool = False) -> FileStructureDescriptor:
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
            metadata={"backend": "treesitter", "binary": item.is_binary, "skipped": skipped},
        )

    @staticmethod
    def _load_language_provider():
        if TreeSitterCodeAnalyzer._provider_checked:
            return TreeSitterCodeAnalyzer._cached_language_provider
        candidates = (
            ("tree_sitter_languages", "get_parser"),
            ("tree_sitter_language_pack", "get_parser"),
        )
        for module_name, attr in candidates:
            try:
                module = importlib.import_module(module_name)
                provider = getattr(module, attr, None)
                if provider:
                    TreeSitterCodeAnalyzer._provider_checked = True
                    TreeSitterCodeAnalyzer._cached_language_provider = provider
                    return provider
            except Exception:
                continue
        TreeSitterCodeAnalyzer._provider_checked = True
        TreeSitterCodeAnalyzer._cached_language_provider = None
        LOGGER.warning("Tree-sitter language bindings are not installed. Falling back to legacy AST backend.")
        return None
