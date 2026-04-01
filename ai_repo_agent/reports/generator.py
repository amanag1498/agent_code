"""Report generation."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ai_repo_agent.core.models import CompareResult, FindingRecord, RepoSnapshotRecord, RepositoryRecord


class ReportGenerator:
    """Generate JSON, Markdown, and HTML reports."""

    def build_payload(
        self,
        repository: RepositoryRecord,
        snapshot: RepoSnapshotRecord,
        findings: list[FindingRecord],
        compare_result: CompareResult | None,
        llm_summaries: list[dict],
    ) -> dict:
        return {
            "repository": asdict(repository),
            "snapshot": asdict(snapshot),
            "findings": [asdict(finding) for finding in findings],
            "compare_result": asdict(compare_result) if compare_result else None,
            "llm_summaries": llm_summaries,
        }

    def export_json(self, output_path: Path, payload: dict) -> None:
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def export_markdown(self, output_path: Path, payload: dict) -> None:
        lines = [
            f"# AI Repo Analyst Report: {payload['repository']['name']}",
            "",
            f"- Snapshot: {payload['snapshot']['id']}",
            f"- Branch: {payload['snapshot']['branch']}",
            f"- Commit: {payload['snapshot']['commit_hash']}",
            f"- Summary: {payload['snapshot']['summary']}",
            "",
            "## Findings",
        ]
        for finding in payload["findings"][:50]:
            lines.append(f"- [{finding['severity']}] {finding['title']} ({finding['scanner_name']})")
        output_path.write_text("\n".join(lines), encoding="utf-8")

    def export_html(self, output_path: Path, payload: dict) -> None:
        rows = "".join(
            f"<tr><td>{finding['severity']}</td><td>{finding['title']}</td><td>{finding['scanner_name']}</td></tr>"
            for finding in payload["findings"][:100]
        )
        html = f"""
<html>
<body>
  <h1>AI Repo Analyst Report: {payload['repository']['name']}</h1>
  <p>{payload['snapshot']['summary']}</p>
  <table border="1" cellspacing="0" cellpadding="6">
    <tr><th>Severity</th><th>Title</th><th>Scanner</th></tr>
    {rows}
  </table>
</body>
</html>
"""
        output_path.write_text(html, encoding="utf-8")
