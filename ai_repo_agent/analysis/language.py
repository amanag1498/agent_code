"""Language and framework detection."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

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
            frameworks.append("spring")
        if any(path.endswith("next.config.js") or path.endswith("next.config.mjs") for path in paths):
            frameworks.append("react_next")
        if any(path.endswith("package.json") for path in paths):
            package_json = next((item.absolute_path for item in files if item.path == "package.json"), "")
            frameworks.extend(self._package_frameworks(package_json))
        if any(path.endswith(".py") for path in paths):
            frameworks.extend(self._python_frameworks(files))
        return dict(counts.most_common()), sorted(dict.fromkeys(frameworks))

    @staticmethod
    def _package_frameworks(package_json_path: str) -> list[str]:
        if not package_json_path:
            return []
        try:
            payload = json.loads(Path(package_json_path).read_text(encoding="utf-8"))
        except Exception:
            return []
        deps = {
            **payload.get("dependencies", {}),
            **payload.get("devDependencies", {}),
        }
        names = {name.lower() for name in deps}
        detected: list[str] = []
        if "express" in names:
            detected.append("express")
        if "react" in names or "next" in names:
            detected.append("react_next")
        return detected

    @staticmethod
    def _python_frameworks(files: list[FileInventoryItem]) -> list[str]:
        detected: list[str] = []
        for item in files:
            if not item.path.endswith((".py", ".txt", ".toml")):
                continue
            try:
                text = Path(item.absolute_path).read_text(encoding="utf-8", errors="ignore")[:4000].lower()
            except Exception:
                continue
            if "fastapi" in text and "fastapi" not in detected:
                detected.append("fastapi")
            if "django" in text and "django" not in detected:
                detected.append("django")
        return detected
