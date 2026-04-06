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
        previous_by_family = {}
        for finding in previous_findings:
            if finding.family_id:
                previous_by_family.setdefault(finding.family_id, []).append(finding)
        deltas: list[FindingDeltaRecord] = []
        matched_previous_ids: set[int] = set()
        for fingerprint, current in current_by_fingerprint.items():
            previous = previous_by_fingerprint.get(fingerprint)
            if previous is None:
                previous = self._find_related_previous(current, previous_findings, matched_previous_ids)
            if previous is not None and previous.id is not None:
                matched_previous_ids.add(previous.id)
            delta = DeltaType.UNCHANGED if previous else DeltaType.NEW
            if previous is None and current.family_id and current.family_id in previous_by_family:
                delta = DeltaType.REGRESSED
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
        semantic_summaries = self._semantic_symbol_summaries(current_symbols or [], previous_symbols or [], changed_files)
        architectural_drift = self._architectural_drift(
            current_symbols or [],
            previous_symbols or [],
            current_dependencies,
            previous_dependencies,
            changed_files,
        )
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
            semantic_summaries=semantic_summaries,
            architectural_drift=architectural_drift,
            trend_metadata={
                "new_findings": sum(1 for d in deltas if d.delta_type == DeltaType.NEW.value),
                "fixed_findings": sum(1 for d in deltas if d.delta_type == DeltaType.FIXED.value),
                "regressed_findings": sum(1 for d in deltas if d.delta_type == DeltaType.REGRESSED.value),
                "changed_files": len(changed_files),
                "changed_dependencies": len(changed_dependencies),
                "symbol_additions": symbol_additions,
                "symbol_removals": symbol_removals,
            },
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
            if current.family_id and previous.family_id and current.family_id == previous.family_id:
                return previous
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

    @staticmethod
    def _semantic_symbol_summaries(
        current_symbols: list[SymbolRecord],
        previous_symbols: list[SymbolRecord],
        changed_files: list[str],
    ) -> list[str]:
        changed_set = set(changed_files)
        current_only = [
            symbol for symbol in current_symbols
            if (symbol.file_path, symbol.symbol_name, symbol.symbol_kind, symbol.line_start, symbol.line_end)
            not in {
                (prev.file_path, prev.symbol_name, prev.symbol_kind, prev.line_start, prev.line_end)
                for prev in previous_symbols
            }
        ]
        previous_only = [
            symbol for symbol in previous_symbols
            if (symbol.file_path, symbol.symbol_name, symbol.symbol_kind, symbol.line_start, symbol.line_end)
            not in {
                (curr.file_path, curr.symbol_name, curr.symbol_kind, curr.line_start, curr.line_end)
                for curr in current_symbols
            }
        ]
        summaries: list[str] = []
        hotspot_terms = {
            "auth": "auth middleware changed",
            "payment": "payment service call chain changed",
            "session": "session handling changed",
            "token": "token handling changed",
            "admin": "admin path changed",
            "db": "database interaction surface changed",
            "query": "query logic changed",
            "api": "API boundary changed",
        }
        changed_modules = {path.split("/")[0] if "/" in path else path for path in changed_set}
        for term, message in hotspot_terms.items():
            if any(term in symbol.file_path.lower() or term in symbol.symbol_name.lower() for symbol in current_only + previous_only):
                summaries.append(message)
        if changed_modules:
            summaries.append(f"Changed modules: {', '.join(sorted(changed_modules)[:6])}")
        additions_by_kind: dict[str, int] = {}
        removals_by_kind: dict[str, int] = {}
        for symbol in current_only:
            additions_by_kind[symbol.symbol_kind] = additions_by_kind.get(symbol.symbol_kind, 0) + 1
        for symbol in previous_only:
            removals_by_kind[symbol.symbol_kind] = removals_by_kind.get(symbol.symbol_kind, 0) + 1
        if additions_by_kind:
            summaries.append(
                "Symbol additions by kind: " + ", ".join(f"{kind}={count}" for kind, count in sorted(additions_by_kind.items()))
            )
        if removals_by_kind:
            summaries.append(
                "Symbol removals by kind: " + ", ".join(f"{kind}={count}" for kind, count in sorted(removals_by_kind.items()))
            )
        return summaries[:8]

    @staticmethod
    def _architectural_drift(
        current_symbols: list[SymbolRecord],
        previous_symbols: list[SymbolRecord],
        current_dependencies: list[DependencyRecord],
        previous_dependencies: list[DependencyRecord],
        changed_files: list[str],
    ) -> list[str]:
        drift: list[str] = []
        changed_roots: dict[str, int] = {}
        for path in changed_files:
            root = path.split("/", 1)[0]
            changed_roots[root] = changed_roots.get(root, 0) + 1
        if changed_roots:
            hottest = sorted(changed_roots.items(), key=lambda item: item[1], reverse=True)[:4]
            drift.append("Change concentration: " + ", ".join(f"{name}={count}" for name, count in hottest))
        current_kinds = {}
        previous_kinds = {}
        for symbol in current_symbols:
            current_kinds[symbol.symbol_kind] = current_kinds.get(symbol.symbol_kind, 0) + 1
        for symbol in previous_symbols:
            previous_kinds[symbol.symbol_kind] = previous_kinds.get(symbol.symbol_kind, 0) + 1
        kind_shift = []
        for kind in sorted(set(current_kinds) | set(previous_kinds)):
            delta = current_kinds.get(kind, 0) - previous_kinds.get(kind, 0)
            if delta:
                kind_shift.append(f"{kind} {delta:+d}")
        if kind_shift:
            drift.append("Code unit drift: " + ", ".join(kind_shift[:6]))
        dep_names_current = {dep.name for dep in current_dependencies}
        dep_names_previous = {dep.name for dep in previous_dependencies}
        dep_added = sorted(dep_names_current - dep_names_previous)
        dep_removed = sorted(dep_names_previous - dep_names_current)
        if dep_added:
            drift.append("Dependency additions: " + ", ".join(dep_added[:6]))
        if dep_removed:
            drift.append("Dependency removals: " + ", ".join(dep_removed[:6]))
        if any("api" in symbol.file_path.lower() or "controller" in symbol.symbol_name.lower() for symbol in current_symbols):
            drift.append("Interface surface updated in API/controller zones.")
        return drift[:8]
