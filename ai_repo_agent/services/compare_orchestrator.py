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
        compare = self.diff_service.compare(
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
        compare.trend_metadata.update(self._trend_metadata(repo_id, snapshots[:8]))
        compare.trend_metadata["reintroduced_findings"] = self._reintroduced_count(snapshots, current.id or 0)
        return compare

    def _trend_metadata(self, repo_id: int, snapshots) -> dict:
        history = []
        previous_snapshot = None
        for snapshot in reversed(snapshots):
            findings = self.finding_store.list_for_snapshot(snapshot.id or 0)
            compare_changed_files = (
                self.file_store.changed_paths_between_snapshots(previous_snapshot.id or 0, snapshot.id or 0)
                if previous_snapshot and previous_snapshot.id and snapshot.id
                else []
            )
            history.append(
                {
                    "snapshot_id": snapshot.id,
                    "created_at": snapshot.created_at,
                    "findings_count": len(findings),
                    "high_risk_count": sum(1 for finding in findings if finding.severity in {"critical", "high"}),
                    "changed_files_count": len(compare_changed_files),
                    "review_coverage": self._review_coverage(snapshot.id or 0, len(findings)),
                    "patch_coverage": self._patch_coverage(repo_id, snapshot.id or 0, len(findings)),
                }
            )
            previous_snapshot = snapshot
        return {"history": history}

    def _reintroduced_count(self, snapshots, current_snapshot_id: int) -> int:
        if len(snapshots) < 3:
            return 0
        current_findings = self.finding_store.list_for_snapshot(current_snapshot_id)
        current_families = {finding.family_id for finding in current_findings if finding.family_id}
        if not current_families:
            return 0
        prior_families: set[str] = set()
        for snapshot in snapshots[2:]:
            prior_families.update(
                finding.family_id
                for finding in self.finding_store.list_for_snapshot(snapshot.id or 0)
                if finding.family_id
            )
        return len(current_families & prior_families)

    def _review_coverage(self, snapshot_id: int, findings_count: int) -> float:
        if findings_count <= 0:
            return 0.0
        reviews = self.symbol_store.connection.execute(
            "SELECT COUNT(*) AS count FROM llm_reviews WHERE snapshot_id = ? AND finding_id IS NOT NULL",
            (snapshot_id,),
        ).fetchone()
        return round((int(reviews["count"]) / findings_count), 3) if reviews else 0.0

    def _patch_coverage(self, repo_id: int, snapshot_id: int, findings_count: int) -> float:
        del repo_id
        if findings_count <= 0:
            return 0.0
        patches = self.symbol_store.connection.execute(
            "SELECT COUNT(*) AS count FROM patch_suggestions WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return round((int(patches["count"]) / findings_count), 3) if patches else 0.0
