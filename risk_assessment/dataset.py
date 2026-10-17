"""Build a labeled training table for the Risk Assessment model from Git history.

Design (avoids label leakage):
  * Pick a cutoff commit T that sits at a chosen fraction of the history.
  * Features for each file are computed ONLY from commits up to T.
  * Label = 1 if the file was touched by a bug-fix commit AFTER T
    (within an optional window), else 0.

Bug-fix commits are detected from commit messages. This is a known noisy proxy
(see the SZZ literature), so the rule is deliberately conservative: a message
must look like a fix and must not look like docs/style/build housekeeping.

Usage:
    python -m risk_assessment.dataset --repo /path/to/repo --out data.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone

FIX_RE = re.compile(
    r"\b(fix(e[sd])?|bug(s|fix)?|defect|npe|nullpointer|crash(es)?|regression|"
    r"resolve[sd]?|patch(ed)?|incorrect|wrong|broken|fail(s|ed|ure)?)\b",
    re.IGNORECASE,
)
NOISE_RE = re.compile(
    r"\b(typo|javadoc|docs?|documentation|checkstyle|formatting|whitespace|"
    r"license|changes\.xml|readme|bump|release|merge|rat|site|build|pom|"
    r"dependabot|spelling|comment(s)?|test(s)? only|typos?|grammar|warn(ing)?s?|"
    r"violations?|error[- ]?prone|lint|refactor(ing)?|cleanup|clean up)\b",
    re.IGNORECASE,
)

# Mass edits (lint sweeps, renames) are rarely real bug fixes, so commits that touch
# more than this many source files never count as bug-fix commits.
MAX_FILES_PER_FIX = 10

SEP = "\x1e"  # record separator between commits
FIELD = "\x1f"  # field separator inside the header line


def run_git(repo: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout


def is_bugfix(message: str, num_files: int = 1) -> bool:
    if num_files > MAX_FILES_PER_FIX:
        return False
    return bool(FIX_RE.search(message)) and not NOISE_RE.search(message)


BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_RE = re.compile(r"//[^\n]*")
BRANCH_RE = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?\s")
METHOD_RE = re.compile(
    r"^[ \t]*(?:(?:public|protected|private|static|final|synchronized|abstract)\s+)+"
    r"[\w<>\[\],.? ]+?\s+\w+\s*\([^;{)]*\)\s*(?:throws [\w., ]+)?\s*\{",
    re.MULTILINE,
)


def static_metrics(repo: str, sha: str, path: str) -> dict:
    """Cheap size/complexity proxies from the file as it was at the cutoff commit.

    These are approximations (regex based, no parser) but need no build step, so they
    work on any historical commit.
    """
    try:
        source = run_git(repo, "show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return {"loc": 0, "branch_count": 0, "method_count": 0}
    code = LINE_COMMENT_RE.sub("", BLOCK_COMMENT_RE.sub("", source))
    return {
        "loc": sum(1 for line in code.splitlines() if line.strip()),
        "branch_count": len(BRANCH_RE.findall(code)),
        "method_count": len(METHOD_RE.findall(code)),
    }


def parse_history(repo: str, extensions: tuple[str, ...]) -> list[dict]:
    """Return commits oldest-first, each with the source files it touched."""
    fmt = f"{SEP}%H{FIELD}%ae{FIELD}%at{FIELD}%s"
    raw = run_git(repo, "log", "--no-merges", "--numstat", f"--pretty=format:{fmt}", "--reverse")
    commits = []
    for block in raw.split(SEP):
        block = block.strip("\n")
        if not block:
            continue
        lines = block.split("\n")
        header = lines[0].split(FIELD)
        if len(header) < 4:
            continue
        sha, author, ts, subject = header[0], header[1], int(header[2]), header[3]
        files = []
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added, deleted, path = parts
            if "=>" in path or not path.endswith(extensions):
                continue
            if added == "-" or deleted == "-":
                continue
            files.append((path, int(added), int(deleted)))
        commits.append({"sha": sha, "author": author, "ts": ts, "subject": subject, "files": files})
    return commits


def build_rows(repo: str, repo_name: str, cutoff_fraction: float,
               extensions: tuple[str, ...], window_days: int | None) -> list[dict]:
    commits = parse_history(repo, extensions)
    if len(commits) < 50:
        raise SystemExit(f"{repo_name}: too little history ({len(commits)} commits)")

    cut_idx = int(len(commits) * cutoff_fraction)
    cutoff_commit = commits[cut_idx - 1]
    cutoff_ts = cutoff_commit["ts"]
    before, after = commits[:cut_idx], commits[cut_idx:]

    # Only score files that still exist at the cutoff commit.
    tree = run_git(repo, "ls-tree", "-r", "--name-only", cutoff_commit["sha"])
    existing = {p for p in tree.splitlines() if p.endswith(extensions)}

    stats = defaultdict(lambda: {
        "changes": 0, "authors": set(), "added": 0, "deleted": 0,
        "first": None, "last": None, "bugfixes": 0, "commit_sizes": [],
    })
    for c in before:
        fix = is_bugfix(c["subject"], len(c["files"]))
        for path, added, deleted in c["files"]:
            s = stats[path]
            s["changes"] += 1
            s["authors"].add(c["author"])
            s["added"] += added
            s["deleted"] += deleted
            s["first"] = c["ts"] if s["first"] is None else s["first"]
            s["last"] = c["ts"]
            s["bugfixes"] += 1 if fix else 0
            s["commit_sizes"].append(len(c["files"]))

    end_ts = cutoff_ts + window_days * 86400 if window_days else None
    future_fixes = defaultdict(int)
    for c in after:
        if end_ts and c["ts"] > end_ts:
            break
        if is_bugfix(c["subject"], len(c["files"])):
            for path, _, _ in c["files"]:
                future_fixes[path] += 1

    rows = []
    for path in sorted(existing & set(stats)):
        s = stats[path]
        metrics = static_metrics(repo, cutoff_commit["sha"], path)
        rows.append({
            "repo": repo_name,
            "file": path,
            "num_changes": s["changes"],
            "num_authors": len(s["authors"]),
            "lines_added": s["added"],
            "lines_deleted": s["deleted"],
            "churn": s["added"] + s["deleted"],
            "file_age_days": round((cutoff_ts - s["first"]) / 86400),
            "days_since_last_change": round((cutoff_ts - s["last"]) / 86400),
            "past_bugfixes": s["bugfixes"],
            "avg_files_per_commit": round(sum(s["commit_sizes"]) / len(s["commit_sizes"]), 2),
            **metrics,
            "label_future_bugfix": 1 if future_fixes[path] > 0 else 0,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to a local git clone")
    parser.add_argument("--name", help="Name stored in the repo column (default: folder name)")
    parser.add_argument("--out", required=True, help="CSV file to write")
    parser.add_argument("--cutoff", type=float, default=0.7, help="History fraction used for features")
    parser.add_argument("--window-days", type=int, default=None, help="Only count bug fixes within N days after cutoff")
    parser.add_argument("--ext", nargs="+", default=[".java"], help="Source file extensions to include")
    args = parser.parse_args()

    name = args.name or args.repo.rstrip("/\\").split("/")[-1].split("\\")[-1]
    rows = build_rows(args.repo, name, args.cutoff, tuple(args.ext), args.window_days)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    positives = sum(r["label_future_bugfix"] for r in rows)
    print(f"{name}: {len(rows)} files, {positives} labeled risky ({positives / len(rows):.0%})")


if __name__ == "__main__":
    main()
