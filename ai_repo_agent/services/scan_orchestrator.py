"""Scan orchestration."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from ai_repo_agent.analysis.architecture import ArchitectureMapper
from ai_repo_agent.analysis.chunks import ChunkBuilder
from ai_repo_agent.analysis.code_analysis import create_code_analyzer
from ai_repo_agent.analysis.diff import DiffService
from ai_repo_agent.analysis.embeddings import LocalEmbeddingModel
from ai_repo_agent.analysis.risk import RiskScoringEngine
from ai_repo_agent.analysis.summary import SummaryBuilder
from ai_repo_agent.analysis.symbols import SymbolIndexer
from ai_repo_agent.core.enums import FindingStatus
from ai_repo_agent.core.models import (
    AppSettings,
    DependencyRecord,
    EmbeddingChunkRecord,
    EmbeddingVectorRecord,
    FileRecord,
    FileInventoryItem,
    FileVersionRecord,
    Finding,
    FindingRecord,
    RepoSnapshotRecord,
    RepositoryRecord,
    ScanResult,
    ScanRunRecord,
    SymbolRecord,
)
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
from ai_repo_agent.llm.factory import create_provider
from ai_repo_agent.llm.judge import RepoJudge
from ai_repo_agent.llm.provider import ProviderBase
from ai_repo_agent.llm.workflows import LLMFindingGenerator
from ai_repo_agent.repo.inventory import RepoFingerprintService
from ai_repo_agent.repo.loader import RepoLoader

LOGGER = logging.getLogger(__name__)


class ScanOrchestrator:
    """Run repo ingestion, local memory extraction, LLM findings, and persistence."""

    def __init__(
        self,
        repository_store: RepositoryStore,
        snapshot_store: SnapshotStore,
        file_store: FileStore,
        dependency_store: DependencyStore,
        symbol_store: SymbolStore,
        embedding_store: EmbeddingStore,
        finding_store: FindingStore,
        review_store: ReviewStore,
        scan_run_store: ScanRunStore,
        settings: AppSettings,
    ) -> None:
        self.repository_store = repository_store
        self.snapshot_store = snapshot_store
        self.file_store = file_store
        self.dependency_store = dependency_store
        self.symbol_store = symbol_store
        self.embedding_store = embedding_store
        self.finding_store = finding_store
        self.review_store = review_store
        self.scan_run_store = scan_run_store
        self.settings = settings
        self.loader = RepoLoader()
        self.fingerprint_service = RepoFingerprintService()
        self.risk_engine = RiskScoringEngine()
        self.diff_service = DiffService()
        self.summary_builder = SummaryBuilder()
        self.architecture_mapper = ArchitectureMapper()
        self.embedding_model = LocalEmbeddingModel()
        self.analyzer = create_code_analyzer(settings)
        self.symbol_indexer = SymbolIndexer(self.analyzer)
        self.chunk_builder = ChunkBuilder(self.analyzer)

    def scan(
        self,
        path: str,
        progress_callback: Callable[[str, int], None] | None = None,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> ScanResult:
        self._check_cancel(cancel_callback)
        self._progress(progress_callback, "Loading repository context", 5)
        LOGGER.info("Loading repository context for %s", path)
        repo_context = self.loader.load(path)
        fingerprint = self.fingerprint_service.fingerprint(repo_context.files)
        LOGGER.info(
            "Repository context loaded: files=%s languages=%s dependencies=%s git_repo=%s",
            len(repo_context.files),
            len(repo_context.languages),
            len(repo_context.dependencies),
            repo_context.git_state.is_git_repo,
        )
        repository = self.repository_store.upsert(
            RepositoryRecord(
                id=None,
                path=str(repo_context.path),
                name=repo_context.path.name,
                is_git_repo=repo_context.git_state.is_git_repo,
                fingerprint=fingerprint,
            )
        )
        previous_snapshot = self.snapshot_store.latest_for_repo(repository.id or 0)
        snapshot = self.snapshot_store.create(
            RepoSnapshotRecord(
                id=None,
                repo_id=repository.id or 0,
                created_at=datetime.utcnow().isoformat(timespec="seconds"),
                branch=repo_context.git_state.branch,
                commit_hash=repo_context.git_state.commit_hash,
                dirty_flag=repo_context.git_state.dirty,
                changed_files_count=len(repo_context.git_state.changed_files),
                diff_summary=repo_context.git_state.diff_summary,
                scan_metadata=json.dumps({"languages": repo_context.languages, "frameworks": repo_context.frameworks}),
                summary=repo_context.summary,
            )
        )
        self._progress(progress_callback, "Persisting file inventory", 18)
        self._persist_files(snapshot.id or 0, repository.id or 0, repo_context.files)
        LOGGER.info("Persisted file inventory for snapshot %s", snapshot.id)
        self._check_cancel(cancel_callback)
        changed_focus_paths = self._determine_focus_paths(
            previous_snapshot=previous_snapshot,
            current_snapshot=snapshot,
            repo_context=repo_context,
        )
        self._progress(progress_callback, "Persisting dependencies", 28)
        dep_records = [
            DependencyRecord(
                id=None,
                snapshot_id=snapshot.id or 0,
                ecosystem=dep.ecosystem,
                name=dep.name,
                version=dep.version,
                manifest_path=dep.manifest_path,
            )
            for dep in repo_context.dependencies
        ]
        self.dependency_store.replace_for_snapshot(snapshot.id or 0, dep_records)
        LOGGER.info("Persisted %s dependencies for snapshot %s", len(dep_records), snapshot.id)
        self._check_cancel(cancel_callback)

        self._progress(progress_callback, f"Indexing symbols via {self.analyzer.backend_name}", 40)
        symbols = self.symbol_indexer.index(repo_context.path, repo_context.files)
        self.symbol_store.replace_for_snapshot(
            snapshot.id or 0,
            [
                SymbolRecord(
                    id=None,
                    snapshot_id=snapshot.id or 0,
                    file_path=symbol.file_path,
                    symbol_name=symbol.symbol_name,
                    symbol_kind=symbol.symbol_kind,
                    line_start=symbol.line_start,
                    line_end=symbol.line_end,
                )
                for symbol in symbols
            ],
        )
        LOGGER.info("Persisted %s symbols for snapshot %s", len(symbols), snapshot.id)
        self._check_cancel(cancel_callback)

        self._progress(progress_callback, f"Building code memory via {self.analyzer.backend_name}", 52)
        chunks = self.chunk_builder.build(repo_context.path, repo_context.files, max_lines=self.settings.embedding_chunk_lines)
        stored_chunks = self.embedding_store.replace_for_snapshot(
            snapshot.id or 0,
            [
                EmbeddingChunkRecord(
                    id=None,
                    snapshot_id=snapshot.id or 0,
                    file_path=chunk.file_path,
                    chunk_text=chunk.chunk_text,
                    metadata_json=json.dumps(chunk.metadata),
                )
                for chunk in chunks
            ],
        )
        self.embedding_store.replace_vectors_for_snapshot(
            snapshot.id or 0,
            [
                self.embedding_model.build_vector_record(snapshot.id or 0, chunk)
                for chunk in stored_chunks
                if chunk.id is not None
            ],
        )
        LOGGER.info("Persisted %s code chunks for snapshot %s", len(chunks), snapshot.id)
        self._check_cancel(cancel_callback)

        architecture_observations = self.architecture_mapper.observe(repo_context.files)
        provider = self._provider()
        findings: list[Finding] = []
        stored_findings: list[FindingRecord] = []
        run_id = self.scan_run_store.create(
            ScanRunRecord(
                id=None,
                repo_id=repository.id or 0,
                snapshot_id=snapshot.id,
                started_at=datetime.utcnow().isoformat(timespec="seconds"),
                finished_at=None,
                status="running",
                scanner_name="llm-finding-generator",
                message="LLM analysis started",
            )
        )
        if provider:
            self._progress(progress_callback, f"Running {provider.provider_name} analysis", 64)
            LOGGER.info(
                "LLM provider configured (%s). Starting finding generation for snapshot %s",
                provider.provider_name,
                snapshot.id,
            )
            stored_symbols = self.symbol_store.list_for_snapshot(snapshot.id or 0)
            stored_chunks = self.embedding_store.list_for_snapshot(snapshot.id or 0)
            stored_vectors = self.embedding_store.list_vectors_for_snapshot(snapshot.id or 0)
            generator = LLMFindingGenerator(provider, self.review_store, self.settings.llm_max_findings_per_scan)
            try:
                generated, evidence_hash = generator.generate(
                    repo_root=repo_context.path,
                    snapshot=snapshot,
                    symbols=stored_symbols,
                    chunks=stored_chunks,
                    vectors=stored_vectors,
                    architecture_observations=architecture_observations,
                    dependency_summary=[asdict(dep) for dep in dep_records],
                    focus_file_paths=changed_focus_paths,
                    progress_callback=progress_callback,
                )
                findings = [
                    Finding(
                        scanner_name=provider.provider_name,
                        rule_id=item.rule_id,
                        title=item.title,
                        description=item.description,
                        severity=item.severity,
                        category=item.category,
                        file_path=item.file_path,
                        line_start=item.line_start,
                        line_end=item.line_end,
                        fingerprint=self._fingerprint(item),
                        raw_payload=item.model_dump(mode="json"),
                        status=FindingStatus.OPEN,
                        family_id=generator.family_id(item),
                        confidence=item.confidence,
                        framework_tags=item.framework_tags,
                        evidence_quality=item.evidence_quality,
                    )
                    for item in generated
                ]
                stored_findings = self.finding_store.add_many(
                    snapshot.id or 0,
                    [
                        FindingRecord(
                            id=None,
                            repo_snapshot_id=snapshot.id or 0,
                            scanner_name=provider.provider_name,
                            rule_id=finding.rule_id,
                            title=finding.title,
                            description=finding.description,
                            severity=finding.severity.value,
                            category=finding.category,
                            file_path=finding.file_path,
                            line_start=finding.line_start,
                            line_end=finding.line_end,
                            fingerprint=finding.fingerprint,
                            raw_payload=json.dumps(finding.raw_payload),
                            status=finding.status.value,
                            family_id=finding.family_id,
                            confidence=finding.confidence,
                            framework_tags_json=json.dumps(finding.framework_tags),
                            evidence_quality=finding.evidence_quality,
                        )
                        for finding in findings
                    ],
                )
                generator.persist_reviews(generated, stored_findings, evidence_hash, snapshot.id or 0)
                self.scan_run_store.update_status(
                    run_id,
                    "completed",
                    f"Generated {len(stored_findings)} LLM findings",
                    datetime.utcnow().isoformat(timespec="seconds"),
                )
                self._progress(progress_callback, "Persisted LLM findings", 80)
                LOGGER.info("LLM finding generation completed: findings=%s snapshot=%s", len(stored_findings), snapshot.id)
            except Exception as exc:
                LOGGER.warning("LLM finding generation failed: %s", exc)
                self.scan_run_store.update_status(
                    run_id,
                    "failed",
                    str(exc),
                    datetime.utcnow().isoformat(timespec="seconds"),
                )
        else:
            LOGGER.info("LLM provider not configured. Skipping finding generation for snapshot %s", snapshot.id)
            self.scan_run_store.update_status(
                run_id,
                "skipped",
                "LLM provider not configured",
                datetime.utcnow().isoformat(timespec="seconds"),
            )
            self._progress(progress_callback, "Skipping LLM stage", 74)

        self._progress(progress_callback, "Comparing with previous snapshot", 86)
        self._check_cancel(cancel_callback)
        previous_snapshot = self.snapshot_store.previous_for_repo(repository.id or 0, snapshot.id or 0)
        previous_findings = self.finding_store.list_for_snapshot(previous_snapshot.id) if previous_snapshot else []
        previous_dependencies = self.dependency_store.list_for_snapshot(previous_snapshot.id) if previous_snapshot else []
        compare_result = self.diff_service.compare(
            repo_id=repository.id or 0,
            current_snapshot_id=snapshot.id or 0,
            previous_snapshot_id=previous_snapshot.id if previous_snapshot else None,
            current_findings=stored_findings,
            previous_findings=previous_findings,
            current_dependencies=dep_records,
            previous_dependencies=previous_dependencies,
            changed_files=repo_context.git_state.changed_files,
            current_symbols=self.symbol_store.list_for_snapshot(snapshot.id or 0),
            previous_symbols=self.symbol_store.list_for_snapshot(previous_snapshot.id) if previous_snapshot else [],
        )
        self.finding_store.add_deltas(compare_result.deltas)
        risk_score = self.risk_engine.score(findings, repo_context.git_state, len(repo_context.dependencies))
        LOGGER.info(
            "Comparison completed for snapshot %s: deltas=%s risk_score=%s",
            snapshot.id,
            len(compare_result.deltas),
            risk_score,
        )
        if provider:
            try:
                self._progress(progress_callback, "Building repo-level review", 94)
                self._check_cancel(cancel_callback)
                repo_judge = RepoJudge(provider, self.review_store)
                repo_judge.review(snapshot, compare_result.summary, stored_findings[:5])
                LOGGER.info("Repo-level LLM review completed for snapshot %s", snapshot.id)
            except Exception as exc:
                LOGGER.warning("LLM repo review failed: %s", exc)
        snapshot.summary = self.summary_builder.scan_summary(len(stored_findings), risk_score, compare_result.summary)
        self.snapshot_store.connection.execute(
            "UPDATE repo_snapshots SET summary = ? WHERE id = ?",
            (snapshot.summary, snapshot.id),
        )
        self.snapshot_store.connection.commit()
        self._progress(progress_callback, "Finalizing snapshot", 100)
        return ScanResult(
            snapshot=snapshot,
            findings=findings,
            compare_result=compare_result,
            risk_score=risk_score,
            repo_summary=repo_context.summary,
        )

    def _persist_files(self, snapshot_id: int, repo_id: int, files) -> None:
        for item in files:
            file_id = self.file_store.upsert_file(
                FileRecord(
                    id=None,
                    repo_id=repo_id,
                    path=item.path,
                    size=item.size,
                    sha256=item.sha256,
                    language=item.language,
                    is_binary=item.is_binary,
                )
            )
            self.file_store.add_version(
                FileVersionRecord(
                    id=None,
                    file_id=file_id,
                    snapshot_id=snapshot_id,
                    sha256=item.sha256,
                    lines=item.lines,
                )
            )

    def _provider(self) -> ProviderBase | None:
        return create_provider(self.settings)

    def _determine_focus_paths(
        self,
        previous_snapshot: RepoSnapshotRecord | None,
        current_snapshot: RepoSnapshotRecord,
        repo_context,
    ) -> set[str]:
        focus_paths = set(repo_context.git_state.changed_files)
        if previous_snapshot and previous_snapshot.id and current_snapshot.id:
            focus_paths.update(
                self.file_store.changed_paths_between_snapshots(previous_snapshot.id, current_snapshot.id)
            )
        if not focus_paths:
            focus_paths.update(self._heuristic_focus_paths(repo_context.files))
        return focus_paths

    @staticmethod
    def _heuristic_focus_paths(files) -> set[str]:
        ranked = []
        for item in files:
            path = item.path.lower()
            score = 0
            for term in ("auth", "api", "route", "controller", "service", "config", "secret", "db", "query"):
                if term in path:
                    score += 5
            if "test" in path:
                score -= 4
            ranked.append((score, item.path))
        ranked.sort(reverse=True)
        return {path for score, path in ranked[:15] if score > 0}

    @staticmethod
    def _progress(progress_callback: Callable[[str, int], None] | None, stage: str, progress: int) -> None:
        if progress_callback:
            progress_callback(stage, progress)

    @staticmethod
    def _check_cancel(cancel_callback: Callable[[], bool] | None) -> None:
        if cancel_callback and cancel_callback():
            raise RuntimeError("Scan canceled by user.")

    @staticmethod
    def _fingerprint(item) -> str:
        return f"{item.rule_id}|{item.file_path}|{item.line_start}|{item.title}"

    def patch_context_for_file(self, repo_root: str, file_path: str, line_start: int | None, line_end: int | None) -> dict:
        full_path = Path(repo_root) / file_path
        if not full_path.exists():
            return {}
        try:
            text = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return {}
        file_item = FileInventoryItem(
            path=file_path,
            absolute_path=str(full_path),
            size=full_path.stat().st_size,
            sha256="",
            language=self._infer_language(file_path),
            is_binary=False,
            lines=len(text.splitlines()),
        )
        return self.analyzer.get_patch_context(Path(repo_root), file_item, line_start, line_end)

    @staticmethod
    def _infer_language(file_path: str) -> str:
        suffix = Path(file_path).suffix.lower()
        return {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".c": "c",
            ".cc": "cpp",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }.get(suffix, "text")
