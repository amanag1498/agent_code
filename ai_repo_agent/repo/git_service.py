"""Git inspection helpers."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from ai_repo_agent.core.models import GitState

LOGGER = logging.getLogger(__name__)


class GitService:
    """Git-aware repo state extraction using the local git CLI."""

    def inspect(self, path: Path) -> GitState:
        """Inspect git state for a path."""
        if not (path / ".git").exists():
            return GitState(is_git_repo=False)
        try:
            branch = self._run(path, ["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
            commit_hash = self._run(path, ["git", "rev-parse", "HEAD"]).strip()
            status = self._run(path, ["git", "status", "--porcelain"])
            changed_files = [line[3:] for line in status.splitlines() if len(line) > 3]
            diff_summary = self._run(path, ["git", "diff", "--stat"], allow_failure=True)
            return GitState(
                is_git_repo=True,
                branch=branch,
                commit_hash=commit_hash,
                dirty=bool(changed_files),
                changed_files=changed_files,
                diff_summary=diff_summary.strip(),
            )
        except Exception as exc:
            LOGGER.warning("Failed to inspect git repo %s: %s", path, exc)
            return GitState(is_git_repo=False)

    def compare_commits(self, path: Path, left: str, right: str) -> str:
        """Return a compact diff summary between two commits."""
        return self._run(path, ["git", "diff", "--stat", left, right], allow_failure=True).strip()

    def _run(self, cwd: Path, command: list[str], allow_failure: bool = False) -> str:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
        if result.returncode != 0 and not allow_failure:
            raise RuntimeError(result.stderr.strip() or "git command failed")
        return result.stdout
