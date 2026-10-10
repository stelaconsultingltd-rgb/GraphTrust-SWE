"""Independent scoring/statistical expectations, including failed attempts."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graphtrust.metrics import evaluate_runs, summarize, write_report


def record(case="issue", repo="r", condition="false", seed=1, files=None, **kwargs):
    data = {"case_id": case, "repo": repo, "condition": condition, "seed": seed,
            "model_name": "gemma-test", "status": "ok",
            "response": {"files": ["a.py"] if files is None else files,
                         "edge_ids": [], "source_ids": [], "abstain": False}}
    data.update(kwargs)
    return data


def metadata(records, false=None):
    return [{"case_id": item["case_id"], "repo": item["repo"], "condition": item["condition"],
             "visible_files": ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"],
             "visible_edge_ids": ["bad", "good"], "known_false_edge_ids": false or []}
            for item in records]


class EvaluationTests(unittest.TestCase):
    def test_recall_is_reference_file_fraction_not_any_hit(self):
        records = [record(files=["a.py", "a.py", "wrong.py", "b.py", "c.py", "f.py"])]
        scored = evaluate_runs(records, {"issue": ["a.py", "b.py", "f.py", "unseen.py"]}, metadata(records))
        self.assertEqual(scored[0]["file_recall_at5"], .5)
        self.assertEqual(scored[0]["hit_at5"], 1)
        self.assertEqual(scored[0]["coverage_ceiling"], .75)
        self.assertEqual(scored[0]["invalid_files"], 1)

    def test_invalid_paths_consume_top_five_slots(self):
        records = [record(files=["../a.py", "/a.py", "C:/a.py", "not.py", "b.py", "a.py"])]
        scored = evaluate_runs(records, {"issue": ["a.py"]}, metadata(records))
        self.assertEqual(scored[0]["file_recall_at5"], 0)
        self.assertEqual(scored[0]["invalid_files"], 4)

    def test_distinct_false_citations_are_evaluator_only(self):
        records = [record(response={"files": ["a.py"], "edge_ids": ["bad", "bad", "good", "unknown"]})]
        scored = evaluate_runs(records, {"issue": ["a.py"]}, metadata(records, ["bad"]))
        self.assertEqual(scored[0]["cited_false_edges"], 1)
        self.assertEqual(scored[0]["invalid_edge_ids"], 1)

    def test_failures_are_zero_and_not_dropped(self):
        records = [record(seed=seed, status=status) for seed, status in enumerate(["ok", "error", "timeout", "parse_error"])]
        scored = evaluate_runs(records, {"issue": ["a.py"]}, metadata(records))
        arm = summarize(scored, bootstrap_samples=0)["models"]["gemma-test"]["conditions"]["false"]
        self.assertEqual(arm["runs"], 4)
        self.assertEqual(arm["failed_runs"], 3)
        self.assertEqual(arm["metrics"]["file_recall_at5"]["mean"], .25)

    def test_empty_gold_is_disclosed_not_scored_as_miss(self):
        records = [record()]
        scored = evaluate_runs(records, {}, metadata(records))
        self.assertIsNone(scored[0]["file_recall_at5"])
        arm = summarize(scored, 0)["models"]["gemma-test"]["conditions"]["false"]
        self.assertEqual(arm["missing_gold_runs"], 1)
        self.assertEqual(arm["metrics"]["file_recall_at5"]["issues"], 0)

    def test_malformed_response_and_explicit_abstention(self):
        records = [record(seed=1, response={"files": "a.py"}),
                   record(seed=2, response={"files": ["a.py"], "abstain": True})]
        scored = evaluate_runs(records, {"issue": ["a.py"]}, metadata(records))
        self.assertEqual(scored[0]["parse_error"], 1)
        self.assertEqual(scored[1]["abstain"], 1)
        self.assertEqual([row["file_recall_at5"] for row in scored], [0, 0])

    def test_missing_or_mismatched_context_fails_loudly(self):
        records = [record(context_sha256="original")]
        with self.assertRaisesRegex(ValueError, "Missing context"):
            evaluate_runs(records, {}, [])
        contexts = metadata(records)
        contexts[0]["context_sha256"] = "altered"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            evaluate_runs(records, {}, contexts)

    def test_runner_prediction_and_invalid_output_are_compatible(self):
        records = [record(status="invalid_output", prediction={"files": ["a.py", "unknown.py"], "source_ids": [], "edge_ids": ["bad"], "abstain": False})]
        del records[0]["response"]
        row = evaluate_runs(records, {"issue": ["a.py"]}, metadata(records, ["bad"]))[0]
        self.assertEqual(row["file_recall_at5"], 0)
        self.assertEqual(row["invalid_files"], 1)
        self.assertEqual(row["cited_false_edges"], 1)
        self.assertEqual(row["parse_error"], 0)

    def test_parse_error_retains_invalid_prediction_counts(self):
        records = [record(status="parse_error", response={"files": ["missing.py"], "source_ids": [], "edge_ids": ["bad"], "abstain": False})]
        row = evaluate_runs(records, {"issue": ["a.py"]}, metadata(records, ["bad"]))[0]
        self.assertEqual(row["file_recall_at5"], 0)
        self.assertEqual(row["invalid_files"], 1)
        self.assertEqual(row["cited_false_edges"], 1)
        self.assertEqual(row["parse_error"], 1)

    def test_recall_ceiling_obeys_five_file_output_cap(self):
        records = [record()]
        row = evaluate_runs(records, {"issue": ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"]}, metadata(records))[0]
        self.assertEqual(row["source_file_coverage"], 1)
        self.assertEqual(row["coverage_ceiling"], 5 / 6)

    def test_interrupted_attempt_is_not_removed(self):
        records = [record(status="interrupted", response=None, latency_seconds=None)]
        row = evaluate_runs(records, {"issue": ["a.py"]}, metadata(records))[0]
        self.assertEqual(row["file_recall_at5"], 0)
        self.assertEqual(row["error"], 1)
        self.assertIsNone(row["latency_seconds"])


class StatisticalTests(unittest.TestCase):
    def score(self, records):
        gold = {item["case_id"]: ["a.py"] for item in records}
        return evaluate_runs(records, gold, metadata(records))

    def test_average_seeds_within_issue_before_averaging_issues(self):
        records = [record(case="one", seed=1), record(case="one", seed=2, files=[]),
                   record(case="two", seed=1)]
        arm = summarize(self.score(records), 0)["models"]["gemma-test"]["conditions"]["false"]
        self.assertEqual(arm["metrics"]["file_recall_at5"]["mean"], .75)
        self.assertEqual(arm["issues"], 2)

    def test_paired_difference_requires_equal_seed_sets(self):
        records = [record(case="one", condition="a", seed=1), record(case="one", condition="a", seed=2),
                   record(case="one", condition="b", seed=1, files=[]),
                   record(case="two", condition="a", seed=1), record(case="two", condition="b", seed=1, files=[])]
        comparison = summarize(self.score(records), 0)["models"]["gemma-test"]["paired_comparisons"][0]
        self.assertEqual(comparison["paired_issues"], 1)
        self.assertEqual(comparison["unmatched_seed_issues"], 1)
        self.assertEqual(comparison["metrics"]["file_recall_at5"]["mean"], -1)

    def test_duplicate_attempt_uses_latest_but_preserves_attempt_count(self):
        records = [record(status="timeout"), record(status="ok")]
        summary = summarize(self.score(records), 0)
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(summary["outcome_runs"], 1)
        self.assertEqual(summary["superseded_attempts"], 1)
        self.assertEqual(summary["models"]["gemma-test"]["conditions"]["false"]["metrics"]["file_recall_at5"]["mean"], 1)

    def test_model_results_never_pooled(self):
        records = [record(model_name="E2B"), record(model_name="E4B-GGUF", files=[])]
        models = summarize(self.score(records), 0)["models"]
        self.assertEqual(set(models), {"E2B", "E4B-GGUF"})
        self.assertEqual(models["E2B"]["conditions"]["false"]["metrics"]["file_recall_at5"]["mean"], 1)
        self.assertEqual(models["E4B-GGUF"]["conditions"]["false"]["metrics"]["file_recall_at5"]["mean"], 0)

    def test_changed_runtime_configuration_is_separated(self):
        records = [record(backend={"runtime": "first"}), record(backend={"runtime": "second"}, files=[])]
        models = summarize(self.score(records), 0)["models"]
        self.assertEqual(len(models), 2)
        self.assertEqual(sorted(item["conditions"]["false"]["metrics"]["file_recall_at5"]["mean"] for item in models.values()), [0, 1])

    def test_hierarchical_bootstrap_is_deterministic_and_flags_few_clusters(self):
        records = [record(case=f"{repo}-{i}", repo=repo, files=[] if i == 0 else ["a.py"])
                   for repo in ["repo-a", "repo-b", "repo-c"] for i in range(3)]
        first = summarize(self.score(records), 200, 7)
        second = summarize(self.score(list(reversed(records))), 200, 7)
        metric = first["models"]["gemma-test"]["conditions"]["false"]["metrics"]["file_recall_at5"]
        self.assertEqual(metric, second["models"]["gemma-test"]["conditions"]["false"]["metrics"]["file_recall_at5"])
        self.assertEqual(metric["issues"], 9)
        self.assertEqual(metric["repositories"], 3)
        self.assertIn("exploratory", metric["uncertainty_note"])
        self.assertLessEqual(metric["ci95"][0], metric["mean"])
        self.assertGreaterEqual(metric["ci95"][1], metric["mean"])

    def test_single_repository_does_not_claim_population_interval(self):
        records = [record(case="one"), record(case="two", files=[])]
        metric = summarize(self.score(records), 20)["models"]["gemma-test"]["conditions"]["false"]["metrics"]["file_recall_at5"]
        self.assertIsNone(metric["ci95"])
        self.assertIn("One repository", metric["uncertainty_note"])

    def test_report_is_auditable_and_synthetic_is_marked(self):
        records = [record(synthetic=True)]
        with tempfile.TemporaryDirectory() as folder, patch("graphtrust.metrics._figures", return_value=[]):
            summary = write_report(self.score(records), folder)
            root = Path(folder)
            self.assertTrue(summary["synthetic"])
            self.assertIn("SYNTHETIC DEMO", (root / "REPORT.md").read_text())
            self.assertIn("issue", (root / "results.csv").read_text())
            self.assertEqual(json.loads((root / "summary.json").read_text()), summary)


if __name__ == "__main__":
    unittest.main()
