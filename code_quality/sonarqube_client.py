"""Client for pulling real static analysis findings from a running SonarQube instance.

Reads connection details from environment variables so no token ever gets
committed to the repo:

    SONAR_URL    defaults to http://localhost:9000
    SONAR_TOKEN  required, generate this in the SonarQube dashboard

If SonarQube is unreachable or SONAR_TOKEN is not set, fetch_sonarqube_findings
returns None so the caller can fall back to the lightweight heuristic checks
instead of crashing the whole pipeline.
"""
from __future__ import annotations

import os

import requests

SONAR_URL = os.environ.get("SONAR_URL", "http://localhost:9000")
SONAR_TOKEN = os.environ.get("SONAR_TOKEN", "")

_SEVERITY_MAP = {
    "BLOCKER": "high",
    "CRITICAL": "high",
    "MAJOR": "medium",
    "MINOR": "low",
    "INFO": "low",
}


def _finding(path: str, line: int, category: str, message: str, severity: str) -> dict:
    return {
        "file": path, "line": line, "category": category, "message": message,
        "severity": severity, "priority": 0, "confidence": "medium",
        "explanation": "", "recommendation": "", "score_factors": [],
    }


def fetch_sonarqube_findings(project_key: str) -> list[dict] | None:
    """Fetch real issues from SonarQube for the given project key.

    Returns None (not an empty list) when SonarQube could not be reached at
    all, so the caller knows to fall back rather than report zero findings.
    """
    if not SONAR_TOKEN:
        return None

    findings: list[dict] = []
    page = 1
    while True:
        try:
            response = requests.get(
                f"{SONAR_URL}/api/issues/search",
                params={"componentKeys": project_key, "ps": 500, "p": page},
                auth=(SONAR_TOKEN, ""),
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None if page == 1 else findings

        data = response.json()
        for issue in data.get("issues", []):
            component = issue.get("component", "")
            file_path = component.split(":", 1)[1] if ":" in component else component
            severity = _SEVERITY_MAP.get(issue.get("severity", "MINOR"), "medium")
            category = issue.get("type", "CODE_SMELL").replace("_", " ").title()
            message = issue.get("message", "")[:180]
            line = issue.get("line") or 1
            findings.append(_finding(file_path, line, category, message, severity))

        total = data.get("paging", {}).get("total", 0)
        if page * 500 >= total:
            break
        page += 1

    return findings