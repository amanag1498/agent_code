"""Structured LLM judge services."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from hashlib import sha256

from ai_repo_agent.core.enums import ReviewTargetType
from ai_repo_agent.core.models import DiffReview, FindingRecord, FindingReview, LLMReviewRecord, RepoReview, RepoSnapshotRecord
from ai_repo_agent.db.repositories import ReviewStore
from ai_repo_agent.llm.evidence import EvidenceBuilder
from ai_repo_agent.llm.prompts import PROMPT_VERSION, PromptBuilder
from ai_repo_agent.llm.provider import ProviderBase


class JudgeService:
    """Shared LLM review infrastructure with deterministic cache."""

    def __init__(self, provider: ProviderBase, review_store: ReviewStore) -> None:
        self.provider = provider
        self.review_store = review_store
        self.evidence_builder = EvidenceBuilder()
        self.prompt_builder = PromptBuilder()

    def _cached_or_generate(self, cache_key: str, prompt: str, response_model: type):
        cached = self.review_store.get_cache(cache_key)
        if cached:
            return response_model.model_validate(cached)
        response = self.provider.generate_structured(prompt, response_model)
        self.review_store.set_cache(cache_key, response.model_dump(mode="json"))
        return response


class FindingValidator(JudgeService):
    """Validate normalized findings with the configured LLM provider."""

    def review(
        self,
        repo_root: Path,
        finding: FindingRecord,
        previous_related: list[FindingRecord],
        diff_summary: str,
        architecture_observations: list[str],
    ) -> FindingReview:
        evidence, evidence_hash = self.evidence_builder.build_finding_evidence(
            repo_root, finding, previous_related, diff_summary, architecture_observations
        )
        prompt = self.prompt_builder.finding_review_prompt(evidence)
        response = self._cached_or_generate(evidence_hash, prompt, FindingReview)
        self.review_store.save_review(
            LLMReviewRecord(
                id=None,
                target_type=ReviewTargetType.FINDING,
                finding_id=finding.id,
                snapshot_id=finding.repo_snapshot_id,
                model_name=getattr(self.provider, "model_name", "unknown"),
                prompt_version=PROMPT_VERSION,
                verdict=response.verdict.value,
                confidence=response.confidence,
                severity_override=response.severity_override.value,
                reasoning_summary=response.reasoning_summary,
                remediation_summary=response.remediation_summary,
                evidence_hash=evidence_hash,
                raw_response=json.dumps(response.model_dump(mode="json")),
                created_at=datetime.utcnow().isoformat(timespec="seconds"),
            )
        )
        return response


class DiffJudge(JudgeService):
    """Judge diff-related change risk."""

    def review(self, evidence: dict) -> DiffReview:
        prompt = self.prompt_builder.diff_review_prompt(evidence)
        cache_key = sha256(json.dumps(evidence, sort_keys=True).encode("utf-8")).hexdigest()
        return self._cached_or_generate(cache_key, prompt, DiffReview)


class RepoJudge(JudgeService):
    """Judge repo-level readiness."""

    def review(self, snapshot: RepoSnapshotRecord, compare_summary: str, top_findings: list[FindingRecord]) -> RepoReview:
        evidence, evidence_hash = self.evidence_builder.build_snapshot_evidence(snapshot, compare_summary, top_findings)
        prompt = self.prompt_builder.repo_review_prompt(evidence)
        return self._cached_or_generate(evidence_hash, prompt, RepoReview)
