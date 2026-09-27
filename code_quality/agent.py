"""Language-aware lightweight source checks with line-level evidence."""
from __future__ import annotations

import ast
import re
from code_quality.sonarqube_client import fetch_sonarqube_findings

RULES = [
    ("TODO", re.compile(r"\bTODO\b", re.I), "medium"),
    ("FIXME", re.compile(r"\bFIXME\b", re.I), "high"),
    ("HACK", re.compile(r"\bHACK\b", re.I), "medium"),
    ("debug output", re.compile(r"\b(?:print\s*\(|console\.log\s*\(|debugger\s*;|System\.out\.print)", re.I), "low"),
    ("broad exception", re.compile(r"\bexcept\s*:\s*$|\bexcept\s+Exception\b"), "medium"),
    ("long line", re.compile(r".{121,}"), "low"),
    ("dynamic code execution", re.compile(r"\b(?:eval|exec)\s*\("), "high"),
    ("shell execution", re.compile(r"subprocess\.(?:run|Popen|call|check_output)\s*\([^\n]*shell\s*=\s*True"), "high"),
    ("disabled assertion", re.compile(r"\bassert\s+False\b"), "medium"),
]


def _complexity(content: str) -> list[tuple[int, str, int]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            branches = sum(isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While,
                                              ast.ExceptHandler, ast.IfExp, ast.comprehension))
                           for child in ast.walk(node))
            if branches >= 7:
                out.append((node.lineno, node.name, branches + 1))
    return out


def _finding(path: str, line: int, category: str, message: str, severity: str) -> dict:
    return {"file": path, "line": line, "category": category, "message": message,
            "severity": severity, "priority": 0, "confidence": "medium", "explanation": "",
            "recommendation": "", "score_factors": []}


def inspect_code(files: list[dict], project_key: str | None = None) -> list[dict]:
    if project_key:
        sonar_findings = fetch_sonarqube_findings(project_key)
        if sonar_findings is not None:
            return sonar_findings

    findings = []
    for entry in files:
        path, content = entry["path"], entry["text"]
        lines = content.splitlines()
        for number, line in enumerate(lines, 1):
            if line.strip().startswith(("#", "//", "*", "/*")):
                for category, pattern, severity in RULES[:3]:
                    if pattern.search(line):
                        findings.append(_finding(path, number, category, line.strip()[:180], severity))
                continue
            for category, pattern, severity in RULES[3:]:
                if pattern.search(line):
                    findings.append(_finding(path, number, category, line.strip()[:180], severity))
        if path.endswith(".py"):
            for line, name, complexity in _complexity(content):
                findings.append(_finding(path, line, "complex function", f"{name} has an estimated complexity of {complexity}", "medium"))
            if len(lines) > 500:
                findings.append(_finding(path, 1, "large file", f"File contains {len(lines)} lines", "low"))
    return findings
