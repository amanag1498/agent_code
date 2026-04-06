"""Analyzer migration tests."""

from __future__ import annotations

import json

from ai_repo_agent.analysis.code_analysis import create_code_analyzer
from ai_repo_agent.analysis.diff import DiffService
from ai_repo_agent.analysis.symbols import SymbolIndexer
from ai_repo_agent.analysis.chunks import ChunkBuilder
from ai_repo_agent.core.enums import FindingStatus
from ai_repo_agent.core.models import AppSettings, DependencyRecord, FileInventoryItem, FindingRecord, SymbolRecord
from ai_repo_agent.db.database import connect_database
from ai_repo_agent.db.repositories import (
    DependencyStore,
    EmbeddingStore,
    FileStore,
    FindingStore,
    RepositoryStore,
    ReviewStore,
    ScanRunStore,
    SnapshotStore,
    SymbolStore,
)
from ai_repo_agent.services.scan_orchestrator import ScanOrchestrator


def test_symbol_extraction_legacy_backend(tmp_path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "import os\n\nclass Service:\n    def run(self):\n        return 1\n\ndef helper():\n    return 2\n",
        encoding="utf-8",
    )
    item = FileInventoryItem(
        path="sample.py",
        absolute_path=str(source),
        size=source.stat().st_size,
        sha256="abc",
        language="python",
        is_binary=False,
        lines=7,
    )
    analyzer = create_code_analyzer(AppSettings(analyzer_backend="legacy_ast", lsp_enabled=False))
    symbols = SymbolIndexer(analyzer).index(tmp_path, [item])
    names = {(symbol.symbol_name, symbol.symbol_kind) for symbol in symbols}
    assert ("Service", "class") in names
    assert ("helper", "function") in names


def test_chunk_builder_uses_structural_boundaries(tmp_path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        "import os\n\nclass User:\n    def __init__(self):\n        self.id = 1\n\n"
        "def make_user():\n    return User()\n",
        encoding="utf-8",
    )
    item = FileInventoryItem(
        path="module.py",
        absolute_path=str(source),
        size=source.stat().st_size,
        sha256="def",
        language="python",
        is_binary=False,
        lines=8,
    )
    analyzer = create_code_analyzer(AppSettings(analyzer_backend="legacy_ast", lsp_enabled=False))
    chunks = ChunkBuilder(analyzer).build(tmp_path, [item], max_lines=20)
    kinds = {chunk.metadata.get("chunk_kind") for chunk in chunks}
    assert "class" in kinds or "function" in kinds


def test_scan_pipeline_preserves_snapshot_and_memory(tmp_path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text(
        "class App:\n    def run(self):\n        return True\n",
        encoding="utf-8",
    )
    connection = connect_database(str(tmp_path / "scan.db"))
    settings = AppSettings(llm_provider="none", analyzer_backend="legacy_ast", lsp_enabled=False)
    orchestrator = ScanOrchestrator(
        RepositoryStore(connection),
        SnapshotStore(connection),
        FileStore(connection),
        DependencyStore(connection),
        SymbolStore(connection),
        EmbeddingStore(connection),
        FindingStore(connection),
        ReviewStore(connection),
        ScanRunStore(connection),
        settings,
    )
    result = orchestrator.scan(str(repo_dir))
    assert result.snapshot.id is not None
    stored_symbols = SymbolStore(connection).list_for_snapshot(result.snapshot.id or 0)
    stored_chunks = EmbeddingStore(connection).list_for_snapshot(result.snapshot.id or 0)
    assert stored_symbols
    assert stored_chunks


def test_diff_service_keeps_compare_contract_with_symbol_summary() -> None:
    diff_service = DiffService()
    current_findings = [
        FindingRecord(
            id=1,
            repo_snapshot_id=2,
            scanner_name="llm",
            rule_id="R1",
            title="Issue",
            description="desc",
            severity="medium",
            category="security",
            file_path="app.py",
            line_start=1,
            line_end=1,
            fingerprint="R1|app.py|1|Issue",
            raw_payload=json.dumps({}),
            status=FindingStatus.OPEN.value,
        )
    ]
    compare = diff_service.compare(
        repo_id=1,
        current_snapshot_id=2,
        previous_snapshot_id=1,
        current_findings=current_findings,
        previous_findings=[],
        current_dependencies=[DependencyRecord(id=None, snapshot_id=2, ecosystem="pip", name="requests", version="1", manifest_path="requirements.txt")],
        previous_dependencies=[],
        changed_files=["app.py"],
        current_symbols=[SymbolRecord(id=None, snapshot_id=2, file_path="app.py", symbol_name="run", symbol_kind="function", line_start=2, line_end=3)],
        previous_symbols=[],
    )
    assert compare.current_snapshot_id == 2
    assert "symbol additions" in compare.summary
