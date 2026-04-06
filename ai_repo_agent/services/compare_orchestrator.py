"""Comparison orchestration."""

from __future__ import annotations

from ai_repo_agent.analysis.diff import DiffService
from ai_repo_agent.core.models import CompareResult
from ai_repo_agent.db.repositories import DependencyStore, FileStore, FindingStore, SnapshotStore, SymbolStore


class CompareOrchestrator:
    """Compare snapshots for a repository."""

    def __init__(
        self,
        snapshot_store: SnapshotStore,
        finding_store: FindingStore,
        dependency_store: DependencyStore,
        file_store: FileStore,
        symbol_store: SymbolStore,
    ) -> None:
        self.snapshot_store = snapshot_store
        self.finding_store = finding_store
        self.dependency_store = dependency_store
        self.file_store = file_store
        self.symbol_store = symbol_store
        self.diff_service = DiffService()

    def compare_latest(self, repo_id: int) -> CompareResult | None:
        snapshots = self.snapshot_store.list_for_repo(repo_id)
        if len(snapshots) < 2:
            return None
        current, previous = snapshots[0], snapshots[1]
        changed_files = self.file_store.changed_paths_between_snapshots(previous.id or 0, current.id or 0)
        return self.diff_service.compare(
            repo_id,
            current.id or 0,
            previous.id,
            self.finding_store.list_for_snapshot(current.id or 0),
            self.finding_store.list_for_snapshot(previous.id or 0),
            self.dependency_store.list_for_snapshot(current.id or 0),
            self.dependency_store.list_for_snapshot(previous.id or 0),
            changed_files,
            self.symbol_store.list_for_snapshot(current.id or 0),
            self.symbol_store.list_for_snapshot(previous.id or 0),
        )
