"""Repo loader."""

from __future__ import annotations

from pathlib import Path

from ai_repo_agent.analysis.dependency import DependencyAnalyzer
from ai_repo_agent.analysis.language import LanguageDetector
from ai_repo_agent.analysis.summary import SummaryBuilder
from ai_repo_agent.core.models import RepoContext
from ai_repo_agent.repo.git_service import GitService
from ai_repo_agent.repo.inventory import FileInventoryService


class RepoLoader:
    """Load local repo context from disk."""

    def __init__(self) -> None:
        self.git_service = GitService()
        self.inventory = FileInventoryService()
        self.language_detector = LanguageDetector()
        self.dependency_analyzer = DependencyAnalyzer()
        self.summary_builder = SummaryBuilder()

    def load(self, path: str) -> RepoContext:
        root = Path(path).expanduser().resolve()
        files = self.inventory.scan(root)
        languages, frameworks = self.language_detector.detect(files)
        dependencies = self.dependency_analyzer.detect(root)
        git_state = self.git_service.inspect(root)
        summary = self.summary_builder.repo_summary(root, files, languages, frameworks, dependencies, git_state)
        return RepoContext(
            path=root,
            git_state=git_state,
            files=files,
            languages=languages,
            frameworks=frameworks,
            dependencies=dependencies,
            summary=summary,
        )
