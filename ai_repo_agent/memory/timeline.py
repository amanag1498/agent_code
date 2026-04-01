"""Snapshot timeline helpers."""

from __future__ import annotations

from ai_repo_agent.core.models import RepoSnapshotRecord
from ai_repo_agent.db.repositories import SnapshotStore


class MemoryTimelineService:
    """Browse stored snapshots."""

    def __init__(self, snapshot_store: SnapshotStore) -> None:
        self.snapshot_store = snapshot_store

    def list_snapshots(self, repo_id: int) -> list[RepoSnapshotRecord]:
        return self.snapshot_store.list_for_repo(repo_id)
