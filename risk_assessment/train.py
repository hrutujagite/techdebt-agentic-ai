"""Train the bug-fix likelihood model from the committed datasets.

Run from the project root (virtual environment active):

    python -m risk_assessment.train

Outputs, all written next to this file:
    model.json          the trained XGBoost model used at analysis time
    model_meta.json     training repos, settings and the evaluation table
    evaluation.csv      leave-one-repo-out results, for the report
    shap_summary.png    global SHAP plot, for the report (needs shap + matplotlib)
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from risk_assessment.dataset import MAX_FILES_PER_FIX
from risk_assessment.model import FEATURE_LABELS, FEATURES, META_PATH, MODEL_PATH

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "datasets"
EVAL_PATH = Path(__file__).with_name("evaluation.csv")
PLOT_PATH = Path(__file__).with_name("shap_summary.png")
LABEL = "label_future_bugfix"
HISTORY_ONLY = [f for f in FEATURES if f not in ("loc", "branch_count", "method_count")]
PARAMS = dict(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8,
              colsample_bytree=0.8, eval_metric="logloss")


def load_datasets() -> pd.DataFrame:
    files = sorted(glob.glob(str(DATA_DIR / "*.csv")))
    if not files:
        raise SystemExit(f"No CSV files found in {DATA_DIR}")
    return pd.concat([pd.read_csv(path) for path in files], ignore_index=True)


def new_model(seed: int) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(random_state=seed, **PARAMS)


def leave_one_repo_out(data: pd.DataFrame, seeds: int = 5) -> pd.DataFrame:
    """Train on every repo but one, test on the held-out repo, for each repo in turn."""
    rows = []
    for repo in sorted(data["repo"].unique()):
        train, test = data[data["repo"] != repo], data[data["repo"] == repo]
        y = test[LABEL]
        scores = {"repo": repo, "files": len(test), "risky": int(y.sum()),
                  "auc_change_count": roc_auc_score(y, test["num_changes"]),
                  "auc_lines_of_code": roc_auc_score(y, test["loc"])}
        for key, features in (("auc_xgb_history", HISTORY_ONLY), ("auc_xgb_all", FEATURES)):
            aucs = []
            for seed in range(seeds):
                model = new_model(seed).fit(train[features], train[LABEL])
                aucs.append(roc_auc_score(y, model.predict_proba(test[features])[:, 1]))
            scores[key] = float(np.mean(aucs))
        logistic = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
        logistic.fit(np.log1p(train[FEATURES].clip(lower=0)), train[LABEL])
        scores["auc_logreg_all"] = roc_auc_score(
            y, logistic.predict_proba(np.log1p(test[FEATURES].clip(lower=0)))[:, 1])
        rows.append(scores)
    table = pd.DataFrame(rows)
    mean_row = {"repo": "MEAN", "files": int(table["files"].sum()), "risky": int(table["risky"].sum())}
    mean_row.update({c: float(table[c].mean()) for c in table.columns if c.startswith("auc_")})
    return pd.concat([table, pd.DataFrame([mean_row])], ignore_index=True)


def save_shap_plot(model: xgb.XGBClassifier, features: pd.DataFrame) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import shap

        readable = features.rename(columns=FEATURE_LABELS)
        values = shap.TreeExplainer(model).shap_values(features)
        shap.summary_plot(values, readable, show=False)
        plt.title("What drives predicted bug-fix likelihood (SHAP)")
        plt.tight_layout()
        plt.savefig(PLOT_PATH, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Saved {PLOT_PATH.name}")
    except Exception as error:  # plotting is optional, never block training on it
        print(f"Skipped SHAP plot: {error}")


def main() -> None:
    data = load_datasets()
    print(f"Loaded {len(data)} files from {data['repo'].nunique()} repositories "
          f"({int(data[LABEL].sum())} risky, {data[LABEL].mean():.0%})\n")

    table = leave_one_repo_out(data)
    table.to_csv(EVAL_PATH, index=False)
    print("Leave-one-repo-out AUC (higher is better, 0.5 is chance):")
    print(table.round(3).to_string(index=False), "\n")

    model = new_model(0).fit(data[FEATURES], data[LABEL])
    model.get_booster().save_model(str(MODEL_PATH))
    meta = {
        "features": FEATURES,
        "repositories": {r: int((data["repo"] == r).sum()) for r in sorted(data["repo"].unique())},
        "total_files": int(len(data)),
        "risky_files": int(data[LABEL].sum()),
        "xgboost_params": PARAMS,
        "dataset_settings": {"feature_history_fraction": 0.7, "max_files_per_bugfix_commit": MAX_FILES_PER_FIX,
                             "extensions": [".java"]},
        "xgboost_version": xgb.__version__,
        "leave_one_repo_out": json.loads(table.to_json(orient="records")),
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved {MODEL_PATH.name} and {META_PATH.name}")
    save_shap_plot(model, data[FEATURES])


if __name__ == "__main__":
    main()
