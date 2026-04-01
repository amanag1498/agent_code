"""Risk scoring heuristics."""

from __future__ import annotations

from ai_repo_agent.core.enums import Severity
from ai_repo_agent.core.models import Finding, GitState


class RiskScoringEngine:
    """Compute a heuristic repo risk score."""

    SEVERITY_WEIGHTS = {
        Severity.CRITICAL: 30.0,
        Severity.HIGH: 15.0,
        Severity.MEDIUM: 7.0,
        Severity.LOW: 3.0,
        Severity.INFO: 1.0,
        Severity.UNKNOWN: 2.0,
    }

    def score(self, findings: list[Finding], git_state: GitState, dependency_count: int) -> float:
        score = sum(self.SEVERITY_WEIGHTS.get(finding.severity, 2.0) for finding in findings)
        if git_state.dirty:
            score += min(10.0, len(git_state.changed_files))
        if dependency_count > 100:
            score += 5.0
        return round(score, 2)
