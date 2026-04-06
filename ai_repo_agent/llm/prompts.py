"""Prompt builders for structured judging."""

from __future__ import annotations

import json


PROMPT_VERSION = "v1"


class PromptBuilder:
    """Build grounded prompts for structured LLM providers."""

    def finding_generation_prompt(self, evidence: dict, max_findings: int) -> str:
        return (
            "You are analyzing a local code repository for security, vulnerabilities, architecture issues, risky changes, and code quality.\n"
            "Stay grounded strictly in the provided evidence only.\n"
            "Do not invent files, code paths, libraries, or hidden behavior outside the evidence.\n"
            "Return at most "
            f"{max_findings} findings and omit low-signal guesses.\n"
            "If evidence is weak, use verdict uncertain and set needs_human_review to true.\n"
            "Do not wrap the JSON in markdown fences.\n"
            "Escape backslashes inside JSON strings correctly. Prefer forward slashes in file paths when possible.\n"
            "Return JSON only matching this schema:\n"
            "{"
            '"findings":['
            "{"
            '"rule_id":"string","title":"string","description":"string","severity":"critical|high|medium|low|info|unknown",'
            '"category":"security|vulnerability|architecture|quality|risky_change|dependency",'
            '"file_path":"string|null","line_start":1,"line_end":1,'
            '"verdict":"true_positive|likely_true_positive|uncertain|likely_false_positive|false_positive",'
            '"confidence":0.0,'
            '"framework_tags":["string"],'
            '"evidence_quality":0.0,'
            '"severity_override":"critical|high|medium|low|info|unchanged",'
            '"impact_summary":"string","reasoning_summary":"string","remediation_summary":"string",'
            '"related_change_risk":"string","needs_human_review":true'
            "}"
            "]}"
            f"\nEvidence:\n{json.dumps(evidence, indent=2)}"
        )

    def finding_review_prompt(self, evidence: dict) -> str:
        return (
            "You are reviewing a software security or quality finding.\n"
            "Stay grounded strictly in the provided evidence only.\n"
            "Do not invent repository facts, exploit paths, dependencies, or mitigations not supported by the evidence.\n"
            "If evidence is insufficient, return uncertain and set needs_human_review to true.\n"
            "Do not wrap the JSON in markdown fences.\n"
            "Escape backslashes inside JSON strings correctly. Prefer forward slashes in file paths when possible.\n"
            "Return JSON only matching this schema:\n"
            "{"
            '"verdict":"true_positive|likely_true_positive|uncertain|likely_false_positive|false_positive",'
            '"confidence":0.0,'
            '"framework_tags":["string"],'
            '"evidence_quality":0.0,'
            '"severity_override":"critical|high|medium|low|info|unchanged",'
            '"impact_summary":"string",'
            '"reasoning_summary":"string",'
            '"remediation_summary":"string",'
            '"related_change_risk":"string",'
            '"needs_human_review":true'
            "}\n"
            f"Evidence:\n{json.dumps(evidence, indent=2)}"
        )

    def diff_review_prompt(self, evidence: dict) -> str:
        return (
            "You are reviewing changed code for security and risk impact.\n"
            "Use only the provided diff context and prior findings. Do not infer hidden code.\n"
            "Do not wrap the JSON in markdown fences.\n"
            "Escape backslashes inside JSON strings correctly.\n"
            "Return JSON only matching this schema:\n"
            "{"
            '"confidence":0.0,'
            '"risk_increased":true,'
            '"reasoning_summary":"string",'
            '"suspicious_changes":["string"],'
            '"reintroduction_risk":"string",'
            '"needs_human_review":true'
            "}\n"
            f"Evidence:\n{json.dumps(evidence, indent=2)}"
        )

    def repo_review_prompt(self, evidence: dict) -> str:
        return (
            "You are summarizing repository risk and release readiness.\n"
            "Stay grounded in the evidence. Do not add unsupported claims.\n"
            "Do not wrap the JSON in markdown fences.\n"
            "Escape backslashes inside JSON strings correctly.\n"
            "Return JSON only matching this schema:\n"
            "{"
            '"confidence":0.0,'
            '"top_risks":["string"],'
            '"release_readiness_summary":"string",'
            '"prioritized_remediation":["string"],'
            '"needs_human_review":true'
            "}\n"
            f"Evidence:\n{json.dumps(evidence, indent=2)}"
        )

    def repo_chat_prompt(self, evidence: dict) -> str:
        return (
            "You are answering a repository question using only retrieved local evidence.\n"
            "Do not claim anything not supported by the snippets or history.\n"
            "Do not wrap the JSON in markdown fences.\n"
            "Escape backslashes inside JSON strings correctly.\n"
            "Return JSON only matching this schema:\n"
            "{"
            '"answer":"string","cited_files":["string"],"confidence":0.0,"needs_human_review":true'
            "}\n"
            f"Evidence:\n{json.dumps(evidence, indent=2)}"
        )

    def patch_suggestion_prompt(self, evidence: dict) -> str:
        return (
            "You are proposing a patch for a repository finding using only the supplied code evidence.\n"
            "Do not invent surrounding code beyond the shown snippets. If uncertain, keep the patch conservative.\n"
            "Do not wrap the JSON in markdown fences.\n"
            "Escape backslashes inside JSON strings correctly.\n"
            "Return JSON only matching this schema:\n"
            "{"
            '"summary":"string","rationale":"string","suggested_diff":"string","confidence":0.0,'
            '"needs_human_review":true,'
            '"validation_status":"valid|warning|invalid|not_run",'
            '"validation_notes":["string"],'
            '"alternatives":[{"label":"string","summary":"string","suggested_diff":"string"}]'
            "}\n"
            f"Evidence:\n{json.dumps(evidence, indent=2)}"
        )

    def specialized_finding_generation_prompt(self, evidence: dict, max_findings: int) -> str:
        focus = evidence.get("analysis_focus", "specialized")
        return (
            f"You are performing a focused {focus} review of a code repository.\n"
            "Prioritize precise, evidence-backed findings only for this focus area.\n"
            "Stay grounded strictly in the provided evidence only.\n"
            "Do not invent hidden code paths, frameworks, or exploit chains outside the evidence.\n"
            f"Return at most {max_findings} findings.\n"
            "If evidence is weak, use verdict uncertain and set needs_human_review to true.\n"
            "Do not wrap the JSON in markdown fences.\n"
            "Escape backslashes inside JSON strings correctly. Prefer forward slashes in file paths when possible.\n"
            "Return JSON only matching this schema:\n"
            "{"
            '"findings":['
            "{"
            '"rule_id":"string","title":"string","description":"string","severity":"critical|high|medium|low|info|unknown",'
            '"category":"security|vulnerability|architecture|quality|risky_change|dependency",'
            '"file_path":"string|null","line_start":1,"line_end":1,'
            '"verdict":"true_positive|likely_true_positive|uncertain|likely_false_positive|false_positive",'
            '"confidence":0.0,'
            '"severity_override":"critical|high|medium|low|info|unchanged",'
            '"impact_summary":"string","reasoning_summary":"string","remediation_summary":"string",'
            '"related_change_risk":"string","needs_human_review":true'
            "}"
            "]}"
            f"\nEvidence:\n{json.dumps(evidence, indent=2)}"
        )
