"""Structured LLM workflows for findings, repo chat, and patch suggestions."""

from __future__ import annotations

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from ai_repo_agent.core.enums import ReviewTargetType
from ai_repo_agent.core.models import (
    EmbeddingChunkRecord,
    EmbeddingVectorRecord,
    RetrievalHit,
    FindingBatch,
    FindingRecord,
    GeneratedFinding,
    LLMReviewRecord,
    PatchSuggestion,
    PatchSuggestionRecord,
    RepoChatResponse,
    RepoSnapshotRecord,
    SymbolRecord,
)
from ai_repo_agent.db.repositories import PatchSuggestionStore, ReviewStore
from ai_repo_agent.llm.evidence import EvidenceBuilder
from ai_repo_agent.llm.prompts import PROMPT_VERSION, PromptBuilder
from ai_repo_agent.llm.provider import ProviderBase


class LLMFindingGenerator:
    """Generate normalized findings directly from repository evidence."""

    def __init__(self, provider: ProviderBase, review_store: ReviewStore, max_findings: int = 20) -> None:
        self.provider = provider
        self.review_store = review_store
        self.max_findings = max_findings
        self.evidence_builder = EvidenceBuilder()
        self.prompt_builder = PromptBuilder()

    def generate(
        self,
        repo_root: Path,
        snapshot: RepoSnapshotRecord,
        symbols: list[SymbolRecord],
        chunks: list[EmbeddingChunkRecord],
        vectors: list[EmbeddingVectorRecord],
        architecture_observations: list[str],
        dependency_summary: list[dict],
        focus_file_paths: set[str] | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> tuple[list[GeneratedFinding], str]:
        scan_metadata = self._scan_metadata(snapshot)
        evidence_batches = self.evidence_builder.build_repo_analysis_batches(
            repo_root=repo_root,
            snapshot=snapshot,
            symbols=symbols,
            chunks=chunks,
            vectors=vectors,
            architecture_observations=architecture_observations,
            dependency_summary=dependency_summary,
            focus_file_paths=focus_file_paths,
            frameworks=scan_metadata.get("frameworks", []),
            max_batches=5,
            batch_size=4,
        )
        specialized_batches = self.evidence_builder.build_specialized_analysis_batches(
            repo_root=repo_root,
            snapshot=snapshot,
            chunks=chunks,
            vectors=vectors,
            dependency_summary=dependency_summary,
            focus_file_paths=focus_file_paths,
            frameworks=scan_metadata.get("frameworks", []),
        )
        combined_batches = [(evidence, evidence_hash, "general") for evidence, evidence_hash in evidence_batches]
        combined_batches.extend((evidence, evidence_hash, "specialized") for evidence, evidence_hash in specialized_batches)
        aggregated: list[GeneratedFinding] = []
        evidence_hashes: list[str] = []
        seen: set[str] = set()
        max_per_batch = max(4, min(8, max(6, self.max_findings // 2)))
        prepared_batches: list[tuple[int, dict, str, FindingBatch | None]] = []
        for index, (evidence, evidence_hash, mode) in enumerate(combined_batches, start=1):
            prompt = (
                self.prompt_builder.specialized_finding_generation_prompt(evidence, max_per_batch)
                if mode == "specialized"
                else self.prompt_builder.finding_generation_prompt(evidence, max_per_batch)
            )
            cached = self.review_store.get_cache(evidence_hash)
            if cached:
                prepared_batches.append((index, evidence, evidence_hash, FindingBatch.model_validate(cached)))
            else:
                prepared_batches.append((index, {"prompt": prompt, "evidence": evidence}, evidence_hash, None))

        uncached = [item for item in prepared_batches if item[3] is None]
        if uncached:
            max_workers = min(3, len(uncached))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(self.provider.generate_structured, item[1]["prompt"], FindingBatch): (item[0], item[2])
                    for item in uncached
                }
                completed = 0
                results_by_hash: dict[str, FindingBatch] = {}
                for future in as_completed(future_map):
                    batch_index, evidence_hash = future_map[future]
                    batch = future.result()
                    results_by_hash[evidence_hash] = batch
                    self.review_store.set_cache(evidence_hash, batch.model_dump(mode="json"))
                    completed += 1
                    if progress_callback:
                        progress_callback(
                            f"Completed LLM batch {batch_index}/{len(combined_batches)}",
                            64 + int(completed * 14 / max(1, len(combined_batches))),
                        )
            prepared_batches = [
                (index, payload, evidence_hash, batch if batch is not None else results_by_hash[evidence_hash])
                for index, payload, evidence_hash, batch in prepared_batches
            ]

        for index, _payload, evidence_hash, batch in sorted(prepared_batches, key=lambda item: item[0]):
            evidence_hashes.append(evidence_hash)
            if progress_callback:
                progress_callback(
                    f"Consolidating batch {index}/{len(combined_batches)}",
                    64 + int(index * 14 / max(1, len(combined_batches))),
                )
            for finding in self._dedupe_and_rank(self._calibrate_findings(batch.findings if batch else [], scan_metadata)):
                dedupe_key = f"{finding.rule_id}|{finding.file_path}|{finding.line_start}|{finding.title}"
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                aggregated.append(finding)
                if len(aggregated) >= self.max_findings:
                    break
            if len(aggregated) >= self.max_findings:
                break
        combined_hash = "|".join(evidence_hashes) if evidence_hashes else "empty"
        return aggregated[: self.max_findings], combined_hash

    def persist_reviews(self, generated: list[GeneratedFinding], stored_findings: list[FindingRecord], evidence_hash: str, snapshot_id: int) -> None:
        lookup = {f"{finding.rule_id}|{finding.file_path}|{finding.line_start}|{finding.title}": finding for finding in stored_findings}
        for generated_finding in generated:
            key = (
                f"{generated_finding.rule_id}|{generated_finding.file_path}|"
                f"{generated_finding.line_start}|{generated_finding.title}"
            )
            finding = lookup.get(key)
            self.review_store.save_review(
                LLMReviewRecord(
                    id=None,
                    target_type=ReviewTargetType.FINDING,
                    finding_id=finding.id if finding else None,
                    snapshot_id=snapshot_id,
                    model_name=getattr(self.provider, "model_name", "unknown"),
                    prompt_version=PROMPT_VERSION,
                    verdict=generated_finding.verdict.value,
                    confidence=generated_finding.confidence,
                    severity_override=generated_finding.severity_override.value,
                    reasoning_summary=generated_finding.reasoning_summary,
                    remediation_summary=generated_finding.remediation_summary,
                    evidence_hash=evidence_hash,
                    raw_response=json.dumps(generated_finding.model_dump(mode="json")),
                    created_at=datetime.utcnow().isoformat(timespec="seconds"),
                )
            )

    @staticmethod
    def _dedupe_and_rank(findings: list[GeneratedFinding]) -> list[GeneratedFinding]:
        severity_rank = {
            "critical": 5,
            "high": 4,
            "medium": 3,
            "low": 2,
            "info": 1,
            "unknown": 0,
        }
        return sorted(
            findings,
            key=lambda finding: (
                severity_rank.get(finding.severity.value, 0),
                finding.evidence_quality,
                finding.confidence,
                not finding.needs_human_review,
            ),
            reverse=True,
        )

    @staticmethod
    def _scan_metadata(snapshot: RepoSnapshotRecord) -> dict:
        try:
            return json.loads(snapshot.scan_metadata or "{}")
        except Exception:
            return {}

    def _calibrate_findings(self, findings: list[GeneratedFinding], scan_metadata: dict) -> list[GeneratedFinding]:
        frameworks = {str(item).lower() for item in scan_metadata.get("frameworks", [])}
        calibrated: list[GeneratedFinding] = []
        seen_families: set[str] = set()
        for finding in findings:
            evidence_quality = self._evidence_quality(finding, frameworks)
            confidence = min(0.99, round((finding.confidence * 0.65) + (evidence_quality * 0.35), 3))
            if evidence_quality < 0.22 and confidence < 0.35:
                continue
            framework_tags = self._framework_tags(finding, frameworks)
            updated = finding.model_copy(
                update={
                    "confidence": confidence,
                    "evidence_quality": evidence_quality,
                    "framework_tags": framework_tags,
                    "needs_human_review": finding.needs_human_review or evidence_quality < 0.45,
                }
            )
            family_id = self.family_id(updated)
            if family_id in seen_families and confidence < 0.6:
                continue
            seen_families.add(family_id)
            calibrated.append(updated)
        return calibrated

    @staticmethod
    def family_id(finding: GeneratedFinding | FindingRecord) -> str:
        title = " ".join((getattr(finding, "title", "") or "").lower().split()[:8])
        category = getattr(finding, "category", "") or ""
        path = getattr(finding, "file_path", "") or "repo"
        rule_id = getattr(finding, "rule_id", "") or "generic"
        family_basis = f"{category}|{rule_id}|{path.rsplit('/', 1)[0]}|{title}"
        return hashlib.sha1(family_basis.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _framework_tags(finding: GeneratedFinding, frameworks: set[str]) -> list[str]:
        haystack = " ".join(
            [
                finding.title.lower(),
                finding.description.lower(),
                (finding.file_path or "").lower(),
            ]
        )
        tags = [framework for framework in frameworks if framework in haystack]
        if not tags:
            if "django" in haystack:
                tags.append("django")
            if "fastapi" in haystack or "pydantic" in haystack:
                tags.append("fastapi")
            if "express" in haystack or "middleware" in haystack:
                tags.append("express")
            if "react" in haystack or "next" in haystack:
                tags.append("react_next")
            if "spring" in haystack or "controller" in haystack:
                tags.append("spring")
        return sorted(set(tags))

    @staticmethod
    def _evidence_quality(finding: GeneratedFinding, frameworks: set[str]) -> float:
        score = 0.15
        if finding.file_path:
            score += 0.2
        if finding.line_start is not None:
            score += 0.15
        if len(finding.reasoning_summary.split()) >= 10:
            score += 0.15
        if len(finding.remediation_summary.split()) >= 8:
            score += 0.1
        if finding.verdict.value in {"true_positive", "likely_true_positive"}:
            score += 0.1
        if finding.framework_tags:
            score += 0.05
        if frameworks and any(tag in frameworks for tag in finding.framework_tags):
            score += 0.1
        return round(min(score, 1.0), 3)


class RepoChatLLMService:
    """Answer repository questions against stored local chunks."""

    def __init__(self, provider: ProviderBase, review_store: ReviewStore) -> None:
        self.provider = provider
        self.review_store = review_store
        self.evidence_builder = EvidenceBuilder()
        self.prompt_builder = PromptBuilder()

    def answer(self, question: str, hits: list[RetrievalHit], history: list[dict[str, str]]) -> RepoChatResponse:
        evidence, evidence_hash = self.evidence_builder.build_chat_evidence(question, hits, history)
        cached = self.review_store.get_cache(evidence_hash)
        if cached:
            return RepoChatResponse.model_validate(cached)
        prompt = self.prompt_builder.repo_chat_prompt(evidence)
        response = self.provider.generate_structured(prompt, RepoChatResponse)
        self.review_store.set_cache(evidence_hash, response.model_dump(mode="json"))
        return response


class PatchSuggestionLLMService:
    """Generate patch suggestions for a selected finding."""

    def __init__(self, provider: ProviderBase, review_store: ReviewStore, patch_store: PatchSuggestionStore) -> None:
        self.provider = provider
        self.review_store = review_store
        self.patch_store = patch_store
        self.evidence_builder = EvidenceBuilder()
        self.prompt_builder = PromptBuilder()

    def suggest(
        self,
        repo_root: Path,
        finding: FindingRecord,
        related_chunks: list[EmbeddingChunkRecord],
        related_symbols,
        patch_context: dict,
        retrieval_hits: list[RetrievalHit],
        snapshot_id: int,
    ) -> PatchSuggestionRecord:
        evidence, evidence_hash = self.evidence_builder.build_patch_evidence(
            repo_root,
            finding,
            related_chunks,
            related_symbols,
            patch_context,
            retrieval_hits,
        )
        cached = self.review_store.get_cache(evidence_hash)
        if cached:
            response = PatchSuggestion.model_validate(cached)
        else:
            prompt = self.prompt_builder.patch_suggestion_prompt(evidence)
            response = self.provider.generate_structured(prompt, PatchSuggestion)
            self.review_store.set_cache(evidence_hash, response.model_dump(mode="json"))
        return self.patch_store.add(
            PatchSuggestionRecord(
                id=None,
                snapshot_id=snapshot_id,
                finding_id=finding.id,
                summary=response.summary,
                rationale=response.rationale,
                suggested_diff=response.suggested_diff,
                confidence=response.confidence,
                alternatives_json=json.dumps([item.model_dump(mode="json") for item in response.alternatives]),
                validation_json=json.dumps(
                    {
                        "status": response.validation_status,
                        "notes": response.validation_notes,
                    }
                ),
                created_at=datetime.utcnow().isoformat(timespec="seconds"),
            )
        )
