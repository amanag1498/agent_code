"""CLI runner for pre-commit usage."""

from __future__ import annotations

import sys

from ai_repo_agent.services.app_context import AppContext
from ai_repo_agent.services.scan_orchestrator import ScanOrchestrator


def main() -> int:
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "."
    context = AppContext("ai_repo_analyst.db")
    settings = context.settings.load()
    orchestrator = ScanOrchestrator(
        context.repositories,
        context.snapshots,
        context.files,
        context.dependencies,
        context.symbols,
        context.embeddings,
        context.findings,
        context.reviews,
        context.scan_runs,
        settings,
    )
    result = orchestrator.scan(repo_path)
    print(result.snapshot.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
