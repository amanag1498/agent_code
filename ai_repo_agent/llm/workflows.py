"""Structured LLM workflows for findings, repo chat, and patch suggestions."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from ai_repo_agent.core.enums import ReviewTargetType
from ai_repo_agent.core.models import (
    EmbeddingChunkRecord,
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
        architecture_observations: list[str],
        dependency_summary: list[dict],
        focus_file_paths: set[str] | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> tuple[list[GeneratedFinding], str]:
        evidence_batches = self.evidence_builder.build_repo_analysis_batches(
            repo_root=repo_root,
            snapshot=snapshot,
            symbols=symbols,
            chunks=chunks,
            architecture_observations=architecture_observations,
            dependency_summary=dependency_summary,
            focus_file_paths=focus_file_paths,
            max_batches=5,
            batch_size=4,
        )
        specialized_batches = self.evidence_builder.build_specialized_analysis_batches(
            repo_root=repo_root,
            snapshot=snapshot,
            chunks=chunks,
            dependency_summary=dependency_summary,
            focus_file_paths=focus_file_paths,
        )
        combined_batches = [(evidence, evidence_hash, "general") for evidence, evidence_hash in evidence_batches]
        combined_batches.extend((evidence, evidence_hash, "specialized") for evidence, evidence_hash in specialized_batches)
        aggregated: list[GeneratedFinding] = []
        evidence_hashes: list[str] = []
        seen: set[str] = set()
        max_per_batch = max(3, min(6, self.max_findings))
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
            for finding in self._dedupe_and_rank(batch.findings if batch else []):
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
                finding.confidence,
                not finding.needs_human_review,
            ),
            reverse=True,
        )


class RepoChatLLMService:
    """Answer repository questions against stored local chunks."""

    def __init__(self, provider: ProviderBase, review_store: ReviewStore) -> None:
        self.provider = provider
        self.review_store = review_store
        self.evidence_builder = EvidenceBuilder()
        self.prompt_builder = PromptBuilder()

    def answer(self, question: str, chunks: list[EmbeddingChunkRecord], history: list[dict[str, str]]) -> RepoChatResponse:
        evidence, evidence_hash = self.evidence_builder.build_chat_evidence(question, chunks, history)
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

    def suggest(self, repo_root: Path, finding: FindingRecord, related_chunks: list[EmbeddingChunkRecord], snapshot_id: int) -> PatchSuggestionRecord:
        evidence, evidence_hash = self.evidence_builder.build_patch_evidence(repo_root, finding, related_chunks)
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
                created_at=datetime.utcnow().isoformat(timespec="seconds"),
            )
        )
