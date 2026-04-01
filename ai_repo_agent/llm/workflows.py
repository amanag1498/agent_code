"""Gemini-first workflows for findings, repo chat, and patch suggestions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

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


class GeminiFindingGenerator:
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
    ) -> tuple[list[GeneratedFinding], str]:
        evidence, evidence_hash = self.evidence_builder.build_repo_analysis_evidence(
            repo_root=repo_root,
            snapshot=snapshot,
            symbols=symbols,
            chunks=chunks,
            architecture_observations=architecture_observations,
            dependency_summary=dependency_summary,
            max_chunks=5,
        )
        prompt = self.prompt_builder.finding_generation_prompt(evidence, self.max_findings)
        cached = self.review_store.get_cache(evidence_hash)
        if cached:
            batch = FindingBatch.model_validate(cached)
        else:
            batch = self.provider.generate_structured(prompt, FindingBatch)
            self.review_store.set_cache(evidence_hash, batch.model_dump(mode="json"))
        return batch.findings, evidence_hash

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
