# AI Repo Analyst

AI Repo Analyst is a local-first Python web application for repository analysis, git-aware memory, diff comparison, structured LLM-assisted review, repo chat, and patch suggestions. It runs a local web server, stores all persistent state in SQLite, and keeps core repo scanning local.

## Current Capabilities

- Scan a local folder or git repository from a browser UI
- Store repositories, snapshots, files, file versions, dependencies, symbols, chunks, findings, reviews, chat history, patches, and logs in SQLite
- Compare the current snapshot against prior snapshots
- Detect changed files and changed dependencies between snapshots
- Build local repo memory with:
  - file inventory
  - language/framework detection
  - dependency detection
  - Python AST symbol extraction
  - chunked code memory
- Use a pluggable LLM provider for:
  - structured finding generation
  - repo-level risk summary
  - repo chat
  - patch suggestions
- Export JSON, Markdown, and HTML reports
- Install a pre-commit hook runner
- View live logs in the web UI

## Web App Layout

The browser UI includes:

- Overview
- Repo Tree
- Findings
- Compare
- Memory
- Repo Chat
- Patch Lab
- Logs
- Settings

## Project Layout

```text
ai_repo_agent/
  analysis/
  app/
  core/
  db/
  llm/
  memory/
  repo/
  reports/
  services/
  tests/
  watch/
  web/
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

3. Configure an LLM provider:

```bash
export LLM_PROVIDER="gemini"
export LLM_API_KEY="your_api_key"
export LLM_MODEL="gemini-2.5-flash"
```

For an OpenAI-compatible endpoint:

```bash
export LLM_PROVIDER="openai_compatible"
export LLM_API_KEY="your_api_key"
export LLM_MODEL="your-model-name"
export LLM_BASE_URL="https://your-endpoint.example.com/v1"
```

4. Run the local web app:

```bash
python main.py
```

5. Open your browser at:

```text
http://127.0.0.1:8000
```

You can override host and port with:

```bash
export AI_REPO_ANALYST_HOST=127.0.0.1
export AI_REPO_ANALYST_PORT=8000
python main.py
```

## Notes

- Core repo ingestion, git inspection, SQLite persistence, symbol extraction, chunking, reporting, and snapshot comparison are local.
- The configured LLM provider powers structured findings, repo chat, patch suggestions, and repo summaries.
- Gemini works out of the box as the default provider, but the service layer also supports OpenAI-compatible endpoints.
- If no LLM provider is configured, the app still builds local memory and stores snapshots, but LLM features will be skipped or return an explanatory message.
- Settings are persisted in `ai_repo_analyst.db`.
- Logs are written to `ai_repo_analyst.log` and are also visible in the web UI.

## Main Components

- `analysis`: local heuristics, AST symbol extraction, chunking, diff logic, summary and risk scoring
- `db`: SQLite schema and repository helpers
- `llm`: provider factory, grounded prompt building, evidence packaging, and structured workflows
- `repo`: repo loading, git service, inventory, fingerprinting
- `reports`: JSON, Markdown, and HTML exports
- `services`: orchestrators for scan, compare, chat, patching, pre-commit, and app context
- `web`: FastAPI server, browser templates, and static assets

## Phase 2 Status

Implemented:

- Python AST symbol extraction
- chunked repo memory persistence
- repo chat backed by stored local chunks
- patch suggestion flow
- pre-commit hook installer

Still to deepen:

- semantic embeddings and retrieval scoring
- richer multi-language AST coverage
- non-blocking background workers for long LLM requests
- patch application and validation workflows
- deeper architecture graph views
