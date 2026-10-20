"""Tests for the LangGraph orchestration and its new-commit feedback loop.

Run from the project root:
    python -m unittest discover -s tests -t . -v
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import analysis, graph, storage
from tests.test_storage import commit_file, make_repo

ORDER = ["repo_analysis", "code_quality", "risk_assessment", "refactor_advisory", "planning"]
LOOP = ["refresh_inputs", "risk_assessment", "refactor_advisory", "planning"]


def make_java_repo(path: Path) -> Path:
    make_repo(path)
    commit_file(path, "Alpha.java", "class Alpha {\n  // TODO tidy this up\n}\n", "add Alpha")
    commit_file(path, "Beta.java", "class Beta {\n  // FIXME broken edge case\n}\n", "add Beta")
    return path


def strip_volatile(report: dict) -> dict:
    """Everything except how the pipeline was executed."""
    return {key: value for key, value in report.items() if key != "orchestration"}


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_java_repo(Path(self.tmp.name) / "repo")
        patcher = mock.patch.dict(os.environ, {"LLM_PROVIDER": "", "LLM_MODEL": "", "LLM_API_KEY": "",
                                               "SONAR_TOKEN": "", "MAX_REEVALUATIONS": "2"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_graph(self, trigger="manual"):
        return analysis.analyze_repository(str(self.repo), trigger=trigger)

    def commit_during(self, filename: str, text: str, times: int | None = None):
        """Wrap the advisory step so a commit lands in the middle of an analysis pass.

        ``times`` limits how many passes get a commit (None means every pass).
        """
        original = graph.advise_all
        counter = {"n": 0}

        def advise_and_commit(*args, **kwargs):
            counter["n"] += 1
            if times is None or counter["n"] <= times:
                commit_file(self.repo, filename.format(counter["n"]), text, f"late commit {counter['n']}")
            return original(*args, **kwargs)

        return mock.patch.object(graph, "advise_all", advise_and_commit), counter

    def test_graph_produces_the_same_report_as_the_sequential_pipeline(self):
        via_graph = self.run_graph()
        via_sequence = analysis._analyze_sequentially(self.repo.resolve(), 5000, "manual")
        self.assertEqual(via_graph["orchestration"]["engine"], "langgraph")
        self.assertEqual(via_sequence["orchestration"]["engine"], "sequential")
        self.assertGreater(len(via_graph["findings"]), 0)
        self.assertEqual(strip_volatile(via_graph), strip_volatile(via_sequence))

    def test_nodes_run_in_order_and_no_loop_when_nothing_changes(self):
        orchestration = self.run_graph()["orchestration"]
        self.assertEqual(orchestration["trace"], ORDER)
        self.assertEqual(orchestration["iterations"], 0)
        self.assertEqual(orchestration["reevaluations"], [])
        self.assertTrue(orchestration["settled"])
        self.assertEqual(orchestration["analyzed_commit"], storage.head_commit(self.repo))

    def test_trigger_is_recorded(self):
        self.assertEqual(self.run_graph("watch")["orchestration"]["trigger"], "watch")

    def test_commit_during_the_run_triggers_the_feedback_loop(self):
        patch, _ = self.commit_during("Late.java", "class Late {\n  // FIXME added mid-run\n}\n", times=1)
        with patch:
            report = self.run_graph()
        orchestration = report["orchestration"]
        self.assertEqual(orchestration["trace"], ORDER + LOOP)
        self.assertEqual(orchestration["iterations"], 1)
        self.assertTrue(orchestration["settled"])  # the repository stopped changing, so the loop ended itself
        event = orchestration["reevaluations"][0]
        self.assertEqual(event["affected_files"], ["Late.java"])
        self.assertEqual(event["new_commits"], 1)
        self.assertEqual(event["findings_in_affected_files"], 1)
        self.assertIn("Late.java", {f["file"] for f in report["findings"]})
        self.assertEqual(orchestration["analyzed_commit"], storage.head_commit(self.repo))

    def test_feedback_loop_is_bounded_for_a_constantly_changing_repository(self):
        patch, counter = self.commit_during("Late{}.java", "class Late {}\n")
        with patch:
            orchestration = self.run_graph()["orchestration"]
        self.assertEqual(orchestration["iterations"], 2)       # MAX_REEVALUATIONS
        self.assertEqual(len(orchestration["trace"]), len(ORDER) + 2 * len(LOOP))
        self.assertFalse(orchestration["settled"])              # honestly reported
        self.assertEqual(counter["n"], 3)                       # initial pass + 2 re-evaluations

    def test_zero_reevaluations_disables_the_loop(self):
        patch, _ = self.commit_during("Late.java", "class Late {}\n", times=1)
        with mock.patch.dict(os.environ, {"MAX_REEVALUATIONS": "0"}), patch:
            orchestration = self.run_graph()["orchestration"]
        self.assertEqual(orchestration["iterations"], 0)
        self.assertFalse(orchestration["settled"])

    def test_folder_without_git_runs_without_a_loop(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        (plain / "Solo.java").write_text("class Solo {\n  // TODO nothing\n}\n", encoding="utf-8")
        orchestration = analysis.analyze_repository(str(plain))["orchestration"]
        self.assertEqual(orchestration["engine"], "langgraph")
        self.assertEqual(orchestration["iterations"], 0)
        self.assertIsNone(orchestration["analyzed_commit"])
        self.assertTrue(orchestration["settled"])

    def test_falls_back_to_sequential_when_langgraph_is_unavailable(self):
        with mock.patch.object(analysis, "_graph_runner", lambda: None):
            report = self.run_graph()
        self.assertEqual(report["orchestration"]["engine"], "sequential")
        self.assertEqual(report["orchestration"]["trace"], ORDER)
        self.assertGreater(len(report["findings"]), 0)

    def test_saved_run_records_the_commit_that_was_analyzed(self):
        report = self.run_graph()
        analyzed = report["orchestration"]["analyzed_commit"]
        commit_file(self.repo, "After.java", "class After {}\n", "commit after analysis")
        with mock.patch.dict(os.environ, {"TECHDEBT_DB": str(Path(self.tmp.name) / "db.sqlite")}):
            storage.record_and_compare(report)
            status = storage.repository_status(self.repo)
        self.assertEqual(status["last_commit"], analyzed)
        self.assertNotEqual(status["last_commit"], storage.head_commit(self.repo))
        self.assertTrue(status["needs_reanalysis"])

    def test_files_changed_between(self):
        first = storage.head_commit(self.repo)
        commit_file(self.repo, "One.java", "class One {}\n", "one")
        commit_file(self.repo, "Two.java", "class Two {}\n", "two")
        self.assertEqual(sorted(storage.files_changed_between(self.repo, first, storage.head_commit(self.repo))),
                         ["One.java", "Two.java"])
        self.assertIsNone(storage.files_changed_between(self.repo, "deadbeef" * 5, storage.head_commit(self.repo)))
        self.assertIsNone(storage.files_changed_between(self.repo, None, first))


if __name__ == "__main__":
    unittest.main()
