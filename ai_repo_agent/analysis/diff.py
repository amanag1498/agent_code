"""Snapshot comparison helpers."""

from __future__ import annotations

from ai_repo_agent.core.enums import DeltaType
from ai_repo_agent.core.models import CompareResult, DependencyRecord, FindingDeltaRecord, FindingRecord


class DiffService:
    """Compare snapshots using finding fingerprints and dependency names."""

    def compare(
        self,
        repo_id: int,
        current_snapshot_id: int,
        previous_snapshot_id: int | None,
        current_findings: list[FindingRecord],
        previous_findings: list[FindingRecord],
        current_dependencies: list[DependencyRecord],
        previous_dependencies: list[DependencyRecord],
        changed_files: list[str],
    ) -> CompareResult:
        previous_by_fingerprint = {finding.fingerprint: finding for finding in previous_findings}
        current_by_fingerprint = {finding.fingerprint: finding for finding in current_findings}
        deltas: list[FindingDeltaRecord] = []
        for fingerprint, current in current_by_fingerprint.items():
            previous = previous_by_fingerprint.get(fingerprint)
            delta = DeltaType.UNCHANGED if previous else DeltaType.NEW
            deltas.append(
                FindingDeltaRecord(
                    id=None,
                    repo_id=repo_id,
                    previous_finding_id=previous.id if previous else None,
                    current_finding_id=current.id,
                    delta_type=delta.value,
                    summary=f"{current.title} classified as {delta.value}",
                )
            )
        for fingerprint, previous in previous_by_fingerprint.items():
            if fingerprint not in current_by_fingerprint:
                deltas.append(
                    FindingDeltaRecord(
                        id=None,
                        repo_id=repo_id,
                        previous_finding_id=previous.id,
                        current_finding_id=None,
                        delta_type=DeltaType.FIXED.value,
                        summary=f"{previous.title} no longer present",
                    )
                )
        current_dep_set = {f"{dep.ecosystem}:{dep.name}:{dep.version}" for dep in current_dependencies}
        previous_dep_set = {f"{dep.ecosystem}:{dep.name}:{dep.version}" for dep in previous_dependencies}
        changed_dependencies = sorted(current_dep_set.symmetric_difference(previous_dep_set))
        summary = (
            f"New findings: {sum(1 for d in deltas if d.delta_type == DeltaType.NEW.value)}, "
            f"fixed findings: {sum(1 for d in deltas if d.delta_type == DeltaType.FIXED.value)}, "
            f"changed files: {len(changed_files)}, changed dependencies: {len(changed_dependencies)}"
        )
        risk_delta = float(sum(1 for d in deltas if d.delta_type == DeltaType.NEW.value) - sum(1 for d in deltas if d.delta_type == DeltaType.FIXED.value))
        return CompareResult(
            previous_snapshot_id=previous_snapshot_id,
            current_snapshot_id=current_snapshot_id,
            deltas=deltas,
            changed_files=changed_files,
            changed_dependencies=changed_dependencies,
            summary=summary,
            risk_delta=risk_delta,
        )
