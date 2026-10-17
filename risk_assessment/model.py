"""Bug-fix likelihood model used by the Risk Assessment Agent.

The model is an XGBoost classifier trained by ``risk_assessment/train.py``. For any
Java repository with Git history it estimates, per file, the probability that the file
will be touched by a bug-fix commit in the future, and explains each prediction with
SHAP values.

Nothing here is imported eagerly: if xgboost, the model file, or Git history is missing,
``predict_file_risk`` returns None and the agent falls back to its rule-based scoring.
"""
from __future__ import annotations

import json
from pathlib import Path

from risk_assessment.dataset import build_rows

MODEL_PATH = Path(__file__).with_name("model.json")
META_PATH = Path(__file__).with_name("model_meta.json")

FEATURES = [
    "num_changes", "num_authors", "lines_added", "lines_deleted", "churn",
    "file_age_days", "days_since_last_change", "past_bugfixes",
    "avg_files_per_commit", "loc", "branch_count", "method_count",
]

# Plain-language names shown in the dashboard's score breakdown.
FEATURE_LABELS = {
    "num_changes": "change frequency",
    "num_authors": "number of contributors",
    "lines_added": "lines added over time",
    "lines_deleted": "lines deleted over time",
    "churn": "code churn volume",
    "file_age_days": "file age",
    "days_since_last_change": "recent activity",
    "past_bugfixes": "past bug fixes",
    "avg_files_per_commit": "commit scatter",
    "loc": "file size",
    "branch_count": "branching complexity",
    "method_count": "method count",
}

_booster = None


def _load_booster():
    global _booster
    if _booster is None:
        import xgboost as xgb

        booster = xgb.Booster()
        booster.load_model(str(MODEL_PATH))
        _booster = booster
    return _booster


def model_metadata() -> dict:
    """Training details (repos, settings, evaluation) saved next to the model."""
    return json.loads(META_PATH.read_text(encoding="utf-8"))


def predict_file_risk(repo_path: str) -> dict[str, dict] | None:
    """Score every Java file in a Git repository.

    Returns {relative_path: {"probability", "percentile", "drivers"}} where ``drivers``
    is a list of (feature, shap_value) sorted from most risk-increasing to most
    risk-decreasing. SHAP values are in log-odds units relative to the training average.
    Returns None when the model cannot be applied (no model file, xgboost missing,
    not a Git repo, too little history, or no Java files).
    """
    try:
        import numpy as np
        import xgboost as xgb

        booster = _load_booster()
        rows = build_rows(repo_path, Path(repo_path).name, 1.0, (".java",), None)
    except (Exception, SystemExit):
        return None
    if not rows:
        return None

    matrix = np.array([[float(row[name]) for name in FEATURES] for row in rows])
    data = xgb.DMatrix(matrix, feature_names=FEATURES)
    probabilities = booster.predict(data)
    # pred_contribs=True returns exact TreeSHAP values; the last column is the bias term.
    contributions = booster.predict(data, pred_contribs=True)[:, :-1]

    ranks = probabilities.argsort().argsort()
    percentiles = ranks / max(1, len(rows) - 1)

    result = {}
    for index, row in enumerate(rows):
        drivers = sorted(
            ((name, float(contributions[index][col])) for col, name in enumerate(FEATURES)),
            key=lambda pair: pair[1],
            reverse=True,
        )
        result[row["file"]] = {
            "probability": float(probabilities[index]),
            "percentile": float(percentiles[index]),
            "drivers": drivers,
        }
    return result
