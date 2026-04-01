"""Language and framework detection."""

from __future__ import annotations

from collections import Counter

from ai_repo_agent.core.models import FileInventoryItem


class LanguageDetector:
    """Heuristic language and framework detector."""

    def detect(self, files: list[FileInventoryItem]) -> tuple[dict[str, int], list[str]]:
        counts = Counter(item.language for item in files if item.language != "unknown")
        paths = {item.path for item in files}
        frameworks: list[str] = []
        if "package.json" in paths:
            frameworks.append("node")
        if "pyproject.toml" in paths or "requirements.txt" in paths:
            frameworks.append("python")
        if "Cargo.toml" in paths:
            frameworks.append("rust")
        if "go.mod" in paths:
            frameworks.append("go")
        if any(path.endswith("manage.py") for path in paths):
            frameworks.append("django")
        if any(path.endswith("pom.xml") for path in paths):
            frameworks.append("maven")
        return dict(counts.most_common()), frameworks
