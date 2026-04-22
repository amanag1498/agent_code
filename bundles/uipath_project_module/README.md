# Portable UiPath Project Module

This bundle contains a single-file portable UiPath analyzer:

```text
uipath_project_module.py
```

It uses only the Python standard library. Copy that one file to another device and run it directly.

## Run Local Findings

```bash
python uipath_project_module.py /path/to/uipath/project --output uipath_report.json
```

## Run LLM Findings

```bash
export UIPATH_LLM_API_KEY="YOUR_API_KEY"
export UIPATH_LLM_MODEL="YOUR_MODEL"

python uipath_project_module.py /path/to/uipath/project \
  --llm \
  --findings-mode llm \
  --output uipath_report.json
```

## OpenAI-Compatible Endpoint

```bash
python uipath_project_module.py /path/to/uipath/project \
  --llm \
  --api-key "YOUR_API_KEY" \
  --base-url "https://api.openai.com/v1" \
  --model "YOUR_MODEL" \
  --findings-mode both \
  --output uipath_report.json
```

## Preview Prompt

```bash
python uipath_project_module.py /path/to/uipath/project --print-prompt
```

## Python Usage

```python
from uipath_project_module import OpenAICompatibleLLMClient, UiPathProjectAnalyzer

llm = OpenAICompatibleLLMClient(api_key="YOUR_API_KEY", model="YOUR_MODEL")
analysis = UiPathProjectAnalyzer().analyze(
    "/path/to/uipath/project",
    llm_client=llm,
    findings_mode="llm",
)

for finding in analysis.findings:
    print(finding.severity, finding.rule_id, finding.title)
```

## What It Covers

- `project.json` metadata and dependencies
- `.xaml` workflow inventory
- workflow graph
- line-number evidence
- invoked workflows and missing workflow checks
- workflow arguments and invoke argument mappings
- REFramework structure and behavioral checks
- selector/config/queue/asset/exception/secret evidence
- compressed LLM prompt
- post-LLM finding validation against discovered files and line evidence

