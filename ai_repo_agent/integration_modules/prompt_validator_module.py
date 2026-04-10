"""Portable LLM-backed prompt validation module.

This module depends only on the shared provider abstraction, so it can be moved
to another deployment and connected to any configured provider implementation.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from ai_repo_agent.llm.provider import ProviderBase


INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "system prompt",
    "reveal hidden prompt",
    "bypass safety",
    "developer instructions",
    "act as root",
)

SECRETS_PATTERNS = (
    "api key",
    "password",
    "secret token",
    "private key",
    "credential",
    "session cookie",
)

DANGEROUS_PATTERNS = (
    "rm -rf",
    "drop database",
    "delete all data",
    "steal credentials",
    "exfiltrate",
)

SUSPICIOUS_CODE_PATTERNS = (
    "subprocess.",
    "os.system",
    "eval(",
    "exec(",
    "curl http",
    "wget http",
)


class PromptValidationDecision(BaseModel):
    """Structured LLM response for prompt validation."""

    allowed: bool
    risk_level: str = Field(pattern="^(low|medium|high)$")
    sanitized_prompt: str
    issues: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    recommendation: Literal["allow", "revise", "reject"] = "allow"
    reasoning: str


class PromptValidationRequest(BaseModel):
    """Input payload for prompt validation."""

    prompt: str
    use_case: str = "general"
    max_length: int = Field(default=4000, ge=100, le=20000)
    blocked_terms: list[str] = Field(default_factory=list)
    strict_mode: bool = False


class PromptValidationResponse(BaseModel):
    """Public module response for callers."""

    accepted: bool
    risk_level: str
    original_prompt: str
    sanitized_prompt: str
    issues: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    recommendation: Literal["allow", "revise", "reject"] = "allow"
    local_flags: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_error: str | None = None
    validation_mode: Literal["local_only", "local_and_llm", "local_fallback"] = "local_only"
    reasoning: str


class PromptValidatorService:
    """Validate prompts with rule-based checks and an optional LLM decision."""

    def __init__(self, provider: ProviderBase | None) -> None:
        self.provider = provider

    def validate(self, request: PromptValidationRequest) -> PromptValidationResponse:
        prompt = request.prompt.strip()
        if not prompt:
            return PromptValidationResponse(
                accepted=False,
                risk_level="high",
                original_prompt=request.prompt,
                sanitized_prompt="",
                issues=["Prompt is empty."],
                categories=["format"],
                recommendation="reject",
                local_flags=["empty"],
                validation_mode="local_only",
                reasoning="The prompt must contain text before it can be validated.",
            )
        if len(prompt) > request.max_length:
            return PromptValidationResponse(
                accepted=False,
                risk_level="medium",
                original_prompt=request.prompt,
                sanitized_prompt=prompt[: request.max_length],
                issues=[f"Prompt exceeds the maximum supported length of {request.max_length} characters."],
                categories=["format"],
                recommendation="revise",
                local_flags=["too_long"],
                validation_mode="local_only",
                reasoning="The prompt should be shortened before it is sent to the LLM.",
            )

        blocked_matches = [term for term in request.blocked_terms if term.lower() in prompt.lower()]
        if blocked_matches:
            return PromptValidationResponse(
                accepted=False,
                risk_level="high",
                original_prompt=request.prompt,
                sanitized_prompt=prompt,
                issues=[f"Blocked term detected: {term}" for term in blocked_matches],
                categories=["policy"],
                recommendation="reject",
                local_flags=["blocked_term"],
                validation_mode="local_only",
                reasoning="The prompt contains blocked content configured by the caller.",
            )

        heuristic = self._heuristic_assessment(prompt, request)
        if not heuristic["allowed"]:
            return self._response_from_heuristic(request, heuristic)

        if self.provider is None:
            response = self._response_from_heuristic(request, heuristic)
            response.reasoning = "No LLM provider is configured, so local heuristic validation was applied."
            return response

        try:
            decision = self.provider.generate_structured(self._build_prompt(request, prompt), PromptValidationDecision)
        except Exception as exc:
            response = self._response_from_heuristic(request, heuristic)
            response.llm_error = str(exc)
            response.validation_mode = "local_fallback"
            response.reasoning = (
                "LLM validation was unavailable, so the result falls back to local heuristic validation."
            )
            if str(exc):
                response.issues.append("LLM validator was unavailable; local validation was used instead.")
            response.issues = self._dedupe_list(response.issues)
            return response

        sanitized = decision.sanitized_prompt.strip() or heuristic["sanitized_prompt"]
        combined_categories = self._dedupe_list(heuristic["categories"] + decision.categories)
        combined_issues = self._dedupe_list(heuristic["issues"] + decision.issues)
        return PromptValidationResponse(
            accepted=decision.allowed,
            risk_level=decision.risk_level,
            original_prompt=request.prompt,
            sanitized_prompt=sanitized,
            issues=combined_issues,
            categories=combined_categories,
            recommendation=decision.recommendation,
            local_flags=heuristic["flags"],
            llm_used=True,
            validation_mode="local_and_llm",
            reasoning=decision.reasoning,
        )

    @staticmethod
    def _basic_sanitize(prompt: str) -> str:
        cleaned = prompt.replace("\x00", " ").replace("\r", "\n")
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _dedupe_list(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _response_from_heuristic(self, request: PromptValidationRequest, heuristic: dict) -> PromptValidationResponse:
        return PromptValidationResponse(
            accepted=heuristic["allowed"],
            risk_level=heuristic["risk_level"],
            original_prompt=request.prompt,
            sanitized_prompt=heuristic["sanitized_prompt"],
            issues=self._dedupe_list(heuristic["issues"]),
            categories=self._dedupe_list(heuristic["categories"]),
            recommendation=heuristic["recommendation"],
            local_flags=self._dedupe_list(heuristic["flags"]),
            llm_used=False,
            validation_mode="local_only",
            reasoning=heuristic["reasoning"],
        )

    def _build_prompt(self, request: PromptValidationRequest, prompt: str) -> str:
        heuristic = self._heuristic_assessment(prompt, request)
        evidence = {
            "prompt": prompt,
            "use_case": request.use_case,
            "max_length": request.max_length,
            "blocked_terms": request.blocked_terms,
            "strict_mode": request.strict_mode,
            "local_heuristics": heuristic,
            "validation_goals": [
                "Reject clearly unsafe, disallowed, or malformed prompts.",
                "Return a cleaned prompt when the prompt is acceptable.",
                "Explain the main risks or quality issues briefly.",
            ],
        }
        return (
            "You are validating a prompt before it is sent to an LLM.\n"
            "Return JSON only.\n"
            "Approve prompts that are safe, well-formed, and suitable for the stated use case.\n"
            "Reject prompts that are unsafe, malformed, or clearly violate caller restrictions.\n"
            "If the prompt is acceptable, set allowed=true and return a cleaned sanitized_prompt.\n"
            "Use risk_level values: low, medium, high.\n"
            "Schema:\n"
            "{"
            '"allowed":true,'
            '"risk_level":"low|medium|high",'
            '"sanitized_prompt":"string",'
            '"issues":["string"],'
            '"categories":["policy|security|injection|quality|format"],'
            '"recommendation":"allow|revise|reject",'
            '"reasoning":"string"'
            "}\n"
            f"Validation input:\n{json.dumps(evidence, indent=2)}"
        )

    def _heuristic_assessment(self, prompt: str, request: PromptValidationRequest) -> dict:
        sanitized = self._basic_sanitize(prompt)
        lowered = sanitized.lower()
        issues: list[str] = []
        categories: set[str] = set()
        flags: list[str] = []
        score = 0

        for pattern in INJECTION_PATTERNS:
            if pattern in lowered:
                issues.append(f"Potential prompt-injection pattern detected: '{pattern}'.")
                categories.add("injection")
                flags.append("injection_pattern")
                score += 3

        for pattern in SECRETS_PATTERNS:
            if pattern in lowered:
                issues.append(f"Potential sensitive-data request detected: '{pattern}'.")
                categories.add("security")
                flags.append("secret_pattern")
                score += 2

        for pattern in DANGEROUS_PATTERNS:
            if pattern in lowered:
                issues.append(f"Potentially dangerous instruction detected: '{pattern}'.")
                categories.add("policy")
                flags.append("dangerous_pattern")
                score += 4

        for pattern in SUSPICIOUS_CODE_PATTERNS:
            if pattern in lowered:
                issues.append(f"Suspicious executable code pattern detected: '{pattern}'.")
                categories.add("security")
                flags.append("suspicious_code")
                score += 2

        if "```" in sanitized:
            categories.add("quality")
            flags.append("contains_code_block")

        if len(sanitized) > 2500:
            issues.append("Prompt is very long and may reduce answer quality or exceed model context budgets.")
            categories.add("quality")
            flags.append("very_long_prompt")
            score += 1

        if re.search(r"(.)\1{9,}", sanitized):
            issues.append("Prompt contains unusually repetitive character sequences.")
            categories.add("quality")
            flags.append("repetitive_text")
            score += 1

        if len(sanitized.split()) < 3:
            issues.append("Prompt is very short and may not give the model enough context.")
            categories.add("quality")
            flags.append("too_short")
            score += 1

        if not re.search(r"[A-Za-z0-9]", sanitized):
            issues.append("Prompt does not contain meaningful alphanumeric content.")
            categories.add("format")
            flags.append("non_meaningful")
            score += 2

        recommendation = "allow"
        allowed = True
        risk_level = "low"
        if request.strict_mode and score >= 2:
            allowed = False
            recommendation = "reject"
            risk_level = "high" if score >= 4 else "medium"
        elif score >= 4:
            allowed = False
            recommendation = "reject"
            risk_level = "high"
        elif score >= 2:
            recommendation = "revise"
            risk_level = "medium"

        return {
            "allowed": allowed,
            "risk_level": risk_level,
            "sanitized_prompt": sanitized,
            "issues": self._dedupe_list(issues),
            "categories": sorted(categories),
            "recommendation": recommendation,
            "flags": self._dedupe_list(flags),
            "reasoning": "Local heuristic screening completed.",
        }
