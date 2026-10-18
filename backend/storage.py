"""SQLite memory for the analysis pipeline.

Every analysis is stored as a "run" (repository, the Git commit that was analyzed, summary
numbers) together with its findings. That memory is what lets the system say what changed
since the last analysis, and tells it when a repository has new commits and needs
re-evaluating.

The database lives in ``techdebt.db`` at the project root (override with the TECHDEBT_DB
environment variable). Storage problems never break an analysis: ``record_and_compare``
reports them in the response instead of raising.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
# Priority moves smaller than this are treated as noise, not as a real change.
PRIORITY_CHANGE_THRESHOLD = 5
LIST_LIMIT = 8      # findings listed per category in the comparison
RECENT_RUNS = 5     # runs shown in the history trend

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_key        TEXT NOT NULL,
    repo_path       TEXT NOT NULL,
    head_commit     TEXT,
    analyzed_at     TEXT NOT NULL,
    files_scanned   INTEGER,
    findings        INTEGER,
    high_priority   INTEGER,
    average_priority REAL,
    model_used      INTEGER,
    llm_upgraded    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_runs_repo ON runs (repo_key, id);
CREATE TABLE IF NOT EXISTS findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    match_key       TEXT NOT NULL,
    file            TEXT,
    line            INTEGER,
    category        TEXT,
    severity        TEXT,
    message         TEXT,
    priority        INTEGER,
    confidence      TEXT,
    advice_source   TEXT,
    explanation     TEXT,
    recommendation  TEXT,
    score_factors   TEXT
);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings (run_id);
"""


def db_path() -> Path:
    return Path(os.environ.get("TECHDEBT_DB") or ROOT / "techdebt.db")


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


def repo_key(repo_path: str | Path) -> str:
    """Stable identity for a repository (case-insensitive on Windows)."""
    return os.path.normcase(str(Path(repo_path).resolve()))


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
def _git(repo: str | Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def head_commit(repo: str | Path) -> str | None:
    """Full hash of the commit currently checked out, or None if not a Git repository."""
    return _git(repo, "rev-parse", "HEAD") or None


def commits_between(repo: str | Path, old: str | None, new: str | None, limit: int = 5) -> dict | None:
    """Commits reachable from ``new`` but not ``old`` (None if either is unknown)."""
    if not old or not new:
        return None
    count = _git(repo, "rev-list", "--count", f"{old}..{new}")
    if count is None or not count.isdigit():
        return None  # e.g. history was rewritten and the old commit no longer exists
    recent = []
    for line in (_git(repo, "log", f"--max-count={limit}", "--format=%h\t%s", f"{old}..{new}") or "").splitlines():
        short, _, subject = line.partition("\t")
        recent.append({"hash": short, "subject": subject})
    return {"count": int(count), "recent": recent}


# ---------------------------------------------------------------------------
# Saving and loading runs
# ---------------------------------------------------------------------------
def _match_keys(findings: list[dict]) -> list[tuple[str, dict]]:
    """Pair each finding with an identity that survives line-number shifts.

    Identity is file + category + message, plus an occurrence number so that several
    identical messages in one file (for example a duplicated literal) stay distinct.
    """
    seen: dict[str, int] = {}
    keyed = []
    for finding in sorted(findings, key=lambda f: (f["file"], f["line"])):
        base = f"{finding['file']}|{finding['category']}|{finding['message']}"
        seen[base] = seen.get(base, 0) + 1
        keyed.append((f"{base}#{seen[base]}", finding))
    return keyed


def save_run(conn: sqlite3.Connection, result: dict) -> int:
    findings = result["findings"]
    summary = result["summary"]
    cursor = conn.execute(
        "INSERT INTO runs (repo_key, repo_path, head_commit, analyzed_at, files_scanned, findings, "
        "high_priority, average_priority, model_used, llm_upgraded) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (repo_key(result["repository"]), result["repository"], head_commit(result["repository"]),
         datetime.now(timezone.utc).isoformat(timespec="seconds"), summary["files_scanned"],
         summary["findings"], summary["high_priority"], summary["average_priority"],
         int(any("bugfix_probability" in f for f in findings)),
         sum(f.get("advice_source") == "llm" for f in findings)),
    )
    run_id = cursor.lastrowid
    conn.executemany(
        "INSERT INTO findings (run_id, match_key, file, line, category, severity, message, priority, "
        "confidence, advice_source, explanation, recommendation, score_factors) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(run_id, key, f["file"], f["line"], f["category"], f["severity"], f["message"], f["priority"],
          f.get("confidence"), f.get("advice_source"), f.get("explanation"), f.get("recommendation"),
          json.dumps(f.get("score_factors", []))) for key, f in _match_keys(findings)],
    )
    return run_id


def latest_run(conn: sqlite3.Connection, key: str, before_id: int | None = None) -> sqlite3.Row | None:
    sql, params = "SELECT * FROM runs WHERE repo_key = ?", [key]
    if before_id is not None:
        sql, params = sql + " AND id < ?", params + [before_id]
    return conn.execute(sql + " ORDER BY id DESC LIMIT 1", params).fetchone()


def load_findings(conn: sqlite3.Connection, run_id: int) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM findings WHERE run_id = ?", (run_id,)).fetchall()
    return {row["match_key"]: {**dict(row), "score_factors": json.loads(row["score_factors"] or "[]")}
            for row in rows}


# ---------------------------------------------------------------------------
# Comparing runs
# ---------------------------------------------------------------------------
def _brief(finding: dict) -> dict:
    return {"file": finding["file"], "line": finding["line"], "category": finding["category"],
            "message": finding["message"], "priority": finding["priority"]}


def _biggest_factor_change(old: list[dict], new: list[dict]) -> str | None:
    """Name the score factor that moved most, so a priority change is explained."""
    before = {f["name"]: f["points"] for f in old}
    after = {f["name"]: f["points"] for f in new}
    deltas = {name: after.get(name, 0) - before.get(name, 0) for name in set(before) | set(after)}
    deltas = {name: delta for name, delta in deltas.items() if delta}
    if not deltas:
        return None
    name = max(deltas, key=lambda n: abs(deltas[n]))
    return f"{name} {deltas[name]:+d}"


def compare_findings(previous: dict[str, dict], current: dict[str, dict]) -> dict:
    new_keys = current.keys() - previous.keys()
    gone_keys = previous.keys() - current.keys()
    changed, unchanged = [], 0
    for key in current.keys() & previous.keys():
        delta = current[key]["priority"] - previous[key]["priority"]
        if abs(delta) >= PRIORITY_CHANGE_THRESHOLD:
            changed.append({**_brief(current[key]), "previous_priority": previous[key]["priority"],
                            "delta": delta,
                            "reason": _biggest_factor_change(previous[key]["score_factors"],
                                                             current[key]["score_factors"])})
        else:
            unchanged += 1
    return {
        "counts": {"new": len(new_keys), "resolved": len(gone_keys), "changed": len(changed), "unchanged": unchanged},
        "new": sorted((_brief(current[k]) for k in new_keys), key=lambda f: -f["priority"])[:LIST_LIMIT],
        "resolved": sorted((_brief(previous[k]) for k in gone_keys), key=lambda f: -f["priority"])[:LIST_LIMIT],
        "changed": sorted(changed, key=lambda f: -abs(f["delta"]))[:LIST_LIMIT],
    }


def _run_brief(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "analyzed_at": row["analyzed_at"], "head_commit": (row["head_commit"] or "")[:7] or None,
            "findings": row["findings"], "high_priority": row["high_priority"],
            "average_priority": row["average_priority"]}


def record_and_compare(result: dict) -> dict:
    """Store this run and describe how it differs from the previous one.

    Never raises: if the database cannot be used, the analysis result is still returned
    and the failure is reported in the history block.
    """
    try:
        with closing(_connect()) as conn, conn:
            key = repo_key(result["repository"])
            previous = latest_run(conn, key)
            previous_findings = load_findings(conn, previous["id"]) if previous else {}
            run_id = save_run(conn, result)
            current = load_findings(conn, run_id)
            current_row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            recent = [_run_brief(r) for r in conn.execute(
                "SELECT * FROM runs WHERE repo_key = ? ORDER BY id DESC LIMIT ?", (key, RECENT_RUNS))]
    except Exception as error:  # a database problem must not lose the analysis
        return {"available": False, "reason": f"History could not be saved ({type(error).__name__})."}

    history = {"available": True, "run_id": run_id, "first_run": previous is None, "recent_runs": recent,
               "previous_run": _run_brief(previous) if previous else None}
    if previous:
        history["new_commits"] = commits_between(result["repository"], previous["head_commit"],
                                                 current_row["head_commit"])
        history["head_changed"] = previous["head_commit"] != current_row["head_commit"]
        history["comparison"] = compare_findings(previous_findings, current)
        history["deltas"] = {
            "findings": current_row["findings"] - previous["findings"],
            "high_priority": current_row["high_priority"] - previous["high_priority"],
            "average_priority": round(current_row["average_priority"] - previous["average_priority"], 1),
        }
    return history


def repository_status(repo_path: str | Path) -> dict:
    """Cheap check (no analysis): has this repository moved since it was last analyzed?"""
    root = Path(repo_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Repository path must be an existing directory")
    head = head_commit(root)
    try:
        with closing(_connect()) as conn:
            previous = latest_run(conn, repo_key(root))
    except Exception:
        previous = None
    status = {"repository": str(root), "current_commit": head, "has_previous_run": previous is not None,
              "last_analyzed_at": None, "last_commit": None, "new_commits": None, "needs_reanalysis": True}
    if previous:
        status["last_analyzed_at"] = previous["analyzed_at"]
        status["last_commit"] = previous["head_commit"]
        status["new_commits"] = commits_between(root, previous["head_commit"], head)
        status["needs_reanalysis"] = bool(head) and head != previous["head_commit"]
    return status
