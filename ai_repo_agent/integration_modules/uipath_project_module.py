"""Portable UiPath project structure analyzer.

This module is intentionally self-contained and uses only the Python standard
library so it can be copied into another deployment or run beside a UiPath
project without needing the full AI Repo Analyst app.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


IGNORED_DIRS = {
    ".git",
    ".local",
    ".settings",
    ".objects",
    "bin",
    "obj",
    "packages",
    "node_modules",
}

REFRAMEWORK_FILES = {
    "Main.xaml",
    "Framework/InitAllApplications.xaml",
    "Framework/InitAllSettings.xaml",
    "Framework/GetTransactionData.xaml",
    "Framework/ProcessTransaction.xaml",
    "Framework/SetTransactionStatus.xaml",
    "Framework/CloseAllApplications.xaml",
    "Framework/KillAllProcesses.xaml",
    "Data/Config.xlsx",
}

CORE_FILE_DESCRIPTIONS = {
    "project.json": "UiPath project manifest with dependencies, runtime settings, entry points, and package metadata.",
    "Main.xaml": "Default entry workflow for most process projects.",
    "Data/Config.xlsx": "Common REFramework configuration workbook for constants, assets, applications, and queues.",
    "Tests/": "Recommended folder for UiPath test workflows.",
    "Documentation/": "Recommended folder for PDD, SDD, runbook, and support notes.",
    "Objects/": "Optional object repository folder for reusable UI elements.",
}

HARDCODED_SECRET_PATTERNS = (
    "password",
    "credential",
    "secret",
    "token",
    "api key",
    "apikey",
)

EXCEPTION_ACTIVITY_NAMES = {
    "TryCatch",
    "RetryScope",
    "Throw",
    "Rethrow",
    "GlobalHandler",
}

QUEUE_ACTIVITY_TERMS = (
    "GetTransactionItem",
    "GetQueueItem",
    "AddQueueItem",
    "SetTransactionStatus",
    "QueueItem",
    "TransactionItem",
)

ASSET_ACTIVITY_TERMS = (
    "GetAsset",
    "GetCredential",
    "GetRobotCredential",
)

REFRAMEWORK_MAIN_TARGETS = {
    "InitAllSettings.xaml",
    "InitAllApplications.xaml",
    "GetTransactionData.xaml",
    "ProcessTransaction.xaml",
    "SetTransactionStatus.xaml",
}


class OpenAICompatibleLLMClient:
    """Tiny stdlib OpenAI-compatible chat-completions client.

    This keeps the UiPath module portable: copy this one file, set an API key,
    and run the CLI without installing provider SDKs.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key or os.environ.get("UIPATH_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("UIPATH_LLM_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        self.base_url = (base_url or os.environ.get("UIPATH_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("Missing API key. Set UIPATH_LLM_API_KEY or OPENAI_API_KEY, or pass --api-key.")

    def generate_json(self, prompt: str) -> dict:
        return UiPathProjectAnalyzer._parse_llm_json(self.generate(prompt))

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise UiPath project reviewer. Return valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM HTTP error {exc.code}: {detail}") from exc
        payload = json.loads(raw)
        return payload["choices"][0]["message"]["content"]


@dataclass(slots=True)
class UiPathWorkflowSummary:
    """Summary of one XAML workflow file."""

    path: str
    role: str
    root_activity: str | None
    display_names: list[str] = field(default_factory=list)
    invoked_workflows: list[str] = field(default_factory=list)
    activity_counts: dict[str, int] = field(default_factory=dict)
    selectors_count: int = 0
    config_references: list[str] = field(default_factory=list)
    exception_activity_count: int = 0
    queue_activity_count: int = 0
    asset_activity_count: int = 0
    arguments: list[str] = field(default_factory=list)
    argument_directions: dict[str, str] = field(default_factory=dict)
    invoked_argument_mappings: dict[str, list[str]] = field(default_factory=dict)
    line_evidence: dict[str, list[int]] = field(default_factory=dict)
    activity_lines: dict[str, list[int]] = field(default_factory=dict)
    hardcoded_secret_hits: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UiPathFinding:
    """Portable structured finding for a UiPath project."""

    rule_id: str
    title: str
    severity: str
    category: str
    description: str
    recommendation: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    verdict: str = "likely_true_positive"
    confidence: float = 0.75
    severity_override: str = "unchanged"
    impact_summary: str = ""
    reasoning_summary: str = ""
    remediation_summary: str = ""
    related_change_risk: str = ""
    needs_human_review: bool = True
    evidence_quality: float = 0.65
    source: str = "local_rules"
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.impact_summary:
            self.impact_summary = self.description
        if not self.reasoning_summary:
            self.reasoning_summary = "; ".join(self.evidence[:3]) or self.description
        if not self.remediation_summary:
            self.remediation_summary = self.recommendation
        if not self.related_change_risk:
            self.related_change_risk = "Review this finding before promoting the UiPath package to a shared robot or production environment."


@dataclass(slots=True)
class UiPathProjectAnalysis:
    """Structured analysis of a UiPath project folder."""

    root_path: str
    project_json_present: bool
    project_name: str | None
    description: str | None
    main_workflow: str | None
    target_framework: str | None
    expression_language: str | None
    dependencies: dict[str, str] = field(default_factory=dict)
    entry_points: list[str] = field(default_factory=list)
    xaml_files: list[str] = field(default_factory=list)
    workflows: list[UiPathWorkflowSummary] = field(default_factory=list)
    required_files: dict[str, str] = field(default_factory=dict)
    present_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    workflow_graph: list[dict[str, Any]] = field(default_factory=list)
    is_reframework_like: bool = False
    reframework_missing: list[str] = field(default_factory=list)
    findings: list[UiPathFinding] = field(default_factory=list)
    llm_used: bool = False
    llm_error: str | None = None
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a JSON-serializable representation."""

        return asdict(self)


class UiPathProjectAnalyzer:
    """Analyze UiPath project files, workflows, dependencies, and structure."""

    def analyze(
        self,
        root: str | Path,
        llm_client: Any | None = None,
        max_llm_findings: int = 8,
        findings_mode: str = "both",
    ) -> UiPathProjectAnalysis:
        findings_mode = self._choice(findings_mode, {"local", "llm", "both"}, "both")
        project_root = Path(root).expanduser().resolve()
        if not project_root.exists():
            raise FileNotFoundError(f"UiPath project path does not exist: {project_root}")
        if not project_root.is_dir():
            raise NotADirectoryError(f"UiPath project path is not a directory: {project_root}")

        project_json_path = project_root / "project.json"
        project_payload = self._read_project_json(project_json_path)
        xaml_files = self._find_xaml_files(project_root)
        workflows = [self._analyze_workflow(project_root, path) for path in xaml_files]
        present_files = self._present_core_files(project_root)
        missing_files = self._missing_core_files(project_root, project_payload, xaml_files)
        entry_points = self._entry_points(project_payload)
        main_workflow = self._main_workflow(project_payload, entry_points)
        workflow_graph = self._workflow_graph(workflows)
        is_reframework_like = self._is_reframework_like(project_root, workflows, project_payload)
        reframework_missing = self._reframework_missing(project_root) if is_reframework_like else []

        analysis = UiPathProjectAnalysis(
            root_path=str(project_root),
            project_json_present=project_json_path.exists(),
            project_name=self._string_field(project_payload, "name"),
            description=self._string_field(project_payload, "description"),
            main_workflow=main_workflow,
            target_framework=self._string_field(project_payload, "targetFramework"),
            expression_language=self._string_field(project_payload, "expressionLanguage"),
            dependencies=self._dependencies(project_payload),
            entry_points=entry_points,
            xaml_files=[self._relative(project_root, path) for path in xaml_files],
            workflows=workflows,
            required_files=CORE_FILE_DESCRIPTIONS.copy(),
            present_files=present_files,
            missing_files=missing_files,
            workflow_graph=workflow_graph,
            is_reframework_like=is_reframework_like,
            reframework_missing=reframework_missing,
        )
        local_findings = self._findings(analysis)
        analysis.findings = local_findings
        if llm_client is not None:
            try:
                llm_findings = self._llm_findings(analysis, llm_client, max_llm_findings=max_llm_findings)
                if findings_mode == "llm":
                    analysis.findings = llm_findings
                elif findings_mode == "both":
                    analysis.findings = self._merge_findings(local_findings, llm_findings)
                analysis.llm_used = bool(llm_findings)
            except Exception as exc:
                analysis.llm_error = str(exc)
                if findings_mode == "llm":
                    analysis.findings = []
        elif findings_mode == "llm":
            analysis.findings = []
        analysis.recommendations = self._recommendations(analysis)
        return analysis

    def analyze_to_dict(
        self,
        root: str | Path,
        llm_client: Any | None = None,
        findings_mode: str = "both",
    ) -> dict:
        """Analyze a project and return a plain dictionary."""

        return self.analyze(root, llm_client=llm_client, findings_mode=findings_mode).to_dict()

    def write_report(
        self,
        root: str | Path,
        output_path: str | Path,
        llm_client: Any | None = None,
        max_llm_findings: int = 8,
        findings_mode: str = "both",
    ) -> UiPathProjectAnalysis:
        """Analyze a project and write a JSON report."""

        analysis = self.analyze(
            root,
            llm_client=llm_client,
            max_llm_findings=max_llm_findings,
            findings_mode=findings_mode,
        )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(analysis.to_dict(), indent=2), encoding="utf-8")
        return analysis

    @staticmethod
    def _read_project_json(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _find_xaml_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for path in root.rglob("*.xaml"):
            if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
                continue
            files.append(path)
        return sorted(files, key=lambda item: self._relative(root, item).lower())

    def _analyze_workflow(self, root: Path, path: Path) -> UiPathWorkflowSummary:
        rel_path = self._relative(root, path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        warnings: list[str] = []
        root_activity: str | None = None
        display_names: list[str] = []
        invoked_workflows: list[str] = []
        activity_counts: dict[str, int] = {}
        lines = text.splitlines()
        selectors_count = len(re.findall(r"<\s*webctrl|<\s*wnd|selector=", text, flags=re.IGNORECASE))
        hardcoded_secret_hits = self._hardcoded_secret_hits(text)
        arguments, argument_directions = self._workflow_arguments(text)
        invoked_argument_mappings = self._invoked_argument_mappings(lines)
        line_evidence = self._line_evidence(lines)
        activity_lines = self._activity_lines(lines)

        try:
            xml_root = ET.fromstring(text)
            root_activity = self._local_name(xml_root.tag)
            for element in xml_root.iter():
                activity_name = self._local_name(element.tag)
                activity_counts[activity_name] = activity_counts.get(activity_name, 0) + 1
                for attr_name, attr_value in element.attrib.items():
                    local_attr = self._local_name(attr_name)
                    if local_attr == "DisplayName" and attr_value.strip():
                        display_names.append(attr_value.strip())
                    if "WorkflowFileName" in local_attr:
                        invoked_workflows.extend(self._xaml_references(attr_value))
        except ET.ParseError as exc:
            warnings.append(f"XAML could not be parsed as XML: {exc}")
            root_activity = None
            display_names = self._display_names_from_text(text)
            invoked_workflows = self._xaml_references(text)

        return UiPathWorkflowSummary(
            path=rel_path,
            role=self._workflow_role(rel_path, text),
            root_activity=root_activity,
            display_names=self._dedupe(display_names)[:30],
            invoked_workflows=self._dedupe(invoked_workflows),
            activity_counts=dict(sorted(activity_counts.items(), key=lambda item: item[0].lower())),
            selectors_count=selectors_count,
            config_references=self._config_references(text),
            exception_activity_count=sum(activity_counts.get(name, 0) for name in EXCEPTION_ACTIVITY_NAMES),
            queue_activity_count=sum(count for name, count in activity_counts.items() if any(term.lower() in name.lower() for term in QUEUE_ACTIVITY_TERMS)),
            asset_activity_count=sum(count for name, count in activity_counts.items() if any(term.lower() in name.lower() for term in ASSET_ACTIVITY_TERMS)),
            arguments=arguments,
            argument_directions=argument_directions,
            invoked_argument_mappings=invoked_argument_mappings,
            line_evidence=line_evidence,
            activity_lines=activity_lines,
            hardcoded_secret_hits=hardcoded_secret_hits,
            warnings=warnings,
        )

    @staticmethod
    def _workflow_role(path: str, text: str) -> str:
        name = Path(path).stem.lower()
        lower_text = text.lower()
        if name == "main":
            return "entry"
        if "init" in name:
            return "initialization"
        if "processtransaction" in name or name == "process":
            return "transaction_processing"
        if "gettransactiondata" in name:
            return "transaction_fetch"
        if "settransactionstatus" in name:
            return "transaction_status"
        if "close" in name or "kill" in name:
            return "cleanup"
        if "test" in path.lower():
            return "test"
        if "invoke workflow file" in lower_text:
            return "orchestration"
        return "workflow"

    @staticmethod
    def _dependencies(payload: dict) -> dict[str, str]:
        dependencies = payload.get("dependencies", {})
        if not isinstance(dependencies, dict):
            return {}
        return {str(name): str(version) for name, version in sorted(dependencies.items())}

    @staticmethod
    def _entry_points(payload: dict) -> list[str]:
        entry_points = payload.get("entryPoints", [])
        if not isinstance(entry_points, list):
            return []
        result: list[str] = []
        for entry in entry_points:
            if isinstance(entry, dict):
                value = entry.get("filePath") or entry.get("path")
                if value:
                    result.append(str(value))
            elif isinstance(entry, str):
                result.append(entry)
        return UiPathProjectAnalyzer._dedupe(result)

    @staticmethod
    def _main_workflow(payload: dict, entry_points: list[str]) -> str | None:
        for key in ("main", "mainWorkflow", "mainWorkflowFile"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return entry_points[0] if entry_points else None

    @staticmethod
    def _present_core_files(root: Path) -> list[str]:
        present: list[str] = []
        for rel_path in CORE_FILE_DESCRIPTIONS:
            path = root / rel_path.rstrip("/")
            if path.exists():
                present.append(rel_path)
        return present

    def _missing_core_files(self, root: Path, payload: dict, xaml_files: list[Path]) -> list[str]:
        missing: list[str] = []
        if not (root / "project.json").exists():
            missing.append("project.json")
        main = self._main_workflow(payload, self._entry_points(payload)) or "Main.xaml"
        if not (root / main).exists() and not any(path.name.lower() == "main.xaml" for path in xaml_files):
            missing.append(main)
        if not xaml_files:
            missing.append("at least one .xaml workflow")
        return self._dedupe(missing)

    @staticmethod
    def _reframework_missing(root: Path) -> list[str]:
        return sorted(path for path in REFRAMEWORK_FILES if not (root / path).exists())

    @staticmethod
    def _is_reframework_like(root: Path, workflows: list[UiPathWorkflowSummary], payload: dict) -> bool:
        paths = {workflow.path.replace("\\", "/") for workflow in workflows}
        if (root / "Data" / "Config.xlsx").exists():
            return True
        if any(path.startswith("Framework/") for path in paths):
            return True
        if any("RoboticEnterpriseFramework" in name for name in payload.get("dependencies", {})):
            return True
        reframework_hits = len(paths.intersection(REFRAMEWORK_FILES))
        return reframework_hits >= 3

    @staticmethod
    def _recommendations(analysis: UiPathProjectAnalysis) -> list[str]:
        recommendations: list[str] = [finding.recommendation for finding in analysis.findings]
        if not analysis.project_json_present:
            recommendations.append("Add project.json so dependencies, entry points, and runtime settings are explicit.")
        if not analysis.xaml_files:
            recommendations.append("Add at least one .xaml workflow; UiPath execution needs workflow definitions.")
        if analysis.main_workflow and analysis.main_workflow not in analysis.xaml_files:
            recommendations.append(f"Verify main workflow exists and is committed: {analysis.main_workflow}.")
        if not any(path.startswith("Tests/") or "/Tests/" in path for path in analysis.xaml_files):
            recommendations.append("Add Tests/ workflows for key happy-path and failure-path automation scenarios.")
        if analysis.is_reframework_like and analysis.reframework_missing:
            recommendations.append("Complete the expected REFramework files or document why this project intentionally diverges.")
        if "UiPath.System.Activities" not in analysis.dependencies:
            recommendations.append("Verify core UiPath.System.Activities dependency is declared in project.json.")
        if not any(workflow.config_references for workflow in analysis.workflows) and analysis.is_reframework_like:
            recommendations.append("Reference Data/Config.xlsx consistently for assets, constants, queues, and application settings.")
        if not any(workflow.role == "cleanup" for workflow in analysis.workflows):
            recommendations.append("Add or identify cleanup workflows for closing applications and recovering failed runs.")
        if not any(workflow.selectors_count for workflow in analysis.workflows):
            recommendations.append("If this is a UI automation, include stable selector/object repository evidence for UI elements.")
        return UiPathProjectAnalyzer._dedupe(recommendations)

    @staticmethod
    def _compressed_llm_evidence(analysis: UiPathProjectAnalysis) -> dict[str, Any]:
        """Build a smaller, higher-signal evidence pack for LLM review."""

        workflows = [
            {
                "path": workflow.path,
                "role": workflow.role,
                "arguments": workflow.arguments,
                "argument_directions": workflow.argument_directions,
                "invoked_workflows": workflow.invoked_workflows,
                "invoked_argument_mappings": workflow.invoked_argument_mappings,
                "activity_counts": {
                    name: count
                    for name, count in workflow.activity_counts.items()
                    if count and (
                        name in EXCEPTION_ACTIVITY_NAMES
                        or any(term.lower() in name.lower() for term in QUEUE_ACTIVITY_TERMS + ASSET_ACTIVITY_TERMS)
                        or "InvokeWorkflowFile" in name
                    )
                },
                "selector_count": workflow.selectors_count,
                "exception_activity_count": workflow.exception_activity_count,
                "queue_activity_count": workflow.queue_activity_count,
                "asset_activity_count": workflow.asset_activity_count,
                "line_evidence": workflow.line_evidence,
                "warnings": workflow.warnings,
            }
            for workflow in analysis.workflows
        ]
        return {
            "project": {
                "name": analysis.project_name,
                "description": analysis.description,
                "main_workflow": analysis.main_workflow,
                "target_framework": analysis.target_framework,
                "expression_language": analysis.expression_language,
                "project_json_present": analysis.project_json_present,
            },
            "dependencies": analysis.dependencies,
            "entry_points": analysis.entry_points,
            "xaml_files": analysis.xaml_files,
            "missing_files": analysis.missing_files,
            "workflow_graph": analysis.workflow_graph,
            "is_reframework_like": analysis.is_reframework_like,
            "reframework_missing": analysis.reframework_missing,
            "workflows": workflows,
            "local_findings": [finding for finding in analysis.to_dict().get("findings", []) if finding.get("source") == "local_rules"],
        }

    def _llm_findings(
        self,
        analysis: UiPathProjectAnalysis,
        llm_client: Any,
        max_llm_findings: int,
    ) -> list[UiPathFinding]:
        prompt = self.build_llm_prompt(analysis, max_llm_findings)
        payload = self._call_llm_client(llm_client, prompt)
        raw_findings = payload.get("findings", payload if isinstance(payload, list) else [])
        if not isinstance(raw_findings, list):
            return []
        findings: list[UiPathFinding] = []
        for item in raw_findings[:max_llm_findings]:
            if isinstance(item, UiPathFinding):
                item.source = "llm"
                findings.append(item)
            elif isinstance(item, dict):
                findings.append(self._finding_from_payload(item))
        return self._validate_llm_findings(analysis, findings)

    def _call_llm_client(self, llm_client: Any, prompt: str) -> Any:
        if hasattr(llm_client, "generate_structured"):
            response_model = self._optional_pydantic_batch_model()
            if response_model is not None:
                response = llm_client.generate_structured(prompt, response_model)
                if hasattr(response, "model_dump"):
                    return response.model_dump(mode="json")
                if hasattr(response, "dict"):
                    return response.dict()
                return response

        if hasattr(llm_client, "generate_uipath_findings"):
            return llm_client.generate_uipath_findings(prompt)
        if hasattr(llm_client, "generate_json"):
            return llm_client.generate_json(prompt)
        if hasattr(llm_client, "generate"):
            return self._parse_llm_json(llm_client.generate(prompt))
        if callable(llm_client):
            response = llm_client(prompt)
            return self._parse_llm_json(response) if isinstance(response, str) else response
        raise TypeError("Unsupported LLM client. Provide a callable, generate_json(), generate(), or generate_structured().")

    @staticmethod
    def _optional_pydantic_batch_model():
        try:
            from pydantic import BaseModel, Field
        except Exception:
            return None

        class UiPathLLMFindingModel(BaseModel):
            rule_id: str
            title: str
            severity: str = Field(pattern="^(critical|high|medium|low|info|unknown)$")
            category: str
            description: str
            recommendation: str
            file_path: str | None = None
            line_start: int | None = None
            line_end: int | None = None
            verdict: str = Field(default="likely_true_positive", pattern="^(true_positive|likely_true_positive|uncertain|likely_false_positive|false_positive)$")
            confidence: float = Field(default=0.65, ge=0.0, le=1.0)
            severity_override: str = Field(default="unchanged", pattern="^(critical|high|medium|low|info|unchanged)$")
            impact_summary: str
            reasoning_summary: str
            remediation_summary: str
            related_change_risk: str = ""
            needs_human_review: bool = True
            evidence_quality: float = Field(default=0.55, ge=0.0, le=1.0)
            evidence: list[str] = Field(default_factory=list)

        class UiPathLLMFindingBatchModel(BaseModel):
            findings: list[UiPathLLMFindingModel]

        return UiPathLLMFindingBatchModel

    @staticmethod
    def _parse_llm_json(response: str) -> Any:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return json.loads(cleaned)

    @staticmethod
    def _finding_from_payload(payload: dict) -> UiPathFinding:
        evidence = payload.get("evidence", [])
        if not isinstance(evidence, list):
            evidence = [str(evidence)]
        return UiPathFinding(
            rule_id=str(payload.get("rule_id") or "UIPATH_LLM"),
            title=str(payload.get("title") or "UiPath LLM finding"),
            severity=UiPathProjectAnalyzer._choice(str(payload.get("severity") or "medium"), {"critical", "high", "medium", "low", "info", "unknown"}, "medium"),
            category=str(payload.get("category") or "uipath"),
            description=str(payload.get("description") or payload.get("reasoning_summary") or ""),
            recommendation=str(payload.get("recommendation") or payload.get("remediation_summary") or ""),
            file_path=payload.get("file_path") if isinstance(payload.get("file_path"), str) else None,
            line_start=payload.get("line_start") if isinstance(payload.get("line_start"), int) else None,
            line_end=payload.get("line_end") if isinstance(payload.get("line_end"), int) else None,
            verdict=UiPathProjectAnalyzer._choice(str(payload.get("verdict") or "likely_true_positive"), {"true_positive", "likely_true_positive", "uncertain", "likely_false_positive", "false_positive"}, "likely_true_positive"),
            confidence=UiPathProjectAnalyzer._bounded_float(payload.get("confidence"), 0.65),
            severity_override=UiPathProjectAnalyzer._choice(str(payload.get("severity_override") or "unchanged"), {"critical", "high", "medium", "low", "info", "unchanged"}, "unchanged"),
            impact_summary=str(payload.get("impact_summary") or payload.get("description") or ""),
            reasoning_summary=str(payload.get("reasoning_summary") or ""),
            remediation_summary=str(payload.get("remediation_summary") or payload.get("recommendation") or ""),
            related_change_risk=str(payload.get("related_change_risk") or ""),
            needs_human_review=bool(payload.get("needs_human_review", True)),
            evidence_quality=UiPathProjectAnalyzer._bounded_float(payload.get("evidence_quality"), 0.55),
            source="llm",
            evidence=[str(item) for item in evidence],
        )

    @staticmethod
    def _validate_llm_findings(analysis: UiPathProjectAnalysis, findings: list[UiPathFinding]) -> list[UiPathFinding]:
        valid_paths = set(analysis.xaml_files)
        valid_paths.update({"project.json", "Data/Config.xlsx"})
        valid_paths.update(analysis.reframework_missing)
        workflow_line_lookup = {workflow.path: workflow for workflow in analysis.workflows}
        validated: list[UiPathFinding] = []
        for finding in findings:
            if finding.file_path and finding.file_path not in valid_paths:
                finding.verdict = "uncertain"
                finding.confidence = min(finding.confidence, 0.35)
                finding.evidence_quality = min(finding.evidence_quality, 0.25)
                finding.needs_human_review = True
                finding.evidence.append(f"Post-validation: file_path not present in project evidence: {finding.file_path}")
            if finding.file_path in workflow_line_lookup and finding.line_start is not None:
                workflow = workflow_line_lookup[finding.file_path]
                if finding.line_start < 1:
                    finding.line_start = None
                    finding.line_end = None
                elif not UiPathProjectAnalyzer._line_supported_by_evidence(workflow, finding.line_start):
                    finding.verdict = "uncertain"
                    finding.confidence = min(finding.confidence, 0.55)
                    finding.evidence_quality = min(finding.evidence_quality, 0.45)
                    finding.needs_human_review = True
                    finding.evidence.append(f"Post-validation: cited line {finding.line_start} is not in extracted line evidence.")
            validated.append(finding)
        return validated

    @staticmethod
    def _line_supported_by_evidence(workflow: UiPathWorkflowSummary, line_number: int) -> bool:
        for lines in workflow.line_evidence.values():
            if line_number in lines:
                return True
        for lines in workflow.activity_lines.values():
            if line_number in lines:
                return True
        return False

    @staticmethod
    def _merge_findings(local_findings: list[UiPathFinding], llm_findings: list[UiPathFinding]) -> list[UiPathFinding]:
        merged: list[UiPathFinding] = []
        seen: set[str] = set()
        for finding in local_findings + llm_findings:
            key = f"{finding.rule_id}|{finding.file_path}|{finding.title}".lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(finding)
        return merged

    @staticmethod
    def _bounded_float(value: Any, default: float) -> float:
        try:
            number = float(value)
        except Exception:
            number = default
        return max(0.0, min(1.0, number))

    @staticmethod
    def _choice(value: str, allowed: set[str], default: str) -> str:
        normalized = value.strip().lower()
        return normalized if normalized in allowed else default

    @staticmethod
    def build_llm_prompt(analysis: UiPathProjectAnalysis, max_findings: int = 8) -> str:
        """Build the portable UiPath LLM findings prompt."""

        evidence = UiPathProjectAnalyzer._compressed_llm_evidence(analysis)
        return (
            "You are reviewing a UiPath automation project for project health, reliability, security, maintainability, "
            "REFramework compliance, workflow structure, selector quality, config usage, exception handling, and test coverage.\n"
            "Use only the supplied evidence. Do not invent files or workflows.\n"
            "Cite only file_path values present in xaml_files, project.json, Data/Config.xlsx, or reframework_missing.\n"
            "Use line_start and line_end when line_evidence supports the finding; otherwise use null.\n"
            "Downgrade to uncertain when evidence is indirect.\n"
            f"Return at most {max_findings} findings. Prefer precise findings with file_path evidence.\n"
            "Return JSON only matching this schema:\n"
            "{"
            '"findings":[{'
            '"rule_id":"string",'
            '"title":"string",'
            '"severity":"critical|high|medium|low|info|unknown",'
            '"category":"structure|workflow|framework|dependency|testing|reliability|configuration|security|quality|ui_automation",'
            '"description":"string",'
            '"recommendation":"string",'
            '"file_path":"string|null",'
            '"line_start":1,'
            '"line_end":1,'
            '"verdict":"true_positive|likely_true_positive|uncertain|likely_false_positive|false_positive",'
            '"confidence":0.0,'
            '"severity_override":"critical|high|medium|low|info|unchanged",'
            '"impact_summary":"string",'
            '"reasoning_summary":"string",'
            '"remediation_summary":"string",'
            '"related_change_risk":"string",'
            '"needs_human_review":true,'
            '"evidence_quality":0.0,'
            '"evidence":["string"]'
            "}]}"
            f"\nEvidence:\n{json.dumps(evidence, indent=2)}"
        )

    def _findings(self, analysis: UiPathProjectAnalysis) -> list[UiPathFinding]:
        findings: list[UiPathFinding] = []

        if not analysis.project_json_present:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH001",
                    title="Missing project manifest",
                    severity="high",
                    category="structure",
                    file_path="project.json",
                    description="The project does not include project.json, so dependencies, runtime settings, and entry points cannot be verified.",
                    recommendation="Add project.json and commit it with package dependencies and entry point configuration.",
                    evidence=["project.json was not found at the project root."],
                )
            )

        if not analysis.xaml_files:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH002",
                    title="No XAML workflows found",
                    severity="high",
                    category="workflow",
                    description="No .xaml workflow files were found, so the UiPath automation has no executable workflow evidence.",
                    recommendation="Add Main.xaml and supporting workflow files, then rescan the project.",
                    evidence=["XAML file inventory is empty."],
                )
            )

        if analysis.main_workflow and analysis.main_workflow not in analysis.xaml_files:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH003",
                    title="Configured main workflow is missing",
                    severity="high",
                    category="workflow",
                    file_path=analysis.main_workflow,
                    description="The configured main workflow is not present in the discovered XAML files.",
                    recommendation=f"Add {analysis.main_workflow} or update project.json to point to the correct entry workflow.",
                    evidence=[f"main_workflow={analysis.main_workflow}", f"xaml_files={', '.join(analysis.xaml_files) or 'none'}"],
                )
            )

        missing_invokes = self._missing_invoked_workflows(analysis)
        for workflow, missing in missing_invokes:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH004",
                    title="Invoked workflow is missing",
                    severity="high",
                    category="workflow",
                    file_path=workflow.path,
                    description="A workflow invokes another .xaml file that was not found in the project.",
                    recommendation=f"Add the invoked workflow or correct the InvokeWorkflowFile reference: {missing}.",
                    evidence=[f"{workflow.path} invokes {missing}"],
                )
            )

        if analysis.is_reframework_like and analysis.reframework_missing:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH005",
                    title="Incomplete REFramework structure",
                    severity="medium",
                    category="framework",
                    description="The project appears to follow REFramework conventions but expected framework files are missing.",
                    recommendation="Complete the expected REFramework files or document the intentional deviation.",
                    evidence=analysis.reframework_missing,
                )
            )

        if "UiPath.System.Activities" not in analysis.dependencies:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH006",
                    title="Core UiPath dependency not declared",
                    severity="medium",
                    category="dependency",
                    file_path="project.json" if analysis.project_json_present else None,
                    description="UiPath.System.Activities was not found in project dependencies.",
                    recommendation="Declare UiPath.System.Activities in project.json with the version used by the target runtime.",
                    evidence=[f"dependencies={', '.join(analysis.dependencies) or 'none'}"],
                )
            )

        if not any(path.startswith("Tests/") or "/Tests/" in path for path in analysis.xaml_files):
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH007",
                    title="No UiPath test workflows found",
                    severity="low",
                    category="testing",
                    description="No test workflows were found under Tests/, which reduces confidence in regression safety.",
                    recommendation="Add Tests/ workflows for key happy path, validation, exception, and retry scenarios.",
                    evidence=["No discovered XAML path starts with Tests/."],
                )
            )

        if analysis.workflows and not any(workflow.role == "cleanup" for workflow in analysis.workflows):
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH008",
                    title="No cleanup workflow identified",
                    severity="medium",
                    category="reliability",
                    description="No close or kill workflow was identified for recovering application state after failures.",
                    recommendation="Add CloseAllApplications.xaml, KillAllProcesses.xaml, or equivalent cleanup workflows.",
                    evidence=[workflow.path for workflow in analysis.workflows],
                )
            )

        if analysis.workflows and not any(workflow.exception_activity_count for workflow in analysis.workflows):
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH009",
                    title="No exception handling activities detected",
                    severity="medium",
                    category="reliability",
                    description="No TryCatch, RetryScope, Throw, Rethrow, or GlobalHandler activities were detected in workflow XML.",
                    recommendation="Add explicit exception handling and retry behavior around unstable application and queue interactions.",
                    evidence=["exception_activity_count is zero across all workflows."],
                )
            )

        if analysis.is_reframework_like and not any(workflow.config_references for workflow in analysis.workflows):
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH010",
                    title="REFramework project does not reference configuration",
                    severity="medium",
                    category="configuration",
                    description="The project appears REFramework-like but no Config.xlsx or in_Config references were detected in workflows.",
                    recommendation="Use Data/Config.xlsx and in_Config consistently for constants, assets, queues, and application settings.",
                    evidence=["No Config.xlsx, in_Config, queue, or Orchestrator folder references detected."],
                )
            )

        secret_workflows = [workflow for workflow in analysis.workflows if workflow.hardcoded_secret_hits]
        for workflow in secret_workflows:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH011",
                    title="Potential hardcoded secret or credential reference",
                    severity="high",
                    category="security",
                    file_path=workflow.path,
                    description="A workflow contains text that looks like a hardcoded secret, token, credential, password, or API key reference.",
                    recommendation="Move credentials and secrets to Orchestrator Assets, secure credential stores, or environment-specific configuration.",
                    evidence=workflow.hardcoded_secret_hits[:8],
                )
            )

        parse_warning_workflows = [workflow for workflow in analysis.workflows if workflow.warnings]
        for workflow in parse_warning_workflows:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH012",
                    title="Workflow XAML could not be parsed cleanly",
                    severity="medium",
                    category="quality",
                    file_path=workflow.path,
                    description="The workflow file could not be parsed as valid XML by the portable analyzer.",
                    recommendation="Open the workflow in UiPath Studio, validate it, and commit a well-formed XAML file.",
                    evidence=workflow.warnings,
                )
            )

        if analysis.workflows and not any(workflow.selectors_count for workflow in analysis.workflows):
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH013",
                    title="No selector evidence detected",
                    severity="info",
                    category="ui_automation",
                    description="No selector or object repository evidence was detected in workflow XAML.",
                    recommendation="For UI automation projects, keep stable selector or object repository evidence for critical UI interactions.",
                    evidence=["selectors_count is zero across all workflows."],
                )
            )

        for edge in analysis.workflow_graph:
            if not edge.get("exists"):
                continue
            target_workflow = self._workflow_by_path(analysis, str(edge.get("target", "")))
            if target_workflow is None:
                continue
            required_args = [
                name
                for name, direction in target_workflow.argument_directions.items()
                if direction in {"in", "io"} and not name.lower().startswith(("out_", "out"))
            ]
            mapped_args = set(str(item) for item in edge.get("argument_mappings", []))
            missing_args = [name for name in required_args if name not in mapped_args]
            if missing_args:
                findings.append(
                    UiPathFinding(
                        rule_id="UIPATH014",
                        title="Invoked workflow argument mapping is incomplete",
                        severity="medium",
                        category="workflow",
                        file_path=str(edge.get("source")),
                        line_start=edge.get("line") if isinstance(edge.get("line"), int) else None,
                        line_end=edge.get("line") if isinstance(edge.get("line"), int) else None,
                        description="A workflow invokes another workflow but does not map all required input arguments.",
                        recommendation="Pass every required in_ or io_ argument when invoking the target workflow.",
                        evidence=[
                            f"{edge.get('source')} invokes {edge.get('target')}",
                            f"missing arguments: {', '.join(missing_args)}",
                        ],
                    )
                )

        findings.extend(self._reframework_behavior_findings(analysis))

        return findings

    def _reframework_behavior_findings(self, analysis: UiPathProjectAnalysis) -> list[UiPathFinding]:
        if not analysis.is_reframework_like:
            return []
        findings: list[UiPathFinding] = []
        main_edges = [edge for edge in analysis.workflow_graph if str(edge.get("source", "")).lower().endswith("main.xaml")]
        main_targets = {Path(str(edge.get("target", ""))).name for edge in main_edges}
        missing_targets = sorted(target for target in REFRAMEWORK_MAIN_TARGETS if target not in main_targets and target not in analysis.reframework_missing)
        if missing_targets:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH015",
                    title="Main workflow does not orchestrate expected REFramework steps",
                    severity="medium",
                    category="framework",
                    file_path="Main.xaml" if "Main.xaml" in analysis.xaml_files else analysis.main_workflow,
                    description="The project appears REFramework-like, but Main.xaml does not invoke all expected framework steps found in the project.",
                    recommendation="Ensure Main.xaml orchestrates initialization, transaction retrieval, processing, status handling, and cleanup workflows.",
                    evidence=[f"missing Main.xaml invokes: {', '.join(missing_targets)}"],
                )
            )

        cleanup_paths = [workflow.path for workflow in analysis.workflows if workflow.role == "cleanup"]
        invoked_targets = {str(edge.get("target", "")).lower() for edge in analysis.workflow_graph}
        uninvoked_cleanup = [path for path in cleanup_paths if path.lower() not in invoked_targets]
        if uninvoked_cleanup:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH016",
                    title="Cleanup workflow exists but is not invoked",
                    severity="medium",
                    category="reliability",
                    file_path=uninvoked_cleanup[0],
                    description="Cleanup workflows were found but are not referenced by the workflow graph.",
                    recommendation="Invoke cleanup workflows from the main exception/finally path so failed runs recover application state.",
                    evidence=uninvoked_cleanup,
                )
            )

        get_transaction = self._workflow_by_name(analysis, "GetTransactionData.xaml")
        if get_transaction and get_transaction.queue_activity_count == 0:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH017",
                    title="Transaction retrieval workflow lacks queue activity evidence",
                    severity="medium",
                    category="framework",
                    file_path=get_transaction.path,
                    description="GetTransactionData.xaml exists but no queue or transaction item activity was detected.",
                    recommendation="Verify GetTransactionData.xaml retrieves transaction data from queue or documented data source.",
                    evidence=[f"{get_transaction.path} queue_activity_count=0"],
                )
            )

        set_status = self._workflow_by_name(analysis, "SetTransactionStatus.xaml")
        if set_status:
            status_lines = set_status.line_evidence.get("transaction_status", [])
            if not status_lines:
                findings.append(
                    UiPathFinding(
                        rule_id="UIPATH018",
                        title="Transaction status workflow lacks success/business/system status evidence",
                        severity="medium",
                        category="framework",
                        file_path=set_status.path,
                        description="SetTransactionStatus.xaml exists but expected success, business exception, or system exception status evidence was not detected.",
                        recommendation="Ensure SetTransactionStatus.xaml explicitly handles Success, Business Exception, and System Exception paths.",
                        evidence=[f"{set_status.path} has no transaction_status line evidence."],
                    )
                )

        init_settings = self._workflow_by_name(analysis, "InitAllSettings.xaml")
        if init_settings and not init_settings.config_references:
            findings.append(
                UiPathFinding(
                    rule_id="UIPATH019",
                    title="InitAllSettings does not reference configuration",
                    severity="medium",
                    category="configuration",
                    file_path=init_settings.path,
                    description="InitAllSettings.xaml exists but no Config.xlsx or in_Config evidence was detected.",
                    recommendation="Load Data/Config.xlsx and populate in_Config from InitAllSettings.xaml.",
                    evidence=[f"{init_settings.path} config_references is empty."],
                )
            )
        return findings

    @staticmethod
    def _missing_invoked_workflows(analysis: UiPathProjectAnalysis) -> list[tuple[UiPathWorkflowSummary, str]]:
        existing = {path.lower() for path in analysis.xaml_files}
        missing: list[tuple[UiPathWorkflowSummary, str]] = []
        for workflow in analysis.workflows:
            base_dir = str(Path(workflow.path).parent).replace("\\", "/")
            if base_dir == ".":
                base_dir = ""
            for invoked in workflow.invoked_workflows:
                candidates = {invoked.lower()}
                if base_dir:
                    candidates.add(f"{base_dir}/{invoked}".lower())
                if not candidates.intersection(existing):
                    missing.append((workflow, invoked))
        return missing

    @staticmethod
    def _workflow_graph(workflows: list[UiPathWorkflowSummary]) -> list[dict[str, Any]]:
        existing = {workflow.path.lower(): workflow.path for workflow in workflows}
        edges: list[dict[str, Any]] = []
        for workflow in workflows:
            base_dir = str(Path(workflow.path).parent).replace("\\", "/")
            if base_dir == ".":
                base_dir = ""
            for invoked in workflow.invoked_workflows:
                candidates = [invoked]
                if base_dir:
                    candidates.append(f"{base_dir}/{invoked}")
                target = next((existing[candidate.lower()] for candidate in candidates if candidate.lower() in existing), invoked)
                lines = workflow.line_evidence.get(f"invoke:{invoked}", [])
                edges.append(
                    {
                        "source": workflow.path,
                        "target": target,
                        "raw_target": invoked,
                        "line": lines[0] if lines else None,
                        "exists": target.lower() in existing,
                        "argument_mappings": workflow.invoked_argument_mappings.get(invoked, []),
                    }
                )
        return edges

    @staticmethod
    def _workflow_by_path(analysis: UiPathProjectAnalysis, path: str) -> UiPathWorkflowSummary | None:
        normalized = path.lower()
        return next((workflow for workflow in analysis.workflows if workflow.path.lower() == normalized), None)

    @staticmethod
    def _workflow_by_name(analysis: UiPathProjectAnalysis, name: str) -> UiPathWorkflowSummary | None:
        normalized = name.lower()
        return next((workflow for workflow in analysis.workflows if Path(workflow.path).name.lower() == normalized), None)

    @staticmethod
    def _workflow_arguments(text: str) -> tuple[list[str], dict[str, str]]:
        names: list[str] = []
        directions: dict[str, str] = {}
        for match in re.finditer(r'(?:x:Property|Argument)\b[^>]*(?:Name|x:Key)="([^"]+)"', text):
            name = match.group(1).strip()
            if not name:
                continue
            names.append(name)
            directions[name] = UiPathProjectAnalyzer._argument_direction(name)
        return UiPathProjectAnalyzer._dedupe(names), directions

    @staticmethod
    def _argument_direction(name: str) -> str:
        lowered = name.lower()
        if lowered.startswith("in_"):
            return "in"
        if lowered.startswith("out_"):
            return "out"
        if lowered.startswith("io_"):
            return "io"
        return "unknown"

    @staticmethod
    def _invoked_argument_mappings(lines: list[str]) -> dict[str, list[str]]:
        mappings: dict[str, list[str]] = {}
        for index, line in enumerate(lines):
            target_match = re.search(r'WorkflowFileName="([^"]+\.xaml)"', line)
            if not target_match:
                continue
            target = target_match.group(1).strip().replace("\\", "/")
            block = "\n".join(lines[index : min(len(lines), index + 24)])
            names = re.findall(r'(?:x:Key|Key|ArgumentName)="([^"]+)"', block)
            if not names:
                names = re.findall(r'\b(?:in|out|io)_[A-Za-z0-9_]+\b', block)
            mappings[target] = UiPathProjectAnalyzer._dedupe(names)
        return mappings

    @staticmethod
    def _line_evidence(lines: list[str]) -> dict[str, list[int]]:
        evidence: dict[str, list[int]] = {}
        patterns = {
            "config": r"Config\.xlsx|in_Config|Config\(",
            "selector": r"<\s*webctrl|<\s*wnd|selector=",
            "exception": r"TryCatch|RetryScope|BusinessRuleException|SystemException|GlobalHandler|Rethrow|Throw",
            "queue": r"GetTransactionItem|GetQueueItem|AddQueueItem|SetTransactionStatus|QueueItem|TransactionItem",
            "asset": r"GetAsset|GetCredential|GetRobotCredential",
            "transaction_status": r"Success|BusinessRuleException|Business Exception|SystemException|System Exception",
            "secret": r"password|credential|secret|token|api key|apikey",
        }
        for line_number, line in enumerate(lines, start=1):
            for key, pattern in patterns.items():
                if re.search(pattern, line, flags=re.IGNORECASE):
                    evidence.setdefault(key, []).append(line_number)
            if "WorkflowFileName" in line:
                for target in UiPathProjectAnalyzer._xaml_references(line):
                    evidence.setdefault(f"invoke:{target}", []).append(line_number)
        return evidence

    @staticmethod
    def _activity_lines(lines: list[str]) -> dict[str, list[int]]:
        result: dict[str, list[int]] = {}
        for line_number, line in enumerate(lines, start=1):
            for match in re.finditer(r"<\s*(?:[A-Za-z0-9_.-]+:)?([A-Za-z0-9_.-]+)", line):
                activity = match.group(1)
                if activity.startswith("/"):
                    continue
                result.setdefault(activity, []).append(line_number)
        return {key: values[:12] for key, values in sorted(result.items(), key=lambda item: item[0].lower())}

    @staticmethod
    def _config_references(text: str) -> list[str]:
        matches = re.findall(r"(?:Config\.xlsx|in_Config|Config\([^)]+\)|OrchestratorQueueName|OrchestratorFolderPath)", text)
        return UiPathProjectAnalyzer._dedupe(matches)

    @staticmethod
    def _hardcoded_secret_hits(text: str) -> list[str]:
        hits: list[str] = []
        for line in text.splitlines():
            lowered = line.lower()
            if any(pattern in lowered for pattern in HARDCODED_SECRET_PATTERNS):
                compact = " ".join(line.strip().split())
                if compact:
                    hits.append(compact[:180])
        return UiPathProjectAnalyzer._dedupe(hits)

    @staticmethod
    def _xaml_references(text: str) -> list[str]:
        return UiPathProjectAnalyzer._dedupe(re.findall(r"[\w ./\\-]+\.xaml", text))

    @staticmethod
    def _display_names_from_text(text: str) -> list[str]:
        return UiPathProjectAnalyzer._dedupe(re.findall(r'DisplayName="([^"]+)"', text))

    @staticmethod
    def _string_field(payload: dict, key: str) -> str | None:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _local_name(value: str) -> str:
        return value.rsplit("}", 1)[-1].split(":", 1)[-1]

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        return str(path.relative_to(root)).replace("\\", "/")

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            cleaned = value.strip().replace("\\", "/")
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
        return result


def analyze_uipath_project(
    root: str | Path,
    llm_client: Any | None = None,
    findings_mode: str = "both",
) -> dict:
    """Convenience function for copy-and-call usage on another device."""

    return UiPathProjectAnalyzer().analyze_to_dict(root, llm_client=llm_client, findings_mode=findings_mode)


def main(argv: list[str] | None = None) -> int:
    """Run the module as a tiny standalone UiPath project scanner."""

    parser = argparse.ArgumentParser(description="Analyze a UiPath project and emit structure plus findings as JSON.")
    parser.add_argument("project_path", help="Path to the UiPath project folder")
    parser.add_argument("--output", "-o", help="Optional JSON output file")
    parser.add_argument("--llm", action="store_true", help="Call an OpenAI-compatible LLM for structured UiPath findings")
    parser.add_argument("--api-key", help="LLM API key. Defaults to UIPATH_LLM_API_KEY or OPENAI_API_KEY")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL. Defaults to UIPATH_LLM_BASE_URL, OPENAI_BASE_URL, or https://api.openai.com/v1")
    parser.add_argument("--model", help="LLM model. Defaults to UIPATH_LLM_MODEL, OPENAI_MODEL, or gpt-4o-mini")
    parser.add_argument("--timeout", type=int, default=60, help="LLM HTTP timeout in seconds")
    parser.add_argument("--max-llm-findings", type=int, default=8, help="Maximum number of LLM findings to request")
    parser.add_argument(
        "--findings-mode",
        choices=["local", "llm", "both"],
        default=None,
        help="Which findings to emit. Defaults to 'both' with --llm, otherwise 'local'.",
    )
    parser.add_argument("--print-prompt", action="store_true", help="Print the UiPath LLM prompt and exit without calling the LLM")
    args = parser.parse_args(argv)

    analyzer = UiPathProjectAnalyzer()
    findings_mode = args.findings_mode or ("both" if args.llm else "local")
    if args.print_prompt:
        analysis_for_prompt = analyzer.analyze(args.project_path, findings_mode="local")
        print(analyzer.build_llm_prompt(analysis_for_prompt, max_findings=args.max_llm_findings))
        return 0
    llm_client = (
        OpenAICompatibleLLMClient(
            api_key=args.api_key,
            model=args.model,
            base_url=args.base_url,
            timeout=args.timeout,
        )
        if args.llm
        else None
    )
    if args.output:
        analysis = analyzer.write_report(
            args.project_path,
            args.output,
            llm_client=llm_client,
            max_llm_findings=args.max_llm_findings,
            findings_mode=findings_mode,
        )
    else:
        analysis = analyzer.analyze(
            args.project_path,
            llm_client=llm_client,
            max_llm_findings=args.max_llm_findings,
            findings_mode=findings_mode,
        )
    print(json.dumps(analysis.to_dict(), indent=2))
    return 1 if any(finding.severity in {"critical", "high"} for finding in analysis.findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
