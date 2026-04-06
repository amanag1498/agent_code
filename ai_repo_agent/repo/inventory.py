"""File inventory and fingerprinting."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ai_repo_agent.core.models import FileInventoryItem

LOGGER = logging.getLogger(__name__)

TEXT_SUFFIX_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".c": "c",
    ".cpp": "cpp",
}

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "__pycache__",
    ".idea",
    ".mypy_cache",
    "dist",
    "build",
    "target",
    "vendor",
}


class FileInventoryService:
    """Inventory local files for analysis."""

    def scan(self, root: Path) -> list[FileInventoryItem]:
        items: list[FileInventoryItem] = []
        for path in root.rglob("*"):
            if path.is_dir():
                if path.name in IGNORED_DIRS:
                    continue
                continue
            rel_path = str(path.relative_to(root))
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            try:
                payload = path.read_bytes()
            except Exception as exc:
                LOGGER.debug("Skipping unreadable file %s: %s", path, exc)
                continue
            is_binary = b"\x00" in payload[:8000]
            language = TEXT_SUFFIX_LANGUAGE.get(path.suffix.lower(), "unknown")
            lines = 0 if is_binary else payload.decode("utf-8", errors="ignore").count("\n") + 1
            items.append(
                FileInventoryItem(
                    path=rel_path,
                    absolute_path=str(path),
                    size=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                    language=language,
                    is_binary=is_binary,
                    lines=lines,
                )
            )
        return sorted(items, key=lambda item: item.path)


class RepoFingerprintService:
    """Compute a repo fingerprint from inventory."""

    def fingerprint(self, items: list[FileInventoryItem]) -> str:
        digest = hashlib.sha256()
        for item in items[:5000]:
            digest.update(item.path.encode("utf-8"))
            digest.update(item.sha256.encode("utf-8"))
        return digest.hexdigest()
