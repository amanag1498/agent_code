"""Evidence builders for LLM review and Phase 2 workflows."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ai_repo_agent.core.models import EmbeddingChunkRecord, FindingRecord, RepoSnapshotRecord, SymbolRecord


class EvidenceBuilder:
    """Build minimal evidence packages for LLM review."""

    HOTSPOT_TERMS = (
        "auth",
        "login",
        "token",
        "session",
        "secret",
        "config",
        "security",
        "permission",
        "admin",
        "middleware",
        "api",
        "route",
        "controller",
        "service",
        "db",
        "query",
        "model",
        "payment",
        "crypto",
    )
    SPECIALIZED_PASSES = {
        "auth": ("auth", "login", "token", "session", "jwt", "permission", "admin", "middleware"),
        "validation": ("validate", "validator", "schema", "sanitize", "input", "request", "payload", "form"),
        "dependency": ("package", "requirement", "dependency", "lock", "version", "manifest", "import"),
        "secrets_config": ("secret", "config", "env", "credential", "key", "password", "vault", "setting"),
    }

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

    def build_repo_analysis_batches(
        self,
        repo_root: Path,
        snapshot: RepoSnapshotRecord,
        symbols: list[SymbolRecord],
        chunks: list[EmbeddingChunkRecord],
        architecture_observations: list[str],
        dependency_summary: list[dict[str, Any]],
        focus_file_paths: set[str] | None = None,
        max_batches: int = 4,
        batch_size: int = 4,
    ) -> list[tuple[dict[str, Any], str]]:
        prioritized = self._prioritize_chunks(chunks, focus_file_paths or set())
        chunk_groups = self._build_module_clusters(prioritized, batch_size=batch_size, max_groups=max_batches)
        if not chunk_groups:
            chunk_groups = [[]]
        batches: list[tuple[dict[str, Any], str]] = []
        for index, group in enumerate(chunk_groups[:max_batches], start=1):
            file_paths = {chunk.file_path for chunk in group}
            grouped_symbols = [symbol for symbol in symbols if symbol.file_path in file_paths][:24]
            evidence = {
                "batch_context": {
                    "batch_number": index,
                    "batch_count": min(len(chunk_groups), max_batches),
                    "repo_root": str(repo_root),
                    "focus_files": sorted(file_paths),
                    "requested_focus_files": sorted(focus_file_paths or set())[:40],
                },
                "snapshot": {
                    "branch": snapshot.branch,
                    "commit_hash": snapshot.commit_hash,
                    "dirty_flag": snapshot.dirty_flag,
                    "diff_summary": snapshot.diff_summary,
                },
                "architecture_observations": architecture_observations[:6],
                "dependencies": dependency_summary[:10],
                "symbols": [
                    {
                        "file_path": symbol.file_path,
                        "symbol_name": symbol.symbol_name,
                        "symbol_kind": symbol.symbol_kind,
                        "line_start": symbol.line_start,
                        "line_end": symbol.line_end,
                    }
                    for symbol in grouped_symbols
                ],
                "code_chunks": [
                    {
                        "file_path": chunk.file_path,
                        "metadata": self._safe_metadata(chunk.metadata_json),
                        "chunk_text": chunk.chunk_text[:1600],
                    }
                    for chunk in group
                ],
            }
            evidence_hash = self._batch_cache_key(evidence)
            batches.append((evidence, evidence_hash))
        return batches

    def build_specialized_analysis_batches(
        self,
        repo_root: Path,
        snapshot: RepoSnapshotRecord,
        chunks: list[EmbeddingChunkRecord],
        dependency_summary: list[dict[str, Any]],
        focus_file_paths: set[str] | None = None,
    ) -> list[tuple[dict[str, Any], str]]:
        del repo_root
        prioritized = self._prioritize_chunks(chunks, focus_file_paths or set())
        results: list[tuple[dict[str, Any], str]] = []
        for focus_name, terms in self.SPECIALIZED_PASSES.items():
            relevant = [chunk for chunk in prioritized if self._matches_focus(chunk, terms)][:4]
            if focus_name == "dependency" and not relevant and dependency_summary:
                relevant = prioritized[:2]
            if not relevant and focus_name != "dependency":
                continue
            evidence = {
                "analysis_focus": focus_name,
                "snapshot": {
                    "branch": snapshot.branch,
                    "commit_hash": snapshot.commit_hash,
                    "dirty_flag": snapshot.dirty_flag,
                    "diff_summary": snapshot.diff_summary,
                },
                "dependencies": dependency_summary[:16],
                "focus_terms": list(terms),
                "code_chunks": [
                    {
                        "file_path": chunk.file_path,
                        "metadata": self._safe_metadata(chunk.metadata_json),
                        "chunk_text": chunk.chunk_text[:1600],
                    }
                    for chunk in relevant
                ],
            }
            evidence_hash = self._batch_cache_key(evidence)
            results.append((evidence, evidence_hash))
        return results

    def build_chat_evidence(
        self,
        question: str,
        chunks: list[EmbeddingChunkRecord],
        history: list[dict[str, str]],
    ) -> tuple[dict, str]:
        question_terms = self._question_terms(question)
        ranked = sorted(
            chunks,
            key=lambda chunk: self._chat_chunk_score(chunk, question_terms),
            reverse=True,
        )
        diversified = self._diversify_chunks(ranked, limit=8)
        evidence = {
            "question": question,
            "history": history[-6:],
            "retrieved_chunks": [
                {
                    "file_path": chunk.file_path,
                    "chunk_text": chunk.chunk_text[:1700],
                    "metadata": self._safe_metadata(chunk.metadata_json),
                }
                for chunk in diversified
            ],
        }
        evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode("utf-8")).hexdigest()
        return evidence, evidence_hash

    def build_patch_evidence(
        self,
        repo_root: Path,
        finding: FindingRecord,
        related_chunks: list[EmbeddingChunkRecord],
        related_symbols: list[SymbolRecord],
        patch_context: dict[str, Any],
    ) -> tuple[dict, str]:
        snippet = ""
        if finding.file_path:
            full_path = repo_root / finding.file_path
            if full_path.exists():
                lines = full_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                start = max((finding.line_start or 1) - 18, 1)
                end = min((finding.line_end or finding.line_start or 1) + 18, len(lines))
                snippet = "\n".join(
                    f"{index + 1}: {line}" for index, line in enumerate(lines[start - 1 : end], start=start - 1)
                )[:3200]
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
            "related_symbols": [
                {
                    "file_path": symbol.file_path,
                    "symbol_name": symbol.symbol_name,
                    "symbol_kind": symbol.symbol_kind,
                    "line_start": symbol.line_start,
                    "line_end": symbol.line_end,
                }
                for symbol in related_symbols[:12]
            ],
            "patch_context": patch_context,
        }
        evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode("utf-8")).hexdigest()
        return evidence, evidence_hash

    def _prioritize_chunks(self, chunks: list[EmbeddingChunkRecord], focus_file_paths: set[str]) -> list[EmbeddingChunkRecord]:
        return sorted(
            chunks,
            key=lambda chunk: (
                -self._chunk_priority_score(chunk, focus_file_paths),
                len(chunk.chunk_text),
                chunk.file_path,
            ),
        )

    def _chunk_priority_score(self, chunk: EmbeddingChunkRecord, focus_file_paths: set[str]) -> int:
        file_path = chunk.file_path.lower()
        metadata = self._safe_metadata(chunk.metadata_json)
        score = 0
        if chunk.file_path in focus_file_paths:
            score += 40
        for term in self.HOTSPOT_TERMS:
            if term in file_path:
                score += 6
            if term in chunk.chunk_text.lower():
                score += 2
        score += min(8, int(metadata.get("lines", 0)) // 25) if isinstance(metadata.get("lines"), int) else 0
        if "test" in file_path:
            score -= 6
        if "vendor" in file_path or "node_modules" in file_path:
            score -= 10
        return score

    def _build_module_clusters(
        self,
        chunks: list[EmbeddingChunkRecord],
        batch_size: int,
        max_groups: int,
    ) -> list[list[EmbeddingChunkRecord]]:
        buckets: dict[str, list[EmbeddingChunkRecord]] = {}
        for chunk in chunks:
            metadata = self._safe_metadata(chunk.metadata_json)
            directory = chunk.file_path.rsplit("/", 1)[0] if "/" in chunk.file_path else "root"
            imports = metadata.get("imports", [])
            dominant_import = imports[0] if imports else ""
            cluster_key = f"{directory}|{dominant_import}"
            buckets.setdefault(cluster_key, []).append(chunk)
        ranked_groups = sorted(
            buckets.values(),
            key=lambda group: sum(self._chunk_priority_score(chunk, set()) for chunk in group),
            reverse=True,
        )
        groups: list[list[EmbeddingChunkRecord]] = []
        for group in ranked_groups[:max_groups]:
            groups.append(group[:batch_size])
        if not groups:
            groups = [chunks[:batch_size]]
        return groups

    def _matches_focus(self, chunk: EmbeddingChunkRecord, terms: tuple[str, ...]) -> bool:
        haystack = f"{chunk.file_path}\n{chunk.chunk_text}\n{chunk.metadata_json}".lower()
        return any(term in haystack for term in terms)

    def _chat_chunk_score(self, chunk: EmbeddingChunkRecord, question_terms: set[str]) -> int:
        haystack = f"{chunk.file_path}\n{chunk.chunk_text}\n{chunk.metadata_json}".lower()
        metadata = self._safe_metadata(chunk.metadata_json)
        score = 0
        for term in question_terms:
            if term in chunk.file_path.lower():
                score += 9
            if term in haystack:
                score += 3
            if term in " ".join(metadata.get("imports", [])).lower():
                score += 5
            if term == str(metadata.get("symbol_name", "")).lower():
                score += 7
        if metadata.get("chunk_kind") in {"function", "method", "class"}:
            score += 4
        if "test" in chunk.file_path.lower():
            score -= 3
        return score

    def _diversify_chunks(self, chunks: list[EmbeddingChunkRecord], limit: int) -> list[EmbeddingChunkRecord]:
        selected: list[EmbeddingChunkRecord] = []
        seen_files: dict[str, int] = {}
        for chunk in chunks:
            count = seen_files.get(chunk.file_path, 0)
            if count >= 2:
                continue
            selected.append(chunk)
            seen_files[chunk.file_path] = count + 1
            if len(selected) >= limit:
                break
        return selected

    @staticmethod
    def _question_terms(question: str) -> set[str]:
        tokens = {token for token in re.findall(r"[a-zA-Z_]{3,}", question.lower()) if len(token) >= 3}
        return set(sorted(tokens))

    def _batch_cache_key(self, evidence: dict[str, Any]) -> str:
        chunk_signatures = [
            {
                "file_path": chunk["file_path"],
                "line_start": chunk["metadata"].get("line_start"),
                "line_end": chunk["metadata"].get("line_end"),
                "file_sha256": chunk["metadata"].get("file_sha256"),
            }
            for chunk in evidence.get("code_chunks", [])
        ]
        symbol_signatures = [
            {
                "file_path": symbol["file_path"],
                "symbol_name": symbol["symbol_name"],
                "symbol_kind": symbol["symbol_kind"],
                "line_start": symbol["line_start"],
                "line_end": symbol["line_end"],
            }
            for symbol in evidence.get("symbols", [])
        ]
        cache_payload = {
            "batch_context": evidence.get("batch_context", {}),
            "snapshot": evidence.get("snapshot", {}),
            "architecture_observations": evidence.get("architecture_observations", []),
            "dependencies": evidence.get("dependencies", []),
            "chunks": chunk_signatures,
            "symbols": symbol_signatures,
        }
        return hashlib.sha256(json.dumps(cache_payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_metadata(text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except Exception:
            return {}
