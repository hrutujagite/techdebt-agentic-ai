"""Orchestrate the five repository agents into an explainable debt report."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from code_quality.agent import inspect_code
from planning.agent import build_plan
from refactor_advisory.agent import advise
from repo_analysis.agent import inspect_repository
from risk_assessment.agent import assess_risk


def analyze_repository(repo_path: str, max_files: int = 5000) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("Repository path must be an existing directory")
    inventory = inspect_repository(root, max_files=max_files)
    findings = inspect_code(inventory["files"])
    assess_risk(findings, inventory["churn"])
    for finding in findings:
        advise(finding, inventory["churn"].get(finding["file"], 0))
    plan = build_plan(findings)
    languages: dict[str, int] = {}
    for entry in inventory["files"]:
        languages[entry["language"]] = languages.get(entry["language"], 0) + 1
    return {
        "repository": str(root), "summary": {
            "files_scanned": len(inventory["files"]), "findings": len(findings),
            "high_priority": sum(f["priority"] >= 65 for f in findings),
            "files_with_findings": len({f["file"] for f in findings}), "languages": languages,
            "commits_analyzed": inventory["commits_analyzed"],
            "average_priority": round(sum(f["priority"] for f in findings) / len(findings), 1) if findings else 0,
        }, "repository_health": inventory["health"],
        "agents": [
            {"name": "Repository Analysis", "status": "complete", "detail": f"Mapped {len(inventory['files'])} files across {len(languages)} languages; inspected {inventory['commits_analyzed']} recent commits."},
            {"name": "Code Quality", "status": "complete", "detail": f"Found {len(findings)} maintainability and safety signals."},
            {"name": "Risk Assessment", "status": "complete", "detail": "Combined finding severity, local code context, and recent change activity."},
            {"name": "Refactoring Advisory", "status": "complete", "detail": "Generated tailored remediation advice with evidence for every finding."},
            {"name": "Planning", "status": "complete", "detail": f"Built a capacity-aware plan with {len(plan)} work groups."},
        ], "roadmap": plan, "findings": findings, "limitations": inventory["limitations"],
    }
