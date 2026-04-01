"""Main desktop UI."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ai_repo_agent.core.logging_config import get_memory_log_handler, set_logging_level
from ai_repo_agent.core.models import AppSettings, CompareResult, RepositoryRecord
from ai_repo_agent.llm.gemini_provider import GeminiProvider
from ai_repo_agent.reports.generator import ReportGenerator
from ai_repo_agent.services.app_context import AppContext
from ai_repo_agent.services.chat_orchestrator import ChatOrchestrator
from ai_repo_agent.services.compare_orchestrator import CompareOrchestrator
from ai_repo_agent.services.patch_orchestrator import PatchOrchestrator
from ai_repo_agent.services.precommit_service import PreCommitService
from ai_repo_agent.services.scan_orchestrator import ScanOrchestrator
from ai_repo_agent.watch.monitor import RepoWatchService

LOGGER = logging.getLogger(__name__)

APP_STYLESHEET = """
QMainWindow {
    background: #f4efe7;
}
QMenuBar, QToolBar, QStatusBar {
    background: #efe5d7;
    color: #2f241d;
}
QToolBar {
    border: none;
    spacing: 8px;
    padding: 6px 10px;
}
QWidget {
    color: #2f241d;
    font-family: "Avenir Next", "Trebuchet MS", sans-serif;
    font-size: 13px;
}
QLabel#brandTitle {
    font-size: 28px;
    font-weight: 700;
    color: #1e1713;
}
QLabel#brandSubtitle {
    color: #725a4c;
    font-size: 12px;
    letter-spacing: 1px;
    text-transform: uppercase;
}
QFrame#sidebarCard, QFrame#panelCard, QFrame#heroCard, QFrame#statCard {
    background: #fffaf4;
    border: 1px solid #e3d3c2;
    border-radius: 18px;
}
QFrame#heroCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fff3e5, stop:1 #efe2d2);
}
QLabel#heroTitle {
    font-size: 26px;
    font-weight: 700;
}
QLabel#heroMeta {
    color: #7a5f50;
    font-size: 12px;
}
QLabel#sectionTitle {
    font-size: 16px;
    font-weight: 700;
}
QLabel#muted {
    color: #7a5f50;
}
QLabel#statValue {
    font-size: 26px;
    font-weight: 700;
}
QLabel#statLabel {
    color: #7a5f50;
    font-size: 12px;
    text-transform: uppercase;
}
QPushButton {
    background: #c96f3d;
    color: white;
    border: none;
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #b85d2d;
}
QPushButton#secondaryButton {
    background: #efe5d7;
    color: #3b3028;
    border: 1px solid #ddc7b2;
}
QPushButton#secondaryButton:hover {
    background: #e5d8c7;
}
QListWidget, QTreeWidget, QTableWidget, QTextEdit, QPlainTextEdit, QLineEdit, QComboBox {
    background: #fffcf8;
    border: 1px solid #e3d3c2;
    border-radius: 14px;
    padding: 6px;
}
QListWidget#navList::item {
    margin: 3px 0;
    padding: 10px 12px;
    border-radius: 12px;
}
QListWidget#navList::item:selected {
    background: #2f241d;
    color: #fffaf4;
}
QHeaderView::section {
    background: #efe5d7;
    border: none;
    border-bottom: 1px solid #ddc7b2;
    padding: 8px;
    font-weight: 700;
}
QSplitter::handle {
    background: #eadac9;
    width: 2px;
}
"""


class DropArea(QFrame):
    """Drag-and-drop area for local paths."""

    def __init__(self, on_path_dropped) -> None:
        super().__init__()
        self.on_path_dropped = on_path_dropped
        self.setAcceptDrops(True)
        self.setObjectName("heroCard")
        layout = QVBoxLayout(self)
        title = QLabel("Drop A Repo To Start")
        title.setObjectName("heroTitle")
        subtitle = QLabel("Folders, repos, or individual files are accepted. AI Repo Analyst builds local memory first, then runs Gemini review.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroMeta")
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        if urls:
            self.on_path_dropped(urls[0].toLocalFile())


class StatCard(QFrame):
    """Small summary card."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.setObjectName("statCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.value_label = QLabel("0")
        self.value_label.setObjectName("statValue")
        self.name_label = QLabel(label)
        self.name_label.setObjectName("statLabel")
        layout.addWidget(self.value_label)
        layout.addWidget(self.name_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class PanelCard(QFrame):
    """Reusable card panel with title and body layout."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("panelCard")
        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.setContentsMargins(18, 18, 18, 18)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        self.outer_layout.addWidget(title_label)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.settings = self.context.settings.load()
        self.report_generator = ReportGenerator()
        self.watch_service = RepoWatchService()
        self.precommit_service = PreCommitService()
        self.log_handler = get_memory_log_handler()
        self.current_repo: RepositoryRecord | None = None
        self.current_snapshot_id: int | None = None
        self.current_finding_id: int | None = None
        self._all_findings = []
        self._compare_result: CompareResult | None = None
        self.scan_orchestrator = self._build_scan_orchestrator()
        self.compare_orchestrator = CompareOrchestrator(self.context.snapshots, self.context.findings, self.context.dependencies)
        self._build_ui()
        self.refresh_recent_repos()
        self._apply_watch_mode()
        self._start_log_refresh()

    def _build_scan_orchestrator(self) -> ScanOrchestrator:
        return ScanOrchestrator(
            self.context.repositories,
            self.context.snapshots,
            self.context.files,
            self.context.dependencies,
            self.context.symbols,
            self.context.embeddings,
            self.context.findings,
            self.context.reviews,
            self.context.scan_runs,
            self.settings,
        )

    def _build_ui(self) -> None:
        self.setWindowTitle("AI Repo Analyst")
        self.resize(1520, 940)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_menu()
        self._build_toolbar()
        self.statusBar().showMessage("Ready")

        container = QWidget()
        root_layout = QHBoxLayout(container)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(18)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter)

        sidebar = self._build_sidebar()
        splitter.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        self.hero_card = self._build_hero()
        content_layout.addWidget(self.hero_card)

        self.pages = QStackedWidget()
        self.overview_page = self._build_overview_page()
        self.repo_tree_page = self._build_repo_tree_page()
        self.findings_page = self._build_findings_page()
        self.compare_page = self._build_compare_page()
        self.memory_page = self._build_memory_page()
        self.chat_page = self._build_chat_page()
        self.patch_page = self._build_patch_page()
        self.logs_page = self._build_logs_page()
        self.settings_page = self._build_settings_page()
        for page in [
            self.overview_page,
            self.repo_tree_page,
            self.findings_page,
            self.compare_page,
            self.memory_page,
            self.chat_page,
            self.patch_page,
            self.logs_page,
            self.settings_page,
        ]:
            self.pages.addWidget(page)
        content_layout.addWidget(self.pages)
        splitter.addWidget(content)
        splitter.setSizes([340, 1180])

        self.setCentralWidget(container)
        self.nav_list.setCurrentRow(0)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebarCard")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        brand_title = QLabel("AI Repo Analyst")
        brand_title.setObjectName("brandTitle")
        brand_subtitle = QLabel("LOCAL MEMORY + GEMINI REVIEW")
        brand_subtitle.setObjectName("brandSubtitle")
        layout.addWidget(brand_title)
        layout.addWidget(brand_subtitle)

        self.drop_area = DropArea(self.load_path)
        layout.addWidget(self.drop_area)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Open Folder")
        self.open_button.clicked.connect(self.open_folder_dialog)
        self.rescan_button = QPushButton("Rescan")
        self.rescan_button.clicked.connect(self.rescan_current_repo)
        self.rescan_button.setObjectName("secondaryButton")
        actions.addWidget(self.open_button)
        actions.addWidget(self.rescan_button)
        layout.addLayout(actions)

        recent_label = QLabel("Recent Repositories")
        recent_label.setObjectName("sectionTitle")
        layout.addWidget(recent_label)
        self.recent_list = QListWidget()
        self.recent_list.itemClicked.connect(self._recent_clicked)
        layout.addWidget(self.recent_list, 1)

        nav_label = QLabel("Workspace")
        nav_label.setObjectName("sectionTitle")
        layout.addWidget(nav_label)
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        for name in ["Overview", "Repo Tree", "Findings", "Compare", "Memory", "Repo Chat", "Patch Lab", "Logs", "Settings"]:
            self.nav_list.addItem(name)
        self.nav_list.currentRowChanged.connect(self._switch_page)
        layout.addWidget(self.nav_list, 1)
        return sidebar

    def _build_hero(self) -> QWidget:
        hero = QFrame()
        hero.setObjectName("heroCard")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(22, 18, 22, 18)

        left = QVBoxLayout()
        self.hero_title = QLabel("Drop a repository to begin")
        self.hero_title.setObjectName("heroTitle")
        self.hero_meta = QLabel("No repository loaded yet.")
        self.hero_meta.setObjectName("heroMeta")
        left.addWidget(self.hero_title)
        left.addWidget(self.hero_meta)
        layout.addLayout(left, 2)

        right = QHBoxLayout()
        self.findings_stat = StatCard("Findings")
        self.risk_stat = StatCard("Risk Score")
        self.changes_stat = StatCard("Changes")
        self.memory_stat = StatCard("Memory Units")
        right.addWidget(self.findings_stat)
        right.addWidget(self.risk_stat)
        right.addWidget(self.changes_stat)
        right.addWidget(self.memory_stat)
        layout.addLayout(right, 3)
        return hero

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        open_action = QAction("Open Folder", self)
        open_action.triggered.connect(self.open_folder_dialog)
        file_menu.addAction(open_action)
        export_action = QAction("Export Report", self)
        export_action.triggered.connect(self.export_report)
        file_menu.addAction(export_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)
        open_action = QAction("Open", self)
        open_action.triggered.connect(self.open_folder_dialog)
        toolbar.addAction(open_action)
        rescan_action = QAction("Rescan", self)
        rescan_action.triggered.connect(self.rescan_current_repo)
        toolbar.addAction(rescan_action)

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        cards_panel = PanelCard("Repository Overview")
        stats_layout = QGridLayout()
        self.repo_stats_text = QTextEdit()
        self.repo_stats_text.setReadOnly(True)
        self.repo_stats_text.setMinimumHeight(180)
        self.overview_summary = QTextEdit()
        self.overview_summary.setReadOnly(True)
        self.overview_summary.setMinimumHeight(180)
        stats_layout.addWidget(self.repo_stats_text, 0, 0)
        stats_layout.addWidget(self.overview_summary, 0, 1)
        cards_panel.outer_layout.addLayout(stats_layout)
        layout.addWidget(cards_panel)

        lower_panel = PanelCard("Release Readiness")
        lower_grid = QGridLayout()
        self.llm_summary_text = QTextEdit()
        self.llm_summary_text.setReadOnly(True)
        self.llm_summary_text.setMinimumHeight(180)
        self.repo_health_text = QTextEdit()
        self.repo_health_text.setReadOnly(True)
        self.repo_health_text.setMinimumHeight(180)
        lower_grid.addWidget(self.llm_summary_text, 0, 0)
        lower_grid.addWidget(self.repo_health_text, 0, 1)
        lower_panel.outer_layout.addLayout(lower_grid)
        layout.addWidget(lower_panel)
        return page

    def _build_repo_tree_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        tree_panel = PanelCard("Repository Tree")
        self.repo_tree = QTreeWidget()
        self.repo_tree.setHeaderLabels(["Path", "Language", "Size"])
        self.repo_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.repo_tree.itemClicked.connect(self._repo_tree_clicked)
        tree_panel.outer_layout.addWidget(self.repo_tree)

        meta_panel = PanelCard("File Detail")
        self.file_meta = QTextEdit()
        self.file_meta.setReadOnly(True)
        meta_panel.outer_layout.addWidget(self.file_meta)

        layout.addWidget(tree_panel, 3)
        layout.addWidget(meta_panel, 2)
        return page

    def _build_findings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        filter_panel = PanelCard("Finding Filters")
        filter_row = QHBoxLayout()
        self.severity_filter = QComboBox()
        self.severity_filter.addItems(["all", "critical", "high", "medium", "low", "info", "unknown"])
        self.category_filter = QComboBox()
        self.category_filter.addItems(["all", "security", "vulnerability", "architecture", "quality", "risky_change", "dependency"])
        self.scanner_filter = QComboBox()
        self.scanner_filter.addItems(["all", "gemini"])
        for widget, label in [
            (self.severity_filter, "Severity"),
            (self.category_filter, "Category"),
            (self.scanner_filter, "Source"),
        ]:
            column = QVBoxLayout()
            name = QLabel(label)
            name.setObjectName("muted")
            column.addWidget(name)
            column.addWidget(widget)
            filter_row.addLayout(column)
            widget.currentTextChanged.connect(self._apply_finding_filters)
        filter_panel.outer_layout.addLayout(filter_row)
        layout.addWidget(filter_panel)

        body = QHBoxLayout()
        table_panel = PanelCard("Findings")
        self.findings_table = QTableWidget(0, 6)
        self.findings_table.setHorizontalHeaderLabels(["Severity", "Source", "Category", "Title", "File", "Status"])
        self.findings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.findings_table.itemSelectionChanged.connect(self._finding_selected)
        table_panel.outer_layout.addWidget(self.findings_table)

        detail_panel = PanelCard("Finding Detail")
        self.finding_detail = QTextEdit()
        self.finding_detail.setReadOnly(True)
        detail_panel.outer_layout.addWidget(self.finding_detail)
        body.addWidget(table_panel, 3)
        body.addWidget(detail_panel, 2)
        layout.addLayout(body)
        return page

    def _build_compare_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        top = QHBoxLayout()
        self.compare_new_stat = StatCard("New")
        self.compare_fixed_stat = StatCard("Fixed")
        self.compare_unchanged_stat = StatCard("Unchanged")
        self.compare_dependency_stat = StatCard("Dependency Delta")
        top.addWidget(self.compare_new_stat)
        top.addWidget(self.compare_fixed_stat)
        top.addWidget(self.compare_unchanged_stat)
        top.addWidget(self.compare_dependency_stat)
        layout.addLayout(top)

        body = QHBoxLayout()
        summary_panel = PanelCard("Comparison Summary")
        self.compare_summary = QTextEdit()
        self.compare_summary.setReadOnly(True)
        summary_panel.outer_layout.addWidget(self.compare_summary)

        changes_panel = PanelCard("Changed Files / Dependencies")
        self.compare_changes = QTextEdit()
        self.compare_changes.setReadOnly(True)
        changes_panel.outer_layout.addWidget(self.compare_changes)
        body.addWidget(summary_panel, 2)
        body.addWidget(changes_panel, 2)
        layout.addLayout(body)
        return page

    def _build_memory_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)

        timeline_panel = PanelCard("Snapshot Timeline")
        self.memory_list = QListWidget()
        self.memory_list.itemClicked.connect(self._memory_selected)
        timeline_panel.outer_layout.addWidget(self.memory_list)

        detail_column = QVBoxLayout()
        detail_panel = PanelCard("Snapshot Memory")
        self.memory_detail = QTextEdit()
        self.memory_detail.setReadOnly(True)
        detail_panel.outer_layout.addWidget(self.memory_detail)

        symbol_panel = PanelCard("Symbols")
        self.symbol_memory = QTextEdit()
        self.symbol_memory.setReadOnly(True)
        symbol_panel.outer_layout.addWidget(self.symbol_memory)

        chunk_panel = PanelCard("Chunks")
        self.chunk_memory = QTextEdit()
        self.chunk_memory.setReadOnly(True)
        chunk_panel.outer_layout.addWidget(self.chunk_memory)

        detail_column.addWidget(detail_panel, 1)
        detail_column.addWidget(symbol_panel, 1)
        detail_column.addWidget(chunk_panel, 1)
        layout.addWidget(timeline_panel, 1)
        layout.addLayout(detail_column, 2)
        return page

    def _build_chat_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        panel = PanelCard("Repository Chat")
        self.chat_output = QTextEdit()
        self.chat_output.setReadOnly(True)
        self.chat_input = QPlainTextEdit()
        self.chat_input.setPlaceholderText("Ask about risk, architecture, auth flows, dependencies, or changed code...")
        send_button = QPushButton("Send Question")
        send_button.clicked.connect(self.send_chat_message)
        panel.outer_layout.addWidget(self.chat_output)
        panel.outer_layout.addWidget(self.chat_input)
        panel.outer_layout.addWidget(send_button)
        layout.addWidget(panel)
        return page

    def _build_patch_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        panel = PanelCard("Patch Lab")
        helper = QLabel("Select a finding from the Findings page, then generate a conservative patch draft grounded in local evidence.")
        helper.setWordWrap(True)
        helper.setObjectName("muted")
        self.patch_output = QTextEdit()
        self.patch_output.setReadOnly(True)
        patch_button = QPushButton("Generate Patch For Selected Finding")
        patch_button.clicked.connect(self.generate_patch_for_selected_finding)
        panel.outer_layout.addWidget(helper)
        panel.outer_layout.addWidget(self.patch_output)
        panel.outer_layout.addWidget(patch_button)
        layout.addWidget(panel)
        return page

    def _build_logs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        panel = PanelCard("Execution Logs")
        controls = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self.refresh_logs)
        clear_button = QPushButton("Clear View")
        clear_button.setObjectName("secondaryButton")
        clear_button.clicked.connect(lambda: self.logs_output.clear())
        controls.addWidget(refresh_button)
        controls.addWidget(clear_button)
        controls.addStretch(1)
        panel.outer_layout.addLayout(controls)
        self.logs_output = QTextEdit()
        self.logs_output.setReadOnly(True)
        panel.outer_layout.addWidget(self.logs_output)
        self.log_file_label = QLabel("Log file: ai_repo_analyst.log")
        self.log_file_label.setObjectName("muted")
        panel.outer_layout.addWidget(self.log_file_label)
        layout.addWidget(panel)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)

        settings_panel = PanelCard("Runtime Settings")
        form = QFormLayout()
        self.api_key_input = QLineEdit(self.settings.gemini_api_key)
        self.api_key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.model_input = QLineEdit(self.settings.gemini_model)
        self.timeout_input = QLineEdit(str(self.settings.llm_timeout_seconds))
        self.retry_input = QLineEdit(str(self.settings.llm_retry_count))
        self.max_findings_input = QLineEdit(str(self.settings.llm_max_findings_per_scan))
        self.chunk_lines_input = QLineEdit(str(self.settings.embedding_chunk_lines))
        self.db_path_input = QLineEdit(self.settings.database_path)
        self.watch_checkbox = QCheckBox()
        self.watch_checkbox.setChecked(self.settings.watch_mode_enabled)
        self.log_level_input = QComboBox()
        self.log_level_input.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_input.setCurrentText(self.settings.logging_level.upper())
        form.addRow("Gemini API Key", self.api_key_input)
        form.addRow("Gemini Model", self.model_input)
        form.addRow("Timeout Seconds", self.timeout_input)
        form.addRow("Retry Count", self.retry_input)
        form.addRow("Max Findings Per Scan", self.max_findings_input)
        form.addRow("Chunk Lines", self.chunk_lines_input)
        form.addRow("Watch Mode", self.watch_checkbox)
        form.addRow("Database Path", self.db_path_input)
        form.addRow("Logging Level", self.log_level_input)
        settings_panel.outer_layout.addLayout(form)
        install_hook_button = QPushButton("Install Pre-Commit Hook")
        install_hook_button.setObjectName("secondaryButton")
        install_hook_button.clicked.connect(self.install_precommit_hook)
        save_button = QPushButton("Save Settings")
        save_button.clicked.connect(self.save_settings)
        actions = QHBoxLayout()
        actions.addWidget(install_hook_button)
        actions.addWidget(save_button)
        settings_panel.outer_layout.addLayout(actions)

        notes_panel = PanelCard("Operational Notes")
        self.settings_notes = QTextEdit()
        self.settings_notes.setReadOnly(True)
        self.settings_notes.setPlainText(
            "Gemini settings are used for findings, repo chat, patch suggestions, and repo summaries.\n\n"
            "If requests time out, reduce Max Findings Per Scan or increase Timeout Seconds.\n\n"
            "The database path is persisted, but the current session remains attached to the already-open database until restart."
        )
        notes_panel.outer_layout.addWidget(self.settings_notes)

        layout.addWidget(settings_panel, 2)
        layout.addWidget(notes_panel, 1)
        return page

    def _switch_page(self, index: int) -> None:
        if hasattr(self, "pages"):
            self.pages.setCurrentIndex(index)

    def open_folder_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select repository or folder")
        if path:
            self.load_path(path)

    def _recent_clicked(self, item: QListWidgetItem) -> None:
        repo = item.data(Qt.UserRole)
        if repo:
            self.load_path(repo.path)

    def load_path(self, path: str) -> None:
        self.statusBar().showMessage(f"Scanning {path}...")
        LOGGER.info("Starting repo scan for %s", path)
        try:
            result = self.scan_orchestrator.scan(path)
            repos = self.context.repositories.list_all()
            self.current_repo = next((repo for repo in repos if repo.path == str(Path(path).resolve())), None)
            self.refresh_recent_repos()
            self.populate_snapshot(result.snapshot.id or 0)
            self._apply_watch_mode()
            self.statusBar().showMessage("Scan completed")
            LOGGER.info(
                "Scan completed for %s: snapshot=%s findings=%s risk_score=%s",
                path,
                result.snapshot.id,
                len(result.findings),
                result.risk_score,
            )
        except Exception as exc:
            LOGGER.exception("Scan failed for %s", path)
            QMessageBox.critical(self, "Scan Failed", str(exc))
            self.statusBar().showMessage("Scan failed")

    def rescan_current_repo(self) -> None:
        if not self.current_repo:
            QMessageBox.information(self, "Rescan", "Open a repository first.")
            return
        self.load_path(self.current_repo.path)

    def refresh_recent_repos(self) -> None:
        self.recent_list.clear()
        for repo in self.context.repositories.list_all():
            item = QListWidgetItem(f"{repo.name}\n{repo.path}")
            item.setData(Qt.UserRole, repo)
            self.recent_list.addItem(item)

    def populate_snapshot(self, snapshot_id: int) -> None:
        snapshot = self.context.snapshots.get(snapshot_id)
        repo = self.context.repositories.get_by_id(snapshot.repo_id)
        self.current_snapshot_id = snapshot_id
        self.current_repo = repo
        findings = self.context.findings.list_for_snapshot(snapshot_id)
        self._all_findings = findings
        files = self.context.files.list_for_repo(repo.id or 0)
        compare = self.compare_orchestrator.compare_latest(repo.id or 0)
        self._compare_result = compare
        reviews = self.context.reviews.list_for_snapshot(snapshot_id)
        symbols = self.context.symbols.list_for_snapshot(snapshot_id)
        chunks = self.context.embeddings.list_for_snapshot(snapshot_id)
        patches = self.context.patches.list_for_snapshot(snapshot_id)
        scan_runs = self.context.connection.execute(
            "SELECT scanner_name, status, message, finished_at FROM scan_runs WHERE snapshot_id = ? ORDER BY id DESC",
            (snapshot_id,),
        ).fetchall()

        self.hero_title.setText(repo.name)
        self.hero_meta.setText(
            f"{repo.path}   |   Branch: {snapshot.branch or 'n/a'}   |   Commit: {snapshot.commit_hash or 'n/a'}   |   Dirty: {snapshot.dirty_flag}"
        )
        self.findings_stat.set_value(str(len(findings)))
        self.risk_stat.set_value(self._extract_risk(snapshot.summary))
        self.changes_stat.set_value(str(len(compare.deltas) if compare else 0))
        self.memory_stat.set_value(str(len(symbols) + len(chunks)))

        self.repo_stats_text.setPlainText(
            f"Repository: {repo.name}\n"
            f"Path: {repo.path}\n"
            f"Git Repo: {repo.is_git_repo}\n"
            f"Snapshot ID: {snapshot.id}\n"
            f"Fingerprint: {repo.fingerprint}\n\n"
            f"Files: {len(files)}\n"
            f"Findings: {len(findings)}\n"
            f"Symbols: {len(symbols)}\n"
            f"Chunks: {len(chunks)}\n"
            f"Patches: {len(patches)}"
        )
        self.overview_summary.setPlainText(snapshot.summary)
        self.llm_summary_text.setPlainText(
            "\n\n".join(
                [
                    f"[{row['scanner_name']}] {row['status']}\n{row['message']}\nFinished: {row['finished_at'] or 'n/a'}"
                    for row in scan_runs[:8]
                ]
            )
            or "No scan execution history for this snapshot."
        )
        self.repo_health_text.setPlainText(
            f"LLM Reviews: {len(reviews)}\n"
            f"Changed Files: {snapshot.changed_files_count}\n"
            f"Dependency Count: {len(self.context.dependencies.list_for_snapshot(snapshot_id))}\n"
            f"Recent Patch Suggestions: {len(patches)}\n\n"
            f"Diff Summary:\n{snapshot.diff_summary or 'No diff summary available.'}"
        )

        self.repo_tree.clear()
        for file_record in files:
            item = QTreeWidgetItem([file_record.path, file_record.language, str(file_record.size)])
            self.repo_tree.addTopLevelItem(item)
        self._render_findings(findings)
        self._render_compare(compare)
        self.memory_list.clear()
        for item in self.context.snapshots.list_for_repo(repo.id or 0):
            memory_item = QListWidgetItem(f"Snapshot {item.id}\n{item.created_at}\n{item.branch or 'n/a'}")
            memory_item.setData(Qt.UserRole, item)
            self.memory_list.addItem(memory_item)
        self.memory_detail.setPlainText(
            f"Snapshot: {snapshot.id}\nCreated: {snapshot.created_at}\nSummary: {snapshot.summary}\n\n"
            f"Stored reviews: {len(reviews)}\nStored patches: {len(patches)}"
        )
        self.symbol_memory.setPlainText("\n".join(f"{symbol.symbol_kind}: {symbol.symbol_name} [{symbol.file_path}]" for symbol in symbols[:250]))
        self.chunk_memory.setPlainText("\n\n".join(f"{chunk.file_path}\n{chunk.chunk_text[:450]}" for chunk in chunks[:16]))
        self.patch_output.setPlainText("\n\n".join(f"{patch.summary}\n{patch.suggested_diff}" for patch in patches[:6]) or "No patch suggestions yet.")
        self.chat_output.setPlainText("")
        self.finding_detail.setPlainText("Select a finding to inspect its structured Gemini judgment.")

    def _render_compare(self, compare: CompareResult | None) -> None:
        if not compare:
            self.compare_new_stat.set_value("0")
            self.compare_fixed_stat.set_value("0")
            self.compare_unchanged_stat.set_value("0")
            self.compare_dependency_stat.set_value("0")
            self.compare_summary.setPlainText("No prior snapshot available.")
            self.compare_changes.setPlainText("Scan the repository again later to compare changes.")
            return
        new_count = sum(1 for delta in compare.deltas if delta.delta_type == "new")
        fixed_count = sum(1 for delta in compare.deltas if delta.delta_type == "fixed")
        unchanged_count = sum(1 for delta in compare.deltas if delta.delta_type == "unchanged")
        self.compare_new_stat.set_value(str(new_count))
        self.compare_fixed_stat.set_value(str(fixed_count))
        self.compare_unchanged_stat.set_value(str(unchanged_count))
        self.compare_dependency_stat.set_value(str(len(compare.changed_dependencies)))
        self.compare_summary.setPlainText(
            f"{compare.summary}\n\nRisk Delta: {compare.risk_delta}\n"
            f"Previous Snapshot: {compare.previous_snapshot_id}\nCurrent Snapshot: {compare.current_snapshot_id}"
        )
        self.compare_changes.setPlainText(
            "Changed Dependencies:\n"
            + ("\n".join(compare.changed_dependencies[:40]) or "None")
            + "\n\nChanged Files:\n"
            + ("\n".join(compare.changed_files[:40]) or "None captured for this comparison.")
        )

    def _repo_tree_clicked(self, item: QTreeWidgetItem) -> None:
        self.file_meta.setPlainText(f"Path: {item.text(0)}\nLanguage: {item.text(1)}\nSize: {item.text(2)} bytes")

    def _finding_selected(self) -> None:
        row = self.findings_table.currentRow()
        if row < 0:
            return
        finding = self.findings_table.item(row, 0).data(Qt.UserRole)
        self.current_finding_id = finding.id
        reviews = self.context.connection.execute(
            "SELECT * FROM llm_reviews WHERE finding_id = ? ORDER BY id DESC LIMIT 1",
            (finding.id,),
        ).fetchall()
        llm_text = "No LLM review stored."
        if reviews:
            review = reviews[0]
            llm_text = (
                f"Verdict: {review['verdict']}\n"
                f"Confidence: {review['confidence']}\n"
                f"Severity Override: {review['severity_override']}\n"
                f"Reasoning: {review['reasoning_summary']}\n"
                f"Remediation: {review['remediation_summary']}"
            )
        raw_payload = finding.raw_payload
        try:
            raw_payload = json.dumps(json.loads(raw_payload), indent=2)
        except Exception:
            pass
        self.finding_detail.setPlainText(
            f"Title: {finding.title}\n"
            f"Description: {finding.description}\n"
            f"File: {finding.file_path or 'n/a'}\n"
            f"Lines: {finding.line_start}-{finding.line_end}\n"
            f"Category: {finding.category}\n"
            f"Source: {finding.scanner_name}\n"
            f"Fingerprint: {finding.fingerprint}\n\n"
            f"Structured Judgment\n{llm_text}\n\n"
            f"Raw Payload\n{raw_payload}"
        )

    def _memory_selected(self, item: QListWidgetItem) -> None:
        snapshot = item.data(Qt.UserRole)
        reviews = self.context.reviews.list_for_snapshot(snapshot.id)
        patches = self.context.patches.list_for_snapshot(snapshot.id)
        self.memory_detail.setPlainText(
            f"Snapshot {snapshot.id}\n"
            f"Created: {snapshot.created_at}\n"
            f"Branch: {snapshot.branch or 'n/a'}\n"
            f"Commit: {snapshot.commit_hash or 'n/a'}\n"
            f"Dirty: {snapshot.dirty_flag}\n\n"
            f"Summary:\n{snapshot.summary}\n\n"
            f"Stored reviews: {len(reviews)}\nStored patches: {len(patches)}"
        )

    def _render_findings(self, findings) -> None:
        self.findings_table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            values = [finding.severity, finding.scanner_name, finding.category, finding.title, finding.file_path or "", finding.status]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if col == 0:
                    cell.setData(Qt.UserRole, finding)
                self.findings_table.setItem(row, col, cell)

    def _apply_finding_filters(self) -> None:
        severity = self.severity_filter.currentText()
        category = self.category_filter.currentText()
        scanner = self.scanner_filter.currentText()
        filtered = [
            finding
            for finding in self._all_findings
            if (severity == "all" or finding.severity == severity)
            and (category == "all" or finding.category == category)
            and (scanner == "all" or finding.scanner_name == scanner)
        ]
        self._render_findings(filtered)

    def _apply_watch_mode(self) -> None:
        if self.settings.watch_mode_enabled and self.current_repo:
            self.watch_service.start(Path(self.current_repo.path), self._on_repo_changed)
            self.statusBar().showMessage(f"Watching {self.current_repo.path}")
            LOGGER.info("Watch mode enabled for %s", self.current_repo.path)
        else:
            self.watch_service.stop()

    def _on_repo_changed(self) -> None:
        message = "Repository changed on disk. Rescan recommended."
        self.statusBar().showMessage(message)
        LOGGER.info(message)

    def save_settings(self) -> None:
        settings = AppSettings(
            database_path=self.db_path_input.text().strip() or self.settings.database_path,
            gemini_api_key=self.api_key_input.text().strip(),
            gemini_model=self.model_input.text().strip() or self.settings.gemini_model,
            llm_timeout_seconds=int(self.timeout_input.text().strip() or self.settings.llm_timeout_seconds),
            llm_retry_count=int(self.retry_input.text().strip() or self.settings.llm_retry_count),
            llm_max_findings_per_scan=int(self.max_findings_input.text().strip() or self.settings.llm_max_findings_per_scan),
            embedding_chunk_lines=int(self.chunk_lines_input.text().strip() or self.settings.embedding_chunk_lines),
            watch_mode_enabled=self.watch_checkbox.isChecked(),
            logging_level=self.log_level_input.currentText(),
        )
        self.context.settings.save(settings)
        self.settings = settings
        set_logging_level(settings.logging_level)
        self.scan_orchestrator = self._build_scan_orchestrator()
        self._apply_watch_mode()
        LOGGER.info(
            "Settings updated: model=%s timeout=%s retries=%s max_findings=%s log_level=%s",
            settings.gemini_model,
            settings.llm_timeout_seconds,
            settings.llm_retry_count,
            settings.llm_max_findings_per_scan,
            settings.logging_level,
        )
        QMessageBox.information(self, "Settings", "Settings saved. Restart only if you changed database path.")
        self.refresh_logs()

    def _provider(self) -> GeminiProvider | None:
        if not self.settings.gemini_api_key:
            return None
        return GeminiProvider(
            api_key=self.settings.gemini_api_key,
            model_name=self.settings.gemini_model,
            timeout_seconds=self.settings.llm_timeout_seconds,
            retry_count=self.settings.llm_retry_count,
        )

    def send_chat_message(self) -> None:
        if not self.current_repo or not self.current_snapshot_id:
            QMessageBox.information(self, "Repo Chat", "Scan a repository first.")
            return
        question = self.chat_input.toPlainText().strip()
        if not question:
            return
        LOGGER.info("Repo chat question submitted for repo_id=%s snapshot_id=%s", self.current_repo.id, self.current_snapshot_id)
        orchestrator = ChatOrchestrator(self.context.chat, self.context.embeddings, self.context.reviews, self._provider())
        try:
            answer = orchestrator.ask(self.current_repo.id or 0, self.current_snapshot_id, question)
        except Exception as exc:
            LOGGER.exception("Repo chat failed")
            answer = str(exc)
        self.chat_output.append(f"User\n{question}\n\nAssistant\n{answer}\n\n")
        self.chat_input.clear()

    def generate_patch_for_selected_finding(self) -> None:
        if not self.current_repo or not self.current_snapshot_id or not self.current_finding_id:
            QMessageBox.information(self, "Patch Suggestions", "Select a finding first.")
            return
        LOGGER.info(
            "Generating patch suggestion for repo_id=%s snapshot_id=%s finding_id=%s",
            self.current_repo.id,
            self.current_snapshot_id,
            self.current_finding_id,
        )
        orchestrator = PatchOrchestrator(
            self.context.findings,
            self.context.embeddings,
            self.context.reviews,
            self.context.patches,
            self._provider(),
        )
        try:
            patch = orchestrator.suggest(self.current_repo.path, self.current_snapshot_id, self.current_finding_id)
        except Exception as exc:
            LOGGER.exception("Patch suggestion generation failed")
            patch = str(exc)
        self.patch_output.setPlainText(patch)

    def install_precommit_hook(self) -> None:
        if not self.current_repo:
            QMessageBox.information(self, "Pre-Commit", "Select a git repository first.")
            return
        try:
            hook_path = self.precommit_service.install_hook(self.current_repo.path)
            LOGGER.info("Installed pre-commit hook at %s", hook_path)
            QMessageBox.information(self, "Pre-Commit", f"Installed hook at {hook_path}")
        except Exception as exc:
            LOGGER.exception("Failed to install pre-commit hook")
            QMessageBox.critical(self, "Pre-Commit", str(exc))

    def export_report(self) -> None:
        if not self.current_repo:
            QMessageBox.information(self, "Export", "No repository selected.")
            return
        if not self.current_snapshot_id:
            QMessageBox.information(self, "Export", "No snapshot available.")
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Report",
            str(Path(self.current_repo.path) / "repo_report"),
            "Markdown (*.md);;JSON (*.json);;HTML (*.html)",
        )
        if not output_path:
            return
        snapshot = self.context.snapshots.get(self.current_snapshot_id)
        findings = self.context.findings.list_for_snapshot(self.current_snapshot_id)
        compare = self.compare_orchestrator.compare_latest(self.current_repo.id or 0)
        reviews = [dict(row) for row in self.context.reviews.list_for_snapshot(self.current_snapshot_id)]
        payload = self.report_generator.build_payload(self.current_repo, snapshot, findings, compare, reviews)
        target = Path(output_path)
        if target.suffix == ".json":
            self.report_generator.export_json(target, payload)
        elif target.suffix == ".html":
            self.report_generator.export_html(target, payload)
        else:
            if target.suffix != ".md":
                target = target.with_suffix(".md")
            self.report_generator.export_markdown(target, payload)
        LOGGER.info("Report exported to %s", target)
        QMessageBox.information(self, "Export", f"Report saved to {target}")

    def _start_log_refresh(self) -> None:
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.refresh_logs)
        self.log_timer.start(1500)
        self.refresh_logs()

    def refresh_logs(self) -> None:
        entries = self.log_handler.get_entries()
        new_text = "\n".join(entries[-300:])
        if new_text != self.logs_output.toPlainText():
            self.logs_output.setPlainText(new_text)
            cursor = self.logs_output.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.logs_output.setTextCursor(cursor)

    def _extract_risk(self, summary: str) -> str:
        marker = "risk score:"
        if marker not in summary:
            return "n/a"
        return summary.split(marker, 1)[1].split(".", 1)[0].strip()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.watch_service.stop()
        if hasattr(self, "log_timer"):
            self.log_timer.stop()
        super().closeEvent(event)


__all__ = ["MainWindow", "QApplication"]
