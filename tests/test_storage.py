"""Tests for SQLite persistence and run-to-run comparison.

Run from the project root:
    python -m unittest discover -s tests -t . -v
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import storage


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=Tester", *args],
                   check=True, capture_output=True)


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    commit_file(path, "a.txt", "one", "first commit")
    return path


def commit_file(repo: Path, name: str, text: str, message: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", message)


def finding(file="A.java", line=1, category="Code Smell", message="msg", priority=50, factors=None):
    return {"file": file, "line": line, "category": category, "severity": "medium", "message": message,
            "priority": priority, "confidence": "high", "advice_source": "template", "explanation": "e",
            "recommendation": "r", "score_factors": factors or [{"name": "Severity", "points": priority}]}


def result_for(repo: Path, findings: list[dict]) -> dict:
    priorities = [f["priority"] for f in findings]
    return {"repository": str(repo.resolve()), "findings": findings,
            "summary": {"files_scanned": 3, "findings": len(findings),
                        "high_priority": sum(p >= 65 for p in priorities),
                        "average_priority": round(sum(priorities) / len(priorities), 1) if priorities else 0}}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        patcher = mock.patch.dict(os.environ, {"TECHDEBT_DB": str(self.base / "history.db")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.base / "repo")

    def record(self, findings, repo=None):
        return storage.record_and_compare(result_for(repo or self.repo, findings))

    def test_first_run_has_no_comparison(self):
        history = self.record([finding()])
        self.assertTrue(history["available"])
        self.assertTrue(history["first_run"])
        self.assertNotIn("comparison", history)
        self.assertEqual(len(history["recent_runs"]), 1)

    def test_new_resolved_changed_and_unchanged_are_counted(self):
        self.record([
            finding("A.java", 1, message="a", priority=50),
            finding("B.java", 1, message="b", priority=70,
                    factors=[{"name": "Severity", "points": 40}, {"name": "Model: file size", "points": 30}]),
            finding("C.java", 1, message="c", priority=40),
        ])
        history = self.record([
            finding("A.java", 1, message="a", priority=52),   # moved by 2: noise, unchanged
            finding("B.java", 1, message="b", priority=60,
                    factors=[{"name": "Severity", "points": 40}, {"name": "Model: file size", "points": 20}]),
            finding("D.java", 1, message="d", priority=80),   # new
        ])                                                    # C.java is gone: resolved
        comparison = history["comparison"]
        self.assertEqual(comparison["counts"], {"new": 1, "resolved": 1, "changed": 1, "unchanged": 1})
        self.assertEqual(comparison["new"][0]["file"], "D.java")
        self.assertEqual(comparison["resolved"][0]["file"], "C.java")
        changed = comparison["changed"][0]
        self.assertEqual((changed["previous_priority"], changed["priority"], changed["delta"]), (70, 60, -10))
        self.assertEqual(changed["reason"], "Model: file size -10")
        self.assertEqual(history["deltas"]["findings"], 0)

    def test_line_shift_is_not_a_change(self):
        self.record([finding("A.java", 10, message="same issue")])
        history = self.record([finding("A.java", 42, message="same issue")])
        self.assertEqual(history["comparison"]["counts"], {"new": 0, "resolved": 0, "changed": 0, "unchanged": 1})

    def test_duplicate_messages_in_one_file_stay_distinct(self):
        self.record([finding("A.java", 5, message="dup"), finding("A.java", 9, message="dup")])
        history = self.record([finding("A.java", 9, message="dup")])
        self.assertEqual(history["comparison"]["counts"]["resolved"], 1)
        self.assertEqual(history["comparison"]["counts"]["new"], 0)

    def test_new_commits_are_detected_with_subjects(self):
        self.record([finding()])
        commit_file(self.repo, "b.txt", "two", "add feature b")
        commit_file(self.repo, "c.txt", "three", "fix bug in c")
        before = storage.repository_status(self.repo)
        self.assertTrue(before["needs_reanalysis"])
        self.assertEqual(before["new_commits"]["count"], 2)
        history = self.record([finding()])
        self.assertTrue(history["head_changed"])
        self.assertEqual(history["new_commits"]["count"], 2)
        self.assertEqual([c["subject"] for c in history["new_commits"]["recent"]], ["fix bug in c", "add feature b"])
        after = storage.repository_status(self.repo)
        self.assertFalse(after["needs_reanalysis"])

    def test_unchanged_head_reports_no_new_commits(self):
        self.record([finding()])
        history = self.record([finding()])
        self.assertFalse(history["head_changed"])
        self.assertEqual(history["new_commits"]["count"], 0)

    def test_repositories_have_separate_histories(self):
        other = make_repo(self.base / "other")
        self.record([finding()])
        self.assertTrue(self.record([finding()], repo=other)["first_run"])
        self.assertFalse(self.record([finding()])["first_run"])

    def test_recent_runs_are_newest_first(self):
        for _ in range(3):
            history = self.record([finding()])
        ids = [r["id"] for r in history["recent_runs"]]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(len(ids), 3)

    def test_status_for_a_never_analyzed_repository(self):
        status = storage.repository_status(self.repo)
        self.assertFalse(status["has_previous_run"])
        self.assertTrue(status["needs_reanalysis"])

    def test_status_rejects_missing_directory(self):
        with self.assertRaises(ValueError):
            storage.repository_status(self.base / "does-not-exist")

    def test_non_git_folder_is_still_recorded(self):
        plain = self.base / "plain"
        plain.mkdir()
        history = self.record([finding()], repo=plain)
        self.assertTrue(history["available"])
        self.assertIsNone(history["previous_run"])
        second = self.record([finding()], repo=plain)
        self.assertIsNone(second["new_commits"])

    def test_database_failure_does_not_raise(self):
        blocker = self.base / "blocker"
        blocker.write_text("a file, not a directory", encoding="utf-8")
        with mock.patch.dict(os.environ, {"TECHDEBT_DB": str(blocker / "nested" / "history.db")}):
            history = self.record([finding()])
        self.assertFalse(history["available"])
        self.assertIn("could not be saved", history["reason"])


if __name__ == "__main__":
    unittest.main()
