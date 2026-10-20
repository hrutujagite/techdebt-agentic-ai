"""LangGraph orchestration of the five agents, including the new-commit feedback loop.

    START -> repo_analysis -> code_quality -> risk_assessment -> refactor_advisory -> planning
                                                    ^                                    |
                                                    |        (HEAD moved while running)  |
                                                    +------ refresh_inputs <-------------+
                                                                                         |
                                                                           (otherwise)   v
                                                                                        END

Why the loop exists: an analysis can take a while (SonarQube lookups, LLM calls). If commits
land during it, the report would be stale the moment it is returned. After Planning, the graph
checks whether the repository's HEAD still matches the commit that was analyzed. If not,
``refresh_inputs`` works out which files the new commits touched, re-reads the repository and
its findings, and sends everything back through Risk Assessment. Everything is re-scored,
not just the touched files, because risk ranks are relative to the rest of the repository;
the expensive LLM step stays cheap because unchanged prompts are served from its cache.

The loop is bounded (MAX_REEVALUATIONS, default 2) so a repository that keeps changing can
never keep the analysis running forever. If the bound is hit while HEAD is still moving,
the report says so (``settled`` is False).
"""
from __future__ import annotations

import operator
import os
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from code_quality.agent import inspect_code
from planning.agent import build_plan
from refactor_advisory.agent import advise_all
from repo_analysis.agent import inspect_repository
from risk_assessment.agent import assess_risk

from .analysis import build_report
from .storage import commits_between, files_changed_between, head_commit

SAMPLE_FILES = 20  # affected files listed in the report (the full count is always given)


class PipelineState(TypedDict, total=False):
    root: Path
    max_files: int
    trigger: str
    inventory: dict
    findings: list
    risk_info: dict
    advice_info: dict
    plan: list
    analyzed_commit: str | None
    iteration: int
    reevaluations: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]


def max_reevaluations() -> int:
    try:
        return max(0, int(os.environ.get("MAX_REEVALUATIONS", 2)))
    except ValueError:
        return 2


# ---------------------------------------------------------------------------
# Nodes: each returns only the state it changes
# ---------------------------------------------------------------------------
def repo_analysis(state: PipelineState) -> dict:
    # Capture the commit BEFORE reading the repository, so a commit that lands
    # while we read is noticed instead of silently included in a half-read snapshot.
    commit = head_commit(state["root"])
    inventory = inspect_repository(state["root"], max_files=state["max_files"])
    return {"inventory": inventory, "analyzed_commit": commit, "trace": ["repo_analysis"]}


def code_quality(state: PipelineState) -> dict:
    findings = inspect_code(state["inventory"]["files"], project_key=state["root"].name)
    return {"findings": findings, "trace": ["code_quality"]}


def risk_assessment(state: PipelineState) -> dict:
    info = assess_risk(state["findings"], state["inventory"]["churn"], repo_path=str(state["root"]))
    return {"risk_info": info, "trace": ["risk_assessment"]}


def refactor_advisory(state: PipelineState) -> dict:
    info = advise_all(state["findings"], state["inventory"]["churn"], state["root"])
    return {"advice_info": info, "trace": ["refactor_advisory"]}


def planning(state: PipelineState) -> dict:
    return {"plan": build_plan(state["findings"]), "trace": ["planning"]}


def refresh_inputs(state: PipelineState) -> dict:
    """The feedback path: new commits landed, so re-read the repository and its findings."""
    root, previous = state["root"], state["analyzed_commit"]
    current = head_commit(root)  # again captured before re-reading
    affected = files_changed_between(root, previous, current) or []
    commits = commits_between(root, previous, current)
    inventory = inspect_repository(root, max_files=state["max_files"])
    findings = inspect_code(inventory["files"], project_key=root.name)
    touched = set(affected)
    event = {
        "from_commit": (previous or "")[:7], "to_commit": (current or "")[:7],
        "new_commits": commits["count"] if commits else None,
        "affected_total": len(affected), "affected_files": affected[:SAMPLE_FILES],
        "findings_in_affected_files": sum(f["file"] in touched for f in findings),
    }
    return {"inventory": inventory, "findings": findings, "analyzed_commit": current,
            "iteration": state.get("iteration", 0) + 1, "reevaluations": [event], "trace": ["refresh_inputs"]}


# ---------------------------------------------------------------------------
# Router: the decision that creates the feedback loop
# ---------------------------------------------------------------------------
def route_after_planning(state: PipelineState) -> str:
    analyzed = state.get("analyzed_commit")
    current = head_commit(state["root"])
    moved = bool(analyzed) and current is not None and current != analyzed
    if moved and state.get("iteration", 0) < max_reevaluations():
        return "refresh_inputs"
    return END


def build_graph():
    graph = StateGraph(PipelineState)
    for name, node in (("repo_analysis", repo_analysis), ("code_quality", code_quality),
                       ("risk_assessment", risk_assessment), ("refactor_advisory", refactor_advisory),
                       ("planning", planning), ("refresh_inputs", refresh_inputs)):
        graph.add_node(name, node)
    graph.add_edge(START, "repo_analysis")
    graph.add_edge("repo_analysis", "code_quality")
    graph.add_edge("code_quality", "risk_assessment")
    graph.add_edge("risk_assessment", "refactor_advisory")
    graph.add_edge("refactor_advisory", "planning")
    graph.add_conditional_edges("planning", route_after_planning, {"refresh_inputs": "refresh_inputs", END: END})
    graph.add_edge("refresh_inputs", "risk_assessment")  # back into Risk Assessment, as in the proposal
    return graph.compile()


def run_pipeline(root: Path, max_files: int, trigger: str = "manual") -> dict[str, Any]:
    final = build_graph().invoke(
        {"root": root, "max_files": max_files, "trigger": trigger, "iteration": 0, "reevaluations": [], "trace": []},
        {"recursion_limit": 15 + 8 * max_reevaluations()},
    )
    head = head_commit(root)
    orchestration = {
        "engine": "langgraph", "trigger": trigger, "analyzed_commit": final["analyzed_commit"],
        "iterations": final["iteration"], "reevaluations": final["reevaluations"], "trace": final["trace"],
        "settled": head is None or head == final["analyzed_commit"],
    }
    return build_report(root, final["inventory"], final["findings"], final["risk_info"],
                        final["advice_info"], final["plan"], orchestration)
