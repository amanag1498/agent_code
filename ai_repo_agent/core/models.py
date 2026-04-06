"""Shared data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ai_repo_agent.core.enums import DeltaType, FindingStatus, ReviewTargetType, Severity, SeverityOverride, Verdict


@dataclass(slots=True)
class RepositoryRecord:
    id: int | None
    path: str
    name: str
    is_git_repo: bool
    fingerprint: str
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class RepoSnapshotRecord:
    id: int | None
    repo_id: int
    created_at: str
    branch: str | None
    commit_hash: str | None
    dirty_flag: bool
    changed_files_count: int
    diff_summary: str
    scan_metadata: str
    summary: str


@dataclass(slots=True)
class FileRecord:
    id: int | None
    repo_id: int
    path: str
    size: int
    sha256: str
    language: str
    is_binary: bool


@dataclass(slots=True)
class FileVersionRecord:
    id: int | None
    file_id: int
    snapshot_id: int
    sha256: str
    lines: int


@dataclass(slots=True)
class DependencyRecord:
    id: int | None
    snapshot_id: int
    ecosystem: str
    name: str
    version: str | None
    manifest_path: str


@dataclass(slots=True)
class FindingRecord:
    id: int | None
    repo_snapshot_id: int
    scanner_name: str
    rule_id: str
    title: str
    description: str
    severity: str
    category: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    fingerprint: str
    raw_payload: str
    status: str = FindingStatus.OPEN.value
    family_id: str = ""
    confidence: float = 0.0
    framework_tags_json: str = "[]"
    evidence_quality: float = 0.0


@dataclass(slots=True)
class SymbolRecord:
    id: int | None
    snapshot_id: int
    file_path: str
    symbol_name: str
    symbol_kind: str
    line_start: int | None
    line_end: int | None


@dataclass(slots=True)
class EmbeddingChunkRecord:
    id: int | None
    snapshot_id: int
    file_path: str
    chunk_text: str
    metadata_json: str


@dataclass(slots=True)
class EmbeddingVectorRecord:
    id: int | None
    snapshot_id: int
    chunk_id: int
    file_path: str
    vector_json: str
    vector_model: str
    content_hash: str


@dataclass(slots=True)
class RetrievalHit:
    chunk: "EmbeddingChunkRecord"
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FindingDeltaRecord:
    id: int | None
    repo_id: int
    previous_finding_id: int | None
    current_finding_id: int | None
    delta_type: str
    summary: str


@dataclass(slots=True)
class ScanRunRecord:
    id: int | None
    repo_id: int
    snapshot_id: int | None
    started_at: str
    finished_at: str | None
    status: str
    scanner_name: str
    message: str


@dataclass(slots=True)
class GitState:
    is_git_repo: bool
    branch: str | None = None
    commit_hash: str | None = None
    dirty: bool = False
    changed_files: list[str] = field(default_factory=list)
    diff_summary: str = ""


@dataclass(slots=True)
class RepoContext:
    path: Path
    git_state: GitState
    files: list["FileInventoryItem"]
    languages: dict[str, int]
    frameworks: list[str]
    dependencies: list["DependencyDescriptor"]
    summary: str


@dataclass(slots=True)
class FileInventoryItem:
    path: str
    absolute_path: str
    size: int
    sha256: str
    language: str
    is_binary: bool
    lines: int


@dataclass(slots=True)
class DependencyDescriptor:
    ecosystem: str
    name: str
    version: str | None
    manifest_path: str


@dataclass(slots=True)
class Finding:
    scanner_name: str
    rule_id: str
    title: str
    description: str
    severity: Severity
    category: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    fingerprint: str
    raw_payload: dict[str, Any]
    status: FindingStatus = FindingStatus.OPEN
    family_id: str = ""
    confidence: float = 0.0
    framework_tags: list[str] = field(default_factory=list)
    evidence_quality: float = 0.0


@dataclass(slots=True)
class SymbolDescriptor:
    file_path: str
    symbol_name: str
    symbol_kind: str
    line_start: int | None
    line_end: int | None


@dataclass(slots=True)
class ChunkDescriptor:
    file_path: str
    chunk_text: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class CodeUnitDescriptor:
    file_path: str
    unit_name: str | None
    unit_kind: str
    line_start: int
    line_end: int
    imports: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    parent_name: str | None = None
    semantic: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SemanticReferenceDescriptor:
    file_path: str
    symbol_name: str | None
    relation: str
    line_start: int | None
    line_end: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FileStructureDescriptor:
    file_path: str
    language: str
    symbols: list["SymbolDescriptor"]
    imports: list[str]
    comments: list[str]
    code_units: list["CodeUnitDescriptor"]
    semantic_references: list["SemanticReferenceDescriptor"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CompareResult:
    previous_snapshot_id: int | None
    current_snapshot_id: int
    deltas: list[FindingDeltaRecord]
    changed_files: list[str]
    changed_dependencies: list[str]
    summary: str
    risk_delta: float
    semantic_summaries: list[str] = field(default_factory=list)
    architectural_drift: list[str] = field(default_factory=list)
    trend_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScanResult:
    snapshot: RepoSnapshotRecord
    findings: list[Finding]
    compare_result: CompareResult | None
    risk_score: float
    repo_summary: str


class FindingReview(BaseModel):
    """Structured LLM review for an individual finding."""

    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    severity_override: SeverityOverride
    impact_summary: str
    reasoning_summary: str
    remediation_summary: str
    related_change_risk: str
    needs_human_review: bool


class DiffReview(BaseModel):
    """Structured LLM review for changed code."""

    confidence: float = Field(ge=0.0, le=1.0)
    risk_increased: bool
    reasoning_summary: str
    suspicious_changes: list[str]
    reintroduction_risk: str
    needs_human_review: bool


class RepoReview(BaseModel):
    """Structured LLM review for repo-level prioritization."""

    confidence: float = Field(ge=0.0, le=1.0)
    top_risks: list[str]
    release_readiness_summary: str
    prioritized_remediation: list[str]
    needs_human_review: bool


class GeneratedFinding(BaseModel):
    """Structured LLM-generated finding."""

    rule_id: str
    title: str
    description: str
    severity: Severity
    category: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    severity_override: SeverityOverride
    impact_summary: str
    reasoning_summary: str
    remediation_summary: str
    related_change_risk: str
    needs_human_review: bool
    framework_tags: list[str] = Field(default_factory=list)
    evidence_quality: float = Field(default=0.0, ge=0.0, le=1.0)


class PatchAlternative(BaseModel):
    """Alternative remediation strategy for a finding."""

    label: str
    summary: str
    suggested_diff: str


class FindingBatch(BaseModel):
    """Structured LLM-generated batch of findings."""

    findings: list[GeneratedFinding]


class RepoChatResponse(BaseModel):
    """Structured repo chat response."""

    answer: str
    cited_files: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human_review: bool


class PatchSuggestion(BaseModel):
    """Structured patch suggestion."""

    summary: str
    rationale: str
    suggested_diff: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human_review: bool
    alternatives: list[PatchAlternative] = Field(default_factory=list)
    validation_status: str = "not_run"
    validation_notes: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class LLMReviewRecord:
    id: int | None
    target_type: ReviewTargetType
    finding_id: int | None
    snapshot_id: int | None
    model_name: str
    prompt_version: str
    verdict: str
    confidence: float
    severity_override: str
    reasoning_summary: str
    remediation_summary: str
    evidence_hash: str
    raw_response: str
    created_at: str


@dataclass(slots=True)
class ChatSessionRecord:
    id: int | None
    repo_id: int
    title: str
    created_at: str


@dataclass(slots=True)
class ChatMessageRecord:
    id: int | None
    session_id: int
    role: str
    content: str
    created_at: str


@dataclass(slots=True)
class PatchSuggestionRecord:
    id: int | None
    snapshot_id: int
    finding_id: int | None
    summary: str
    rationale: str
    suggested_diff: str
    confidence: float
    created_at: str
    alternatives_json: str = "[]"
    validation_json: str = "{}"


@dataclass(slots=True)
class AppSettings:
    database_path: str = "ai_repo_analyst.db"
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_model: str = "gemini-2.5-flash"
    llm_base_url: str = ""
    analyzer_backend: str = "hybrid"
    lsp_enabled: bool = True
    llm_timeout_seconds: int = 60
    llm_retry_count: int = 2
    llm_max_findings_per_scan: int = 25
    embedding_chunk_lines: int = 80
    watch_mode_enabled: bool = False
    logging_level: str = "INFO"
    scan_worker_limit: int = 2
    snapshot_retention_count: int = 12

    @staticmethod
    def now_iso() -> str:
        return datetime.utcnow().isoformat(timespec="seconds")
