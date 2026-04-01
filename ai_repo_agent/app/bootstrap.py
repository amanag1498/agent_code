"""Bootstrap the local web application."""

from __future__ import annotations

import os

import uvicorn

from ai_repo_agent.web.server import create_app


def main() -> int:
    """Run the local web application."""
    host = os.getenv("AI_REPO_ANALYST_HOST", "127.0.0.1")
    port = int(os.getenv("AI_REPO_ANALYST_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
    return 0
