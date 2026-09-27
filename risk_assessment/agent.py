"""Prioritize findings using transparent severity, context, and churn signals."""
SEVERITY = {"high": 52, "medium": 34, "low": 18}
CATEGORY = {
    "dynamic code execution": 14,
    "shell execution": 16,
    "complex function": 9,
    "broad exception": 8,
    "FIXME": 8,
    "large file": 5,
    "TODO": 4,
    "HACK": 5,
    "Vulnerability": 16,
    "Security Hotspot": 14,
    "Bug": 10,
    "Code Smell": 5,
}


def assess_risk(findings: list[dict], churn: dict) -> None:
    density = {}
    for finding in findings:
        density[finding["file"]] = density.get(finding["file"], 0) + 1
    for item in findings:
        factors = [{"name": "Severity", "points": SEVERITY[item["severity"]]},
                   {"name": "Signal type", "points": CATEGORY.get(item["category"], 0)}]
        count = churn.get(item["file"], 0)
        if count:
            factors.append({"name": "Recent file changes", "points": min(20, count * 2)})
        concentration = density[item["file"]]
        if concentration >= 4:
            factors.append({"name": "Finding concentration", "points": min(10, concentration)})
        item["priority"] = min(100, sum(f["points"] for f in factors))
        item["score_factors"] = factors
        item["confidence"] = "high" if item["category"] in {"complex function", "large file", "TODO", "FIXME", "Vulnerability", "Bug"} else "medium"
