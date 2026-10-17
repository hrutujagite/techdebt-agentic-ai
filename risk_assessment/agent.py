"""Prioritize findings by combining finding impact with an ML estimate of bug-fix likelihood.

Each finding's priority (0 to 100) is the sum of transparent parts:

  * Severity       how serious the finding is        (up to 52 points)
  * Signal type    what kind of finding it is        (up to 16 points)
  * Model          how likely the file is to need a  (up to 30 points)
                   bug fix in future, from an XGBoost model, split across the
                   top SHAP drivers so every point is explained

If the model cannot be applied (no Git history, too few commits, no Java files, model
file or xgboost missing), the agent falls back to the earlier rule-based churn and
concentration bonuses, so the pipeline never breaks.
"""
from __future__ import annotations

from risk_assessment.model import FEATURE_LABELS, predict_file_risk

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
MAX_MODEL_POINTS = 30
HIGH_CONFIDENCE = {"complex function", "large file", "TODO", "FIXME", "Vulnerability", "Bug"}


def _split_points(total: int, weights: list[float]) -> list[int]:
    """Split ``total`` whole points in proportion to ``weights`` (largest remainder)."""
    scale = sum(weights)
    raw = [total * w / scale for w in weights]
    parts = [int(value) for value in raw]
    by_remainder = sorted(range(len(raw)), key=lambda i: raw[i] - parts[i], reverse=True)
    for index in by_remainder[: total - sum(parts)]:
        parts[index] += 1
    return parts


def _model_factors(info: dict) -> list[dict]:
    """Turn a file's predicted likelihood into score factors explained by SHAP drivers."""
    points = round(MAX_MODEL_POINTS * info["percentile"])
    if points <= 0:
        return []
    positive = [(name, value) for name, value in info["drivers"] if value > 0][:3]
    if not positive:
        return [{"name": "Model: bug-fix likelihood", "points": points}]
    shares = _split_points(points, [value for _, value in positive])
    return [
        {"name": f"Model: {FEATURE_LABELS.get(name, name)}", "points": share, "shap": round(value, 3)}
        for (name, value), share in zip(positive, shares)
        if share > 0
    ]


def assess_risk(findings: list[dict], churn: dict, repo_path: str | None = None) -> dict:
    """Score findings in place and report whether the ML model was used."""
    file_risk = predict_file_risk(repo_path) if repo_path else None
    density: dict[str, int] = {}
    for finding in findings:
        density[finding["file"]] = density.get(finding["file"], 0) + 1

    modeled = 0
    for item in findings:
        factors = [{"name": "Severity", "points": SEVERITY[item["severity"]]},
                   {"name": "Signal type", "points": CATEGORY.get(item["category"], 0)}]
        info = file_risk.get(item["file"]) if file_risk else None
        if info:
            factors.extend(_model_factors(info))
            item["bugfix_probability"] = round(info["probability"], 3)
            modeled += 1
        else:
            count = churn.get(item["file"], 0)
            if count:
                factors.append({"name": "Recent file changes", "points": min(20, count * 2)})
            concentration = density[item["file"]]
            if concentration >= 4:
                factors.append({"name": "Finding concentration", "points": min(10, concentration)})
        item["priority"] = min(100, sum(f["points"] for f in factors))
        item["score_factors"] = factors
        item["confidence"] = "high" if item["category"] in HIGH_CONFIDENCE else "medium"

    if modeled:
        detail = (f"Scored bug-fix likelihood for {len(file_risk)} files with an XGBoost model explained by SHAP, "
                  f"combined with finding severity and type ({modeled} of {len(findings)} findings used the model).")
    else:
        detail = "Model not applicable to this repository, used rule-based severity and change-frequency weighting."
    return {"model_used": modeled > 0, "detail": detail}
