# Portable Modules

This project now includes portable modules under [ai_repo_agent/integration_modules](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules):

- `auth_module.py`
- `prompt_validator_module.py`
- `uipath_project_module.py`

These are designed to be copied into another deployment and integrated manually with minimal dependencies.

## 1. Username/Password Login Module

File:
- [auth_module.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules/auth_module.py)

What it provides:
- `SQLiteUserStore`
- `JsonFileUserStore`
- `LoginService`
- `UserAccount`
- `AuthResult`

Behavior:
- stores users in SQLite for the integrated app flow
- also supports a JSON file store for portable copy/paste usage
- hashes passwords using PBKDF2-HMAC-SHA256 with a random salt
- supports register, authenticate, enable, and disable flows

SQLite example:

```python
import sqlite3

from ai_repo_agent.integration_modules.auth_module import SQLiteUserStore, LoginService

connection = sqlite3.connect("ai_repo_analyst.db")
connection.row_factory = sqlite3.Row
store = SQLiteUserStore(connection)
service = LoginService(store)

service.register_user("admin", "strong-password-123")
result = service.authenticate("admin", "strong-password-123")
print(result.success, result.message)
```

JSON example:

```python
from ai_repo_agent.integration_modules.auth_module import JsonFileUserStore, LoginService

store = JsonFileUserStore("users.json")
service = LoginService(store)

service.register_user("admin", "strong-password-123")
result = service.authenticate("admin", "strong-password-123")
print(result.success, result.message)
```

## 2. Prompt Validator Module

File:
- [prompt_validator_module.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules/prompt_validator_module.py)

What it provides:
- `PromptValidatorService`
- `PromptValidationRequest`
- `PromptValidationResponse`
- `PromptValidationDecision`

Behavior:
- runs local validation first
- optionally calls the configured LLM provider through the shared `ProviderBase` interface
- returns accepted/rejected status, risk level, sanitized prompt, issues, and reasoning

Example:

```python
from ai_repo_agent.core.models import AppSettings
from ai_repo_agent.llm.factory import create_provider
from ai_repo_agent.integration_modules.prompt_validator_module import (
    PromptValidationRequest,
    PromptValidatorService,
)

settings = AppSettings(
    llm_provider="gemini",
    llm_api_key="YOUR_KEY",
    llm_model="gemini-2.5-flash",
)
provider = create_provider(settings)
validator = PromptValidatorService(provider)

response = validator.validate(
    PromptValidationRequest(
        prompt="Generate a concise architecture summary for leadership.",
        use_case="presentation",
        blocked_terms=["drop database", "steal credentials"],
    )
)
print(response.accepted, response.sanitized_prompt)
```

## Manual Integration Notes

- These modules are intentionally not wired into the web server.
- You can import them where needed on another device and connect them to your own routes, CLI tools, or services.
- The login module is fully local and portable, with SQLite now used by the integrated app flow.
- The prompt validator reuses the project’s existing LLM provider abstraction, so it plugs into any provider already supported by the project.
- The UiPath project module is fully standard-library based and can be copied as a single file.

## 3. UiPath Project Analyzer And Findings Module

File:
- [uipath_project_module.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules/uipath_project_module.py)

What it provides:
- `UiPathProjectAnalyzer`
- `UiPathProjectAnalysis`
- `UiPathWorkflowSummary`
- `UiPathFinding`
- `OpenAICompatibleLLMClient`
- `analyze_uipath_project`

Behavior:
- scans a UiPath project folder
- reads `project.json`
- inventories `.xaml` workflows
- detects invoked workflows
- builds a workflow graph with source, target, line, existence, and argument mappings
- extracts workflow arguments and detects missing invoke argument mappings
- attaches line-number evidence for invokes, selectors, config, queue, assets, exceptions, secrets, and transaction status signals
- checks REFramework-style structure
- checks REFramework behavior, dependencies, tests, cleanup workflows, config references, selectors, transaction handling, and exception handling evidence
- builds a dedicated UiPath LLM prompt similar to the main app's structured finding prompts
- sends compressed high-signal evidence to the LLM instead of the full raw analysis payload
- post-validates LLM findings against discovered files and line evidence, downgrading unsupported claims to `uncertain`
- can call an OpenAI-compatible LLM endpoint using only the Python standard library
- can emit local-only findings, LLM-only findings, or both

Import example:

```python
from uipath_project_module import UiPathProjectAnalyzer

analysis = UiPathProjectAnalyzer().analyze("/path/to/uipath/project")

for finding in analysis.findings:
    print(finding.severity, finding.rule_id, finding.verdict, finding.confidence, finding.title)
```

Single-call example:

```python
from uipath_project_module import analyze_uipath_project

report = analyze_uipath_project("/path/to/uipath/project")
print(report["project_name"])
print(report["findings"])
```

Optional LLM example:

```python
from uipath_project_module import OpenAICompatibleLLMClient, UiPathProjectAnalyzer

llm = OpenAICompatibleLLMClient(
    api_key="YOUR_API_KEY",
    model="YOUR_MODEL",
)

analysis = UiPathProjectAnalyzer().analyze(
    "/path/to/uipath/project",
    llm_client=llm,
    findings_mode="llm",
)

print(analysis.llm_used, analysis.llm_error)
```

The LLM client can be:
- a callable that accepts `prompt` and returns JSON text or a dict
- an object with `generate_json(prompt)`
- an object with `generate(prompt)`
- an object with `generate_structured(prompt, response_model)` when pydantic is available

Structured finding fields:

```text
rule_id, title, severity, category, description, recommendation,
file_path, line_start, line_end, verdict, confidence, severity_override,
impact_summary, reasoning_summary, remediation_summary, related_change_risk,
needs_human_review, evidence_quality, source, evidence
```

Important analysis fields:

```text
workflow_graph, workflows[].arguments, workflows[].argument_directions,
workflows[].invoked_argument_mappings, workflows[].line_evidence,
workflows[].activity_lines
```

CLI example after copying the file to another device:

```bash
python uipath_project_module.py /path/to/uipath/project --output uipath_report.json
```

LLM CLI example:

```bash
export UIPATH_LLM_API_KEY="YOUR_API_KEY"
export UIPATH_LLM_MODEL="YOUR_MODEL"
python uipath_project_module.py /path/to/uipath/project --llm --findings-mode llm --output uipath_report.json
```

OpenAI-compatible endpoint example:

```bash
python uipath_project_module.py /path/to/uipath/project \
  --llm \
  --api-key "YOUR_API_KEY" \
  --base-url "https://api.openai.com/v1" \
  --model "YOUR_MODEL" \
  --findings-mode both \
  --output uipath_report.json
```

Prompt-only preview:

```bash
python uipath_project_module.py /path/to/uipath/project --print-prompt
```

Minimal manual integration steps:

1. Copy `uipath_project_module.py` to the target device.
2. Set `UIPATH_LLM_API_KEY` and `UIPATH_LLM_MODEL`, or pass `--api-key` and `--model`.
3. Run with `--llm --findings-mode llm`.
4. Read the generated JSON report's `findings` array.
