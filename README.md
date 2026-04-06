# AI Repo Analyst

AI Repo Analyst is a local-first repository review workstation for codebase analysis, snapshot comparison, grounded LLM findings, repo chat, and patch generation.

It runs as a local FastAPI web app, stores persistent state in SQLite, keeps repository ingestion and analysis local, and uses a pluggable LLM layer for review workflows.

## What It Does

AI Repo Analyst is designed for iterative repository review, not one-shot scanning.

Core workflow:
1. Select a local folder or repository.
2. Create a snapshot of files, structure, symbols, chunks, dependencies, and git-aware change state.
3. Run structured LLM review over retrieved evidence.
4. Compare the current snapshot against prior snapshots.
5. Inspect findings, drift, repo memory, chat answers, and patch suggestions in the web UI.

## Current Feature Set

### Repository Scanning

- Scan a local folder or git repository from the browser UI
- Create and persist repository snapshots in SQLite
- Capture:
  - branch
  - commit hash
  - dirty state
  - changed file count
  - diff summary
  - file inventory
  - dependency inventory
  - symbol inventory
  - chunk memory

### Analysis Engine

- Pluggable analyzer abstraction instead of direct AST-only parsing
- Analyzer backends:
  - `hybrid`
  - `treesitter`
  - `legacy_ast`
- Tree-sitter structural parsing
- Optional LSP semantic enrichment
- Multi-language structural support designed around:
  - Python
  - JavaScript / TypeScript
  - Java
  - Go
  - Rust
  - C / C++
- Structural outputs normalized into:
  - symbols
  - code units
  - imports/includes
  - comments/docstrings
  - annotations/decorators
  - source spans
  - semantic references where available

### Memory And Retrieval

- Structural chunking based on code units instead of blind line windows
- Local deterministic embeddings for stored chunks
- Retrieval that combines:
  - vector similarity
  - changed-file priority
  - path heuristics
  - symbol relevance
- SQLite persistence for:
  - `embedding_chunks`
  - `embedding_vectors`

### Findings

- Structured LLM-generated findings
- Finding families for grouping related issues across rescans
- Confidence and evidence-quality metadata
- Framework tags where detected
- Focused analysis passes for:
  - auth
  - validation
  - dependency
  - secrets/config
- Framework-aware passes for:
  - FastAPI
  - Django
  - Express
  - React / Next
  - Spring

### Compare And Drift

- Snapshot-to-snapshot compare
- Finding delta tracking:
  - new
  - fixed
  - unchanged
  - regressed
- Changed files and dependency deltas
- Symbol change summaries
- Architectural drift summaries
- Trend metadata across recent snapshots:
  - findings count
  - high-risk count
  - changed files count
  - review coverage
  - patch coverage
  - reintroduced findings count

### Repo Chat

- Repo Q&A grounded in retrieved code evidence
- Retrieval over stored chunk memory
- File citations in answers
- Uses the same local snapshot/memory layer as the findings pipeline

### Patch Lab

- Patch suggestions for selected findings
- Related code and symbol context
- Retrieval-backed patch grounding
- Patch alternatives
- Diff preview support
- Validation metadata
- Current validation is strongest for Python syntax and fails open for other languages

### Reliability And Runtime

- Background scan jobs
- Live progress updates in the UI
- Bounded scan worker pool
- Scan cancellation support
- Snapshot retention trimming
- Persistent logs in file + in-app log view

### Reporting And Tooling

- Export reports as:
  - JSON
  - Markdown
  - HTML
- Pre-commit hook installer

## UI

The web app is a local review workspace built with:

- FastAPI
- Jinja2
- plain JavaScript
- plain CSS

Main views:

- Overview
- Repo Tree
- Findings
- Compare
- Memory
- Repo Chat
- Patch Lab
- Logs
- Settings

Notable UI capabilities:

- live scan activity and progress
- repository graph
- compare insights
- code inspection from compare deltas
- patch validation and diff preview panels
- snapshot/memory browsing

## Architecture

Top-level structure:

```text
ai_repo_agent/
  analysis/     # analyzers, chunking, embeddings, diffing, scoring, summaries
  app/          # runtime bootstrap
  core/         # enums, models, logging
  db/           # SQLite schema and repositories
  llm/          # providers, prompts, evidence, structured workflows
  memory/       # snapshot memory helpers
  repo/         # repo loading, file inventory, git state
  reports/      # report generators
  services/     # scan, compare, chat, patch, app context orchestration
  tests/        # regression and analyzer tests
  watch/        # file watch support
  web/          # FastAPI server + HTML/CSS/JS UI
docs/
main.py
requirements.txt
```

### Important Modules

- [/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/web/server.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/web/server.py)
  - FastAPI app, endpoints, scan-job orchestration, folder picker
- [/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/services/scan_orchestrator.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/services/scan_orchestrator.py)
  - scan flow, persistence, finding generation, compare, review pipeline
- [/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/code_analysis.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/code_analysis.py)
  - analyzer abstraction layer
- [/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/treesitter_analyzer.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/treesitter_analyzer.py)
  - Tree-sitter structural parsing
- [/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/lsp_semantic.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/lsp_semantic.py)
  - optional semantic enrichment
- [/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/embeddings.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/embeddings.py)
  - local embeddings and retrieval scoring
- [/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/llm/workflows.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/llm/workflows.py)
  - findings, repo chat, and patch workflows
- [/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/diff.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/analysis/diff.py)
  - findings compare, semantic summaries, drift metadata

## LLM Providers

The LLM layer is pluggable.

Current provider modes:

- `gemini`
- `openrouter`
- `openai_compatible`
- `local`
- `none`

### OpenRouter

```bash
export LLM_PROVIDER="openrouter"
export OPENROUTER_API_KEY="YOUR_OPENROUTER_KEY"
export OPENROUTER_MODEL="openai/gpt-4o-mini"
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
```

### Gemini

```bash
export LLM_PROVIDER="gemini"
export LLM_API_KEY="YOUR_GEMINI_KEY"
export LLM_MODEL="gemini-2.5-flash"
```

### OpenAI-Compatible

```bash
export LLM_PROVIDER="openai_compatible"
export LLM_API_KEY="YOUR_KEY"
export LLM_MODEL="YOUR_MODEL"
export LLM_BASE_URL="https://your-endpoint.example.com/v1"
```

### Local-Only Runtime

```bash
export LLM_PROVIDER="none"
```

This still builds snapshots, memory, compare data, and UI state, but LLM-driven findings/chat/patch flows will be skipped or return explanatory messages.

## Running The Project

From the repo root:

```bash
cd /Users/amanagarwal/Desktop/AGENT_AI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then configure your provider and run:

```bash
python main.py
```

Open:

```text
http://127.0.0.1:8000
```

## Optional Runtime Configuration

### Analyzer

```bash
export ANALYZER_BACKEND="hybrid"   # hybrid | treesitter | legacy_ast
export LSP_ENABLED="true"          # true | false
```

### LLM

```bash
export LLM_PROVIDER="openrouter"
export OPENROUTER_API_KEY="YOUR_KEY"
export OPENROUTER_MODEL="openai/gpt-4o-mini"
```

### Notes

- settings are also persisted in SQLite and editable from the UI
- environment variables are useful for overrides and fresh sessions

## Persistence

The app stores state in `ai_repo_analyst.db`.

Key stored entities:

- repositories
- repo snapshots
- files and file versions
- dependencies
- symbols
- findings
- finding deltas
- embedding chunks
- embedding vectors
- LLM reviews
- LLM cache
- scan runs
- chat sessions/messages
- patch suggestions
- app settings

## Phase 2 Status

### Implemented

- analyzer abstraction layer
- Tree-sitter structural parsing
- optional LSP enrichment
- local embeddings and vector-backed retrieval
- structural chunking based on code units
- finding families and evidence-quality metadata
- framework-aware specialized finding passes
- architectural drift summaries
- trend metadata across snapshots
- code inspection for compare deltas
- patch alternatives, validation metadata, and diff preview
- bounded scan workers, cancellation, and retention trimming

### Still Worth Improving

- deeper true LSP resolution and call-path semantics
- stronger patch validation for non-Python languages
- more accurate semantic finding-family clustering
- richer inline diff/code workstation behavior
- stronger partial-failure recovery around long LLM calls

## Tests And Verification

Current regression coverage includes:

- analyzer symbol extraction
- structural chunking
- scan pipeline snapshot/memory persistence
- retrieval relevance
- LSP fail-open behavior
- compare trend history
- snapshot retention trimming
- patch validation helpers

Primary test file:

- [/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/tests/test_analyzer_pipeline.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/tests/test_analyzer_pipeline.py)

## Migration Notes

Analyzer migration notes:

- [docs/analyzer_migration.md](docs/analyzer_migration.md)

Phase 2 increment planning notes:

- [docs/phase2_increment_plan.md](docs/phase2_increment_plan.md)

## Practical Notes

- Folder picker support is native and OS-dependent. Manual path entry is always supported.
- The app is local-first, but LLM-backed features depend on your configured provider.
- Logs are visible both in the UI and in the local log file.
- Older snapshots can be trimmed from the Settings workflow or API.
