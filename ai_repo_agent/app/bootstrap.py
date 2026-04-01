"""Bootstrap the desktop application."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ai_repo_agent.services.app_context import AppContext
from ai_repo_agent.ui.main_window import MainWindow


def main() -> int:
    """Run the desktop application."""
    app = QApplication(sys.argv)
    context = AppContext("ai_repo_analyst.db")
    window = MainWindow(context)
    window.show()
    return app.exec()
