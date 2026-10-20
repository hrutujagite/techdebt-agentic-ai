"""Run the five repository agents and assemble the explainable debt report.

The agents are orchestrated as a LangGraph graph (see ``backend/graph.py``), which also
provides the new-commit feedback loop. If LangGraph is not installed, the same agents run
as a plain sequence so the application keeps working; the report then says so.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from code_quality.agent import inspect_code
from planning.agent import build_plan
from refactor_advisory.agent import advise_all
from repo_analysis.agent import inspect_repository
from risk_assessment.agent import assess_risk

from .storage import head_commit

SEQUENCE = ["repo_analysis", "code_quality", "risk_assessment", "refactor_advisory", "planning"]


def build_report(root: Path, inventory: dict, findings: list[dict], risk_info: dict, advice_info: dict,
                 plan: list[dict], orchestration: dict) -> dict[str, Any]:
    """Assemble the API response from the agents' outputs (shared by both execution paths)."""
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
            {"name": "Risk Assessment", "status": "complete", "detail": risk_info["detail"]},
            {"name": "Refactoring Advisory", "status": "complete", "detail": advice_info["detail"]},
            {"name": "Planning", "status": "complete", "detail": f"Built a capacity-aware plan with {len(plan)} work groups."},
        ], "roadmap": plan, "findings": findings, "limitations": inventory["limitations"],
        "orchestration": orchestration,
    }


def _graph_runner():
    """The LangGraph pipeline, or None if LangGraph is not installed."""
    try:
        from .graph import run_pipeline
    except ImportError:
        return None
    return run_pipeline


def _analyze_sequentially(root: Path, max_files: int, trigger: str) -> dict[str, Any]:
    """Fallback: the same agents in a fixed order, without the feedback loop."""
    commit = head_commit(root)
    inventory = inspect_repository(root, max_files=max_files)
    findings = inspect_code(inventory["files"], project_key=root.name)
    risk_info = assess_risk(findings, inventory["churn"], repo_path=str(root))
    advice_info = advise_all(findings, inventory["churn"], root)
    plan = build_plan(findings)
    orchestration = {"engine": "sequential", "trigger": trigger, "analyzed_commit": commit, "iterations": 0,
                     "reevaluations": [], "trace": list(SEQUENCE), "settled": True}
    return build_report(root, inventory, findings, risk_info, advice_info, plan, orchestration)


def analyze_repository(repo_path: str, max_files: int = 5000, trigger: str = "manual") -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("Repository path must be an existing directory")
    runner = _graph_runner()
    if runner is None:
        return _analyze_sequentially(root, max_files, trigger)
    return runner(root, max_files, trigger)
