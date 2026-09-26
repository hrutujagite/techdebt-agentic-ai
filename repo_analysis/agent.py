"""Inventory source files and derive simple change and project-shape signals."""
from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path

IGNORED = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".next", "coverage", "vendor"}
EXTENSIONS = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
              ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java", ".go": "Go",
              ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C", ".h": "C/C++",
              ".rs": "Rust", ".kt": "Kotlin", ".swift": "Swift"}
MAX_FILE_BYTES = 1_000_000


def _history(root: Path) -> tuple[Counter[str], int]:
    try:
        result = subprocess.run(["git", "-C", str(root), "log", "-n", "100", "--format=%H", "--name-only"],
                                capture_output=True, text=True, timeout=10, check=False)
        if result.returncode:
            return Counter(), 0
        commits, files = 0, []
        for line in result.stdout.splitlines():
            if not line:
                continue
            if len(line) >= 32 and all(ch in "0123456789abcdef" for ch in line.lower()):
                commits += 1
            else:
                files.append(line.strip().replace("\\", "/"))
        return Counter(files), commits
    except (OSError, subprocess.TimeoutExpired):
        return Counter(), 0


def inspect_repository(root: Path, max_files: int = 5000) -> dict:
    churn, commit_count = _history(root)
    files, truncated = [], False
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED)
        for name in sorted(names):
            path = Path(directory) / name
            language = EXTENSIONS.get(path.suffix.lower())
            if not language:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                continue
            relative = path.relative_to(root).as_posix()
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files.append({"path": relative, "language": language, "size_bytes": size, "text": content,
                          "churn": churn[relative]})
            if len(files) >= max(1, max_files):
                truncated = True
                break
        if truncated:
            break
    large = sum(1 for f in files if len(f["text"].splitlines()) > 500)
    return {"files": files, "churn": churn, "commits_analyzed": commit_count,
            "health": {"source_files": len(files), "large_files": large,
                       "most_changed": [{"file": p, "commits": n} for p, n in churn.most_common(5) if p]},
            "limitations": (["File scan reached its configured limit; results may be incomplete."] if truncated else []) +
                           ["Checks are heuristic and do not replace language-specific linters, tests, or security scanners.",
                            "Git-based change signals are available only when Git history exists and Git is installed."]}
