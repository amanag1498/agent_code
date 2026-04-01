"""Repo and scan summary building."""

from __future__ import annotations

from pathlib import Path

from ai_repo_agent.core.models import DependencyDescriptor, FileInventoryItem, GitState


class SummaryBuilder:
    """Generate human-readable local summaries."""

    def repo_summary(
        self,
        root: Path,
        files: list[FileInventoryItem],
        languages: dict[str, int],
        frameworks: list[str],
        dependencies: list[DependencyDescriptor],
        git_state: GitState,
    ) -> str:
        language_summary = ", ".join(f"{name}({count})" for name, count in list(languages.items())[:5]) or "none"
        framework_summary = ", ".join(frameworks) or "none"
        return (
            f"{root.name}: {len(files)} files, languages {language_summary}, frameworks {framework_summary}, "
            f"{len(dependencies)} dependencies, git={git_state.is_git_repo}, branch={git_state.branch or 'n/a'}"
        )

    def scan_summary(self, finding_count: int, risk_score: float, compare_summary: str | None) -> str:
        return f"Findings: {finding_count}, risk score: {risk_score:.2f}. {compare_summary or ''}".strip()
