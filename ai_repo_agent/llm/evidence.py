"""Evidence builders for LLM review and Phase 2 workflows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai_repo_agent.core.models import EmbeddingChunkRecord, FindingRecord, RepoSnapshotRecord, SymbolRecord


class EvidenceBuilder:
    """Build minimal evidence packages for LLM review."""

    def build_finding_evidence(
        self,
        repo_root: Path,
        finding: FindingRecord,
        previous_related: list[FindingRecord],
        diff_summary: str,
        architecture_observations: list[str],
    ) -> tuple[dict, str]:
        snippet = ""
        if finding.file_path:
            full_path = repo_root / finding.file_path
            if full_path.exists():
                lines = full_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                start = max((finding.line_start or 1) - 3, 0)
                end = min((finding.line_end or finding.line_start or 1) + 2, len(lines))
                snippet = "\n".join(f"{index + 1}: {line}" for index, line in enumerate(lines[start:end], start=start))
        evidence = {
            "finding": {
                "scanner_name": finding.scanner_name,
                "rule_id": finding.rule_id,
                "title": finding.title,
                "description": finding.description,
                "severity": finding.severity,
                "category": finding.category,
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
            },
            "code_snippet": snippet,
            "diff_summary": diff_summary,
            "previous_related_findings": [
                {"title": item.title, "severity": item.severity, "status": item.status} for item in previous_related[:3]
            ],
            "architecture_observations": architecture_observations[:5],
        }
        evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode("utf-8")).hexdigest()
        return evidence, evidence_hash

    def build_snapshot_evidence(
        self,
        snapshot: RepoSnapshotRecord,
        compare_summary: str,
        top_findings: list[FindingRecord],
    ) -> tuple[dict, str]:
        evidence = {
            "snapshot": {
                "branch": snapshot.branch,
                "commit_hash": snapshot.commit_hash,
                "dirty_flag": snapshot.dirty_flag,
                "summary": snapshot.summary,
            },
            "compare_summary": compare_summary,
            "top_findings": [
                {"title": finding.title, "severity": finding.severity, "category": finding.category} for finding in top_findings[:5]
            ],
        }
        evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode("utf-8")).hexdigest()
        return evidence, evidence_hash

    def build_repo_analysis_evidence(
        self,
        repo_root: Path,
        snapshot: RepoSnapshotRecord,
        symbols: list[SymbolRecord],
        chunks: list[EmbeddingChunkRecord],
        architecture_observations: list[str],
        dependency_summary: list[dict],
        max_chunks: int = 10,
    ) -> tuple[dict, str]:
        del repo_root
        prioritized_chunks = sorted(
            chunks,
            key=lambda chunk: (
                "auth" not in chunk.file_path.lower(),
                "security" not in chunk.file_path.lower(),
                "config" not in chunk.file_path.lower(),
            ),
        )[:max_chunks]
        evidence = {
            "snapshot": {
                "branch": snapshot.branch,
                "commit_hash": snapshot.commit_hash,
                "dirty_flag": snapshot.dirty_flag,
                "diff_summary": snapshot.diff_summary,
            },
            "architecture_observations": architecture_observations[:5],
            "dependencies": dependency_summary[:10],
            "symbols": [
                {
                    "file_path": symbol.file_path,
                    "symbol_name": symbol.symbol_name,
                    "symbol_kind": symbol.symbol_kind,
                    "line_start": symbol.line_start,
                    "line_end": symbol.line_end,
                }
                for symbol in symbols[:35]
            ],
            "code_chunks": [
                {
                    "file_path": chunk.file_path,
                    "metadata": json.loads(chunk.metadata_json),
                    "chunk_text": chunk.chunk_text[:1600],
                }
                for chunk in prioritized_chunks
            ],
        }
        evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode("utf-8")).hexdigest()
        return evidence, evidence_hash

    def build_chat_evidence(
        self,
        question: str,
        chunks: list[EmbeddingChunkRecord],
        history: list[dict[str, str]],
    ) -> tuple[dict, str]:
        evidence = {
            "question": question,
            "history": history[-4:],
            "retrieved_chunks": [
                {
                    "file_path": chunk.file_path,
                    "chunk_text": chunk.chunk_text[:1400],
                    "metadata": json.loads(chunk.metadata_json),
                }
                for chunk in chunks[:5]
            ],
        }
        evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode("utf-8")).hexdigest()
        return evidence, evidence_hash

    def build_patch_evidence(
        self,
        repo_root: Path,
        finding: FindingRecord,
        related_chunks: list[EmbeddingChunkRecord],
    ) -> tuple[dict, str]:
        snippet = ""
        if finding.file_path:
            full_path = repo_root / finding.file_path
            if full_path.exists():
                snippet = full_path.read_text(encoding="utf-8", errors="ignore")[:2200]
        evidence = {
            "finding": {
                "title": finding.title,
                "description": finding.description,
                "severity": finding.severity,
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
            },
            "file_snippet": snippet,
            "related_chunks": [
                {
                    "file_path": chunk.file_path,
                    "chunk_text": chunk.chunk_text[:1200],
                    "metadata": json.loads(chunk.metadata_json),
                }
                for chunk in related_chunks[:4]
            ],
        }
        evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode("utf-8")).hexdigest()
        return evidence, evidence_hash
