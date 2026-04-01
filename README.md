# AI Repo Analyst

AI Repo Analyst is a local-first Python desktop application for repository analysis, git-aware memory, and LLM-assisted review. It scans local folders or repositories, persists snapshots in SQLite, compares future scans against prior state, and uses Gemini as the initial structured analysis engine for findings, change risk, chat, and patch suggestions.

## Features

- PySide6 desktop UI for local repo analysis
- SQLite persistence for repositories, snapshots, files, findings, reviews, and cache
- Git-aware snapshotting with branch, commit, dirty state, changed files, and diff summary
- Heuristic local analysis for language, dependencies, structure, AST symbols, chunked memory, and risk scoring
- Gemini-first structured findings, diff review, repo chat, and patch suggestions
- Watchdog-based change monitoring
- Pre-commit hook runner for local repo checks
- JSON, Markdown, and HTML report export

## Project Layout

```text
ai_repo_agent/
  app/
  ui/
  core/
  db/
  repo/
  analysis/
  memory/
  llm/
  watch/
  reports/
  services/
  tests/
main.py
requirements.txt
README.md
```

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure Gemini:

```bash
export GEMINI_API_KEY="your_api_key"
export GEMINI_MODEL="gemini-1.5-flash"
```

4. Run the app:

```bash
python main.py
```

## Gemini Configuration

- The app reads `GEMINI_API_KEY` from the environment by default.
- The Settings page also supports storing an API key and model name in SQLite-backed app settings.
- Gemini powers findings, chat, patch suggestions, and repo-level summaries. Local inventory, git memory, AST indexing, chunking, persistence, and reporting remain local.

## Sample Flow

1. Open a local folder or drop a repository into the app.
2. AI Repo Analyst inventories files, detects git state, and creates a baseline snapshot.
3. Local analyzers produce repo structure, dependency, symbol, and chunk memory.
4. Gemini receives trimmed evidence only: metadata, symbols, selected code chunks, diffs, and prior context.
5. Structured Gemini findings and reviews are cached and persisted.
6. A later rescan compares snapshots and highlights new, fixed, and regressed risk.
7. Repo chat and patch suggestions reuse locally stored chunk memory.

## Architecture Summary

- `core`: shared models, enums, settings, and logging
- `db`: schema and repository classes for SQLite persistence
- `repo`: repo loading, git service, inventory, fingerprinting
- `analysis`: local heuristics, summaries, AST symbol extraction, chunking, risk scoring, diff support
- `llm`: provider abstraction, Gemini provider, evidence building, prompt building, judge services, chat, and patch workflows
- `watch`: filesystem monitor with debounce
- `reports`: JSON, Markdown, and HTML exports
- `services`: orchestration layer for scan, compare, chat, patch suggestions, and pre-commit
- `ui`: PySide6 widgets and pages

## Phase 2

- semantic embeddings backed by a local vector provider
- improved non-Python AST coverage
- patch application and validation workflows
- repository conversation memory over multiple sessions
- CI-ready headless runner and policy rules
