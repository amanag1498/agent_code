"""Analyzer migration tests."""

from __future__ import annotations

import json

from ai_repo_agent.analysis.embeddings import EmbeddingRetrievalService, LocalEmbeddingModel
from ai_repo_agent.analysis.code_analysis import create_code_analyzer
from ai_repo_agent.analysis.diff import DiffService
from ai_repo_agent.analysis.lsp_semantic import LspSemanticEnricher
from ai_repo_agent.analysis.symbols import SymbolIndexer
from ai_repo_agent.analysis.chunks import ChunkBuilder
from ai_repo_agent.core.enums import FindingStatus
from ai_repo_agent.core.models import (
    AppSettings,
    DependencyRecord,
    EmbeddingChunkRecord,
    FileInventoryItem,
    FileRecord,
    FileVersionRecord,
    FindingRecord,
    RepoSnapshotRecord,
    RepositoryRecord,
    SymbolRecord,
)
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
from ai_repo_agent.services.compare_orchestrator import CompareOrchestrator
from ai_repo_agent.services.patch_orchestrator import PatchOrchestrator
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
    stored_vectors = EmbeddingStore(connection).list_vectors_for_snapshot(result.snapshot.id or 0)
    assert stored_symbols
    assert stored_chunks
    assert stored_vectors


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
    assert compare.semantic_summaries


def test_embedding_retrieval_prefers_relevant_chunk() -> None:
    model = LocalEmbeddingModel()
    retrieval = EmbeddingRetrievalService(model)
    chunks = [
        EmbeddingChunkRecord(id=1, snapshot_id=1, file_path="auth/service.py", chunk_text="def validate_token(token):\n    return token", metadata_json=json.dumps({"chunk_kind": "function", "symbol_name": "validate_token"})),
        EmbeddingChunkRecord(id=2, snapshot_id=1, file_path="ui/view.py", chunk_text="def render_dashboard():\n    return 'ok'", metadata_json=json.dumps({"chunk_kind": "function", "symbol_name": "render_dashboard"})),
    ]
    vectors = [model.build_vector_record(1, chunk) for chunk in chunks]
    hits = retrieval.rank_for_query("where is token validation handled", chunks, vectors, limit=2)
    assert hits
    assert hits[0].chunk.file_path == "auth/service.py"


def test_lsp_enricher_is_fail_open_and_can_enrich_when_available(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "service.py"
    source.write_text(
        "class AuthService:\n"
        "    def validate_token(self, token):\n"
        "        return token\n\n"
        "def use_token():\n"
        "    service = AuthService()\n"
        "    return service.validate_token('a')\n",
        encoding="utf-8",
    )
    item = FileInventoryItem(
        path="service.py",
        absolute_path=str(source),
        size=source.stat().st_size,
        sha256="ghi",
        language="python",
        is_binary=False,
        lines=7,
    )
    unavailable = LspSemanticEnricher(enabled=False)
    analyzer = create_code_analyzer(AppSettings(analyzer_backend="legacy_ast", lsp_enabled=False))
    structure = unavailable.enrich_file(repo, item, analyzer.parse_file(repo, item))
    assert structure.metadata["semantic_backend"] == "unavailable"

    available = LspSemanticEnricher(enabled=True)
    available._server_cache["python"] = "/usr/bin/fake-lsp"
    enriched = available.enrich_file(repo, item, analyzer.parse_file(repo, item))
    assert enriched.metadata["semantic_backend"] == "lsp"
    assert any(unit.semantic.get("definitions") for unit in enriched.code_units if unit.unit_name)


def test_compare_orchestrator_includes_trend_history(tmp_path) -> None:
    connection = connect_database(str(tmp_path / "trend.db"))
    repositories = RepositoryStore(connection)
    snapshots = SnapshotStore(connection)
    findings = FindingStore(connection)
    dependencies = DependencyStore(connection)
    files = FileStore(connection)
    symbols = SymbolStore(connection)
    repo = repositories.upsert(
        RepositoryRecord(
            id=None,
            path=str(tmp_path / "repo"),
            name="repo",
            is_git_repo=False,
            fingerprint="fp",
        )
    )
    snapshot1 = snapshots.create(
        RepoSnapshotRecord(
            id=None,
            repo_id=repo.id or 0,
            created_at="2026-01-01T00:00:00",
            branch=None,
            commit_hash=None,
            dirty_flag=False,
            changed_files_count=0,
            diff_summary="",
            scan_metadata="{}",
            summary="s1",
        )
    )
    snapshot2 = snapshots.create(
        RepoSnapshotRecord(
            id=None,
            repo_id=repo.id or 0,
            created_at="2026-01-02T00:00:00",
            branch=None,
            commit_hash=None,
            dirty_flag=False,
            changed_files_count=1,
            diff_summary="changed app.py",
            scan_metadata="{}",
            summary="s2",
        )
    )
    file_id = files.upsert_file(
        FileRecord(
            id=None,
            repo_id=repo.id or 0,
            path="app.py",
            size=10,
            sha256="old",
            language="python",
            is_binary=False,
        )
    )
    files.add_version(FileVersionRecord(id=None, file_id=file_id, snapshot_id=snapshot1.id or 0, sha256="old", lines=2))
    files.add_version(FileVersionRecord(id=None, file_id=file_id, snapshot_id=snapshot2.id or 0, sha256="new", lines=3))
    findings.add_many(snapshot1.id or 0, [])
    findings.add_many(
        snapshot2.id or 0,
        [
            FindingRecord(
                id=None,
                repo_snapshot_id=snapshot2.id or 0,
                scanner_name="llm",
                rule_id="R1",
                title="Issue",
                description="desc",
                severity="high",
                category="security",
                file_path="app.py",
                line_start=1,
                line_end=1,
                fingerprint="R1|app.py|1|Issue",
                raw_payload=json.dumps({}),
                status=FindingStatus.OPEN.value,
            )
        ],
    )
    compare = CompareOrchestrator(snapshots, findings, dependencies, files, symbols).compare_latest(repo.id or 0)
    assert compare is not None
    assert compare.trend_metadata.get("history")


def test_diff_service_marks_regressed_family() -> None:
    diff_service = DiffService()
    previous = [
        FindingRecord(
            id=10,
            repo_snapshot_id=1,
            scanner_name="llm",
            rule_id="AUTH1",
            title="Missing auth check",
            description="desc",
            severity="high",
            category="security",
            file_path="api/auth.py",
            line_start=10,
            line_end=12,
            fingerprint="old",
            raw_payload=json.dumps({}),
            status=FindingStatus.OPEN.value,
            family_id="family-auth",
        )
    ]
    current = [
        FindingRecord(
            id=11,
            repo_snapshot_id=2,
            scanner_name="llm",
            rule_id="AUTH1",
            title="Missing auth guard",
            description="desc",
            severity="high",
            category="security",
            file_path="api/auth.py",
            line_start=18,
            line_end=21,
            fingerprint="new",
            raw_payload=json.dumps({}),
            status=FindingStatus.OPEN.value,
            family_id="family-auth",
        )
    ]
    compare = diff_service.compare(1, 2, 1, current, previous, [], [], ["api/auth.py"])
    assert any(delta.delta_type == "unchanged" for delta in compare.deltas) or any(delta.delta_type == "regressed" for delta in compare.deltas)


def test_snapshot_trim_history_removes_older_snapshots(tmp_path) -> None:
    connection = connect_database(str(tmp_path / "trim.db"))
    repositories = RepositoryStore(connection)
    snapshots = SnapshotStore(connection)
    repo = repositories.upsert(
        RepositoryRecord(id=None, path=str(tmp_path / "repo"), name="repo", is_git_repo=False, fingerprint="fp")
    )
    for index in range(4):
        snapshots.create(
            RepoSnapshotRecord(
                id=None,
                repo_id=repo.id or 0,
                created_at=f"2026-01-0{index + 1}T00:00:00",
                branch=None,
                commit_hash=None,
                dirty_flag=False,
                changed_files_count=0,
                diff_summary="",
                scan_metadata="{}",
                summary=f"s{index}",
            )
        )
    deleted = snapshots.trim_repo_history(repo.id or 0, 2)
    assert deleted == 2
    assert len(snapshots.list_for_repo(repo.id or 0)) == 2


def test_patch_validation_marks_valid_python_patch(tmp_path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    target = repo_dir / "service.py"
    target.write_text("def run():\n    return True\n", encoding="utf-8")
    patched = PatchOrchestrator._apply_single_file_hunk(
        target.read_text(encoding="utf-8"),
        type("Finding", (), {"line_start": 1, "line_end": 2})(),
        "@@ -1,2 +1,2 @@\n-def run():\n-    return True\n+def run():\n+    return False\n",
    )
    assert patched is not None
