# Analyzer Migration Notes

## Audit Summary

The original analysis pipeline depended on Python `ast` in two direct places:

- `ai_repo_agent/analysis/symbols.py`
  - Python-only symbol extraction for modules, classes, and functions
- `ai_repo_agent/analysis/chunks.py`
  - Python AST-driven function/class chunking
  - heuristic JS/TS chunking via regex

Those AST-derived results flowed into:

- snapshot symbol persistence
- chunk persistence for retrieval/memory
- LLM evidence packaging
- findings generation focus
- patch suggestion context
- UI memory views

## What Changed

The pipeline now depends on `CodeStructureAnalyzer` instead of directly calling
AST helpers.

New layers:

- `CodeStructureAnalyzer`
  - structural parsing contract for symbols, imports, code units, chunks, and patch context
- `TreeSitterCodeAnalyzer`
  - primary structural backend when Tree-sitter language bindings are available
- `LspSemanticEnricher`
  - optional semantic enrichment layer that fails open when no language server is installed
- `LegacyAstCodeAnalyzer`
  - compatibility backend preserved behind `legacy_ast`

## What Remains Unchanged

- SQLite schema for symbols/chunks/findings/snapshots
- scan orchestration contract
- compare result contract
- risk scoring flow
- findings generation flow
- patch suggestion API/UI behavior
- web UI payloads and endpoint shapes

## Backward Compatibility

Config:

- `ANALYZER_BACKEND=legacy_ast|treesitter|hybrid`
- `LSP_ENABLED=true|false`

Behavior:

- `hybrid` tries Tree-sitter first and enriches with LSP when possible
- if Tree-sitter bindings are unavailable, the app falls back to `legacy_ast`
- the legacy AST path is kept for stability and marked as deprecated by design
