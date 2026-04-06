"""Snapshot comparison helpers."""

from __future__ import annotations

from difflib import SequenceMatcher

from ai_repo_agent.core.enums import DeltaType
from ai_repo_agent.core.models import CompareResult, DependencyRecord, FindingDeltaRecord, FindingRecord, SymbolRecord


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
        current_symbols: list[SymbolRecord] | None = None,
        previous_symbols: list[SymbolRecord] | None = None,
    ) -> CompareResult:
        previous_by_fingerprint = {finding.fingerprint: finding for finding in previous_findings}
        current_by_fingerprint = {finding.fingerprint: finding for finding in current_findings}
        deltas: list[FindingDeltaRecord] = []
        matched_previous_ids: set[int] = set()
        for fingerprint, current in current_by_fingerprint.items():
            previous = previous_by_fingerprint.get(fingerprint)
            if previous is None:
                previous = self._find_related_previous(current, previous_findings, matched_previous_ids)
            if previous is not None and previous.id is not None:
                matched_previous_ids.add(previous.id)
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
            if previous.id in matched_previous_ids:
                continue
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
        current_symbol_set = {
            (symbol.file_path, symbol.symbol_name, symbol.symbol_kind, symbol.line_start, symbol.line_end)
            for symbol in (current_symbols or [])
        }
        previous_symbol_set = {
            (symbol.file_path, symbol.symbol_name, symbol.symbol_kind, symbol.line_start, symbol.line_end)
            for symbol in (previous_symbols or [])
        }
        symbol_additions = len(current_symbol_set - previous_symbol_set)
        symbol_removals = len(previous_symbol_set - current_symbol_set)
        summary = (
            f"New findings: {sum(1 for d in deltas if d.delta_type == DeltaType.NEW.value)}, "
            f"fixed findings: {sum(1 for d in deltas if d.delta_type == DeltaType.FIXED.value)}, "
            f"changed files: {len(changed_files)}, changed dependencies: {len(changed_dependencies)}, "
            f"symbol additions: {symbol_additions}, symbol removals: {symbol_removals}"
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

    def _find_related_previous(
        self,
        current: FindingRecord,
        previous_findings: list[FindingRecord],
        matched_previous_ids: set[int],
    ) -> FindingRecord | None:
        candidates: list[tuple[float, FindingRecord]] = []
        current_title = self._normalized_title(current.title)
        for previous in previous_findings:
            if previous.id is not None and previous.id in matched_previous_ids:
                continue
            if current.file_path and previous.file_path and current.file_path != previous.file_path:
                continue
            if current.rule_id and previous.rule_id and current.rule_id == previous.rule_id:
                if self._line_distance(current, previous) <= 8:
                    return previous
            if current.category != previous.category:
                continue
            ratio = SequenceMatcher(None, current_title, self._normalized_title(previous.title)).ratio()
            if ratio >= 0.88 and self._line_distance(current, previous) <= 15:
                candidates.append((ratio, previous))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _normalized_title(title: str) -> str:
        return " ".join((title or "").lower().replace("_", " ").split())

    @staticmethod
    def _line_distance(current: FindingRecord, previous: FindingRecord) -> int:
        current_line = current.line_start or 0
        previous_line = previous.line_start or 0
        return abs(current_line - previous_line)
