"""Local, explainable technical-debt analysis pipeline.

The pipeline uses deterministic repository signals and keeps optional tools (Git,
LLMs, external linters) out of the critical path so it works on a fresh checkout.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".next"}
SUPPORTED = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".php", ".cs", ".cpp", ".c", ".h"}
PATTERNS = {
    "TODO": re.compile(r"\bTODO\b", re.I),
    "FIXME": re.compile(r"\bFIXME\b", re.I),
    "HACK": re.compile(r"\bHACK\b", re.I),
    "debug print": re.compile(r"\b(print\s*\(|console\.log\s*\(|debugger\s*;)", re.I),
    "broad exception": re.compile(r"except\s*:\s*$|except\s+Exception\b"),
    "long line": re.compile(r".{121,}"),
}


@dataclass
class Finding:
    file: str
    line: int
    category: str
    message: str
    severity: str
    priority: float
    explanation: str
    recommendation: str


def _git_churn(root: Path) -> Counter[str]:
    """Count recent commits touching each file; return empty data without Git."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "-n", "100", "--format=", "--name-only"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if result.returncode:
            return Counter()
        return Counter(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())
    except (OSError, subprocess.TimeoutExpired):
        return Counter()


def _python_complexity(text: str) -> list[tuple[int, str]]:
    """Return approximate complexity points (line, function) from Python AST."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    points: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        branches = sum(isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With,
                                      ast.AsyncWith, ast.comprehension, ast.IfExp, ast.BoolOp)) for n in ast.walk(node))
        if branches >= 8:
            points.append((node.lineno, node.name))
    return points


def analyze_repository(repo_path: str, max_files: int = 5000) -> dict[str, Any]:
    """Run repository, quality, risk, advisory, and planning stages in sequence."""
    root = Path(repo_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("Repository path must be an existing directory")
    churn = _git_churn(root)
    files: list[Path] = []
    for directory, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for name in names:
            path = Path(directory) / name
            if path.suffix.lower() in SUPPORTED:
                files.append(path)
                if len(files) >= max_files:
                    break
        if len(files) >= max_files:
            break

    findings: list[Finding] = []
    scanned = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        relative = path.relative_to(root).as_posix()
        file_churn = churn[relative]
        lines = text.splitlines()
        for line_no, line in enumerate(lines, 1):
            for category, pattern in PATTERNS.items():
                if pattern.search(line):
                    severity = "high" if category in {"FIXME", "broad exception"} else "medium" if category in {"TODO", "HACK"} else "low"
                    findings.append(Finding(relative, line_no, category, line.strip()[:180], severity, 0,
                                            "This pattern can leave unfinished work, hide failures, or add maintenance noise.",
                                            "Review the surrounding code, confirm the intended behavior, and replace the marker or debug code with a tracked fix."))
        if path.suffix.lower() == ".py":
            for line_no, name in _python_complexity(text):
                findings.append(Finding(relative, line_no, "complex function", f"{name} has many branching paths", "medium", 0,
                                        "Many branching paths make behavior harder to reason about and test; recent file churn increases the cost of a regression.",
                                        "Split the function into smaller units with focused tests for the branching cases."))
        if len(lines) > 500:
            findings.append(Finding(relative, 1, "large file", f"File has {len(lines)} lines", "low", 0,
                                    "Large files often accumulate unrelated responsibilities and raise the effort of safe changes.",
                                    "Look for cohesive sections that can be extracted behind small, well-named interfaces."))

    severity_weight = {"high": 55, "medium": 32, "low": 18}
    for finding in findings:
        churn_score = min(churn[finding.file] * 3, 24)
        finding.priority = round(min(100, severity_weight[finding.severity] + churn_score), 1)
        if churn_score:
            finding.explanation += f" This file appeared in {churn[finding.file]} of the last 100 commits, adding change-risk context."
    findings.sort(key=lambda f: (-f.priority, f.file, f.line))

    buckets: dict[str, list[Finding]] = {"Sprint 1": [], "Sprint 2": [], "Backlog": []}
    for finding in findings:
        buckets["Sprint 1" if finding.priority >= 65 else "Sprint 2" if finding.priority >= 40 else "Backlog"].append(finding)
    return {
        "repository": str(root), "summary": {"files_scanned": scanned, "findings": len(findings),
        "high_priority": sum(f.priority >= 65 for f in findings), "files_with_findings": len({f.file for f in findings})},
        "agents": [
            {"name": "Repository Analysis", "status": "complete", "detail": f"Scanned {scanned} source files; gathered recent Git churn where available."},
            {"name": "Code Quality", "status": "complete", "detail": f"Detected {len(findings)} maintainability signals using local source inspection."},
            {"name": "Risk Assessment", "status": "complete", "detail": "Ranked findings by severity and recent file churn with visible score factors."},
            {"name": "Refactoring Advisory", "status": "complete", "detail": "Attached a plain-language reason and suggested next step to every finding."},
            {"name": "Planning", "status": "complete", "detail": "Grouped work into Sprint 1, Sprint 2, and Backlog using priority thresholds."},
        ],
        "roadmap": [{"name": name, "items": [asdict(f) for f in items]} for name, items in buckets.items()],
        "findings": [asdict(f) for f in findings],
        "limitations": ["This first version uses heuristic source checks; it does not replace language-specific linters or security scanners.",
                        "Git churn is unavailable when Git is missing or the selected folder is not a Git repository."],
    }
