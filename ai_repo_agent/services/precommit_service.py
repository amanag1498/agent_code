"""Pre-commit support."""

from __future__ import annotations

from pathlib import Path


class PreCommitService:
    """Generate a repo-local pre-commit hook wrapper."""

    def install_hook(self, repo_path: str) -> Path:
        hooks_dir = Path(repo_path) / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_path = hooks_dir / "pre-commit"
        hook_path.write_text(
            "#!/bin/sh\n"
            "python3 -m ai_repo_agent.app.precommit_runner \"$PWD\"\n"
            "exit $?\n",
            encoding="utf-8",
        )
        hook_path.chmod(0o755)
        return hook_path
