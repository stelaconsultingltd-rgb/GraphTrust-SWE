"""Versioned scoring contract; no model outputs or experimental claims."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graphtrust.metrics import evaluate_runs, summarize, write_report
from graphtrust.prediction import RECORD_SCHEMA_VERSION, RESPONSE_CONTRACT_VERSION, parse_prediction, validate_prediction


def context():
    return {"case_id": "issue", "repo": "r", "condition": "rewired",
            "response_contract_version": RESPONSE_CONTRACT_VERSION,
            "visible_files": ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"],
            "visible_source_ids": ["a.py::f"], "visible_edge_ids": ["false-edge", "good-edge"],
            "known_false_edge_ids": ["false-edge"]}


def record(data=None, **changes):
    raw = json.dumps(data if data is not None else {"files": ["a.py"]})
    decoded = parse_prediction(raw)
    checked = validate_prediction(decoded, context())
    result = {"schema_version": RECORD_SCHEMA_VERSION, "response_contract_version": RESPONSE_CONTRACT_VERSION,
              "case_id": "issue", "repo": "r", "condition": "rewired", "seed": 17,
              "model_name": "fixture-only", "status": "invalid_prediction" if checked["invalid_prediction"] else "ok",
              "contract_parseable": True, "latency_seconds": 1, "raw_output": raw,
              "response": decoded, "prediction": deepcopy(decoded), **checked}
    result.update(changes)
    return result


class V2MetricsTests(unittest.TestCase):
    def score(self, run, gold=None):
        return evaluate_runs([run], {"issue": ["a.py"]} if gold is None else gold, [context()])[0]

    def test_citation_errors_do_not_erase_valid_localization(self):
        row = self.score(record({"files": ["a.py"], "citations": ["invented"]}))
        self.assertEqual(row["file_recall_at5"], 1)
        self.assertEqual(row["contract_parseable"], 1)
        self.assertEqual(row["invalid_prediction"], 1)
        self.assertEqual(row["invalid_citations"], 1)
        self.assertEqual(row["graph_citations"], 0)

    def test_literal_invalid_duplicate_slots_are_never_replaced(self):
        run = record({"files": ["./a.py", "a.py ", "../a.py", "b.py", "b.py", "a.py"]})
        row = self.score(run)
        self.assertEqual(row["file_recall_at5"], 0)
        self.assertEqual(row["predicted_files"], run["response"]["files"])
        self.assertEqual(row["invalid_files"], 3)
        self.assertEqual(row["duplicate_files"], 1)
        self.assertEqual(row["too_many_files"], 1)

    def test_metadata_is_never_normalized_to_make_invalid_prediction_valid(self):
        wrong = context()
        wrong["visible_files"] = [" a.py "]
        run = record()
        run.update(validate_prediction(run["response"], wrong))
        run["status"] = "invalid_prediction"
        row = evaluate_runs([run], {"issue": ["a.py"]}, [wrong])[0]
        self.assertEqual(row["invalid_files"], 1)
        self.assertEqual(row["file_recall_at5"], 0)

    def test_supplied_false_relationship_is_valid_and_counts_false_use(self):
        row = self.score(record({"files": ["a.py"], "citations": ["false-edge", "a.py"]}))
        self.assertEqual(row["invalid_prediction"], 0)
        self.assertEqual(row["cited_false_edges"], 1)
        self.assertEqual(row["source_citations"], 1)
        self.assertEqual(row["file_citations"], 1)

    def test_extra_fields_remain_parseable_and_recall_is_scored(self):
        row = self.score(record({"files": ["a.py"], "rationale": "fixture"}))
        self.assertEqual(row["file_recall_at5"], 1)
        self.assertEqual(row["extra_fields"], 1)
        self.assertEqual(row["parse_error"], 0)

    def test_abstain_zero_but_missing_gold_null(self):
        run = record({"files": ["a.py"], "abstain": True})
        self.assertEqual(self.score(run)["file_recall_at5"], 0)
        self.assertIsNone(self.score(run, {})["file_recall_at5"])
        self.assertIsNone(self.score(record({"files": [], "abstain": True}), {})["file_recall_at5"])

    def test_late_valid_and_invalid_outputs_are_diagnostics_with_zero_recall(self):
        for citations in ([], ["invented", "false-edge"]):
            run = record({"files": ["a.py"], "citations": citations})
            run.update(completed_status=run["status"], status="timeout", latency_seconds=91)
            row = self.score(run)
            self.assertEqual(row["file_recall_at5"], 0)
            self.assertEqual(row["contract_parseable"], 1)
            self.assertEqual(row["within_budget_contract_parseable"], 0)
            self.assertEqual(row["invalid_prediction"], bool(citations))
            self.assertEqual(row["cited_false_edges"], bool(citations))

    def test_runtime_and_parse_failures_zero_without_fabricated_response(self):
        for status, raw in (("error", None), ("timeout", None), ("interrupted", None), ("parse_error", '{"files":[')):
            run = record(status=status, raw_output=raw, contract_parseable=False, invalid_prediction=False, response=None, prediction=None)
            row = self.score(run)
            self.assertEqual(row["file_recall_at5"], 0)
            self.assertEqual(row["contract_parseable"], 0)

    def test_unknown_versions_missing_raw_or_false_classifications_fail_loudly(self):
        for mutation in ({"schema_version": "3.0"}, {"response_contract_version": "future"},
                         {"contract_parseable": False}, {"invalid_prediction": True}, {"status": "parse_error"}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.score(record(**mutation))
        run = record()
        del run["raw_output"]
        with self.assertRaisesRegex(ValueError, "raw output"):
            self.score(run)
        wrong = context()
        wrong["response_contract_version"] = "old"
        with self.assertRaises(ValueError):
            evaluate_runs([record()], {}, [wrong])

    def test_legacy_reporting_has_separate_configuration_and_original_rule(self):
        old = {"case_id": "issue", "repo": "r", "condition": "rewired", "seed": 17,
               "model_name": "fixture-only", "schema_version": "1.0", "status": "parse_error",
               "response": {"files": ["a.py"], "edge_ids": [], "source_ids": [], "abstain": False}}
        rows = evaluate_runs([old, record()], {"issue": ["a.py"]}, [context()])
        self.assertEqual([r["file_recall_at5"] for r in rows], [0, 1])
        result = summarize(rows, 0)
        self.assertEqual(len(result["models"]), 2)
        self.assertEqual(result["outcome_runs"], 2)

    def test_report_and_record_content_hash_are_traceable(self):
        run = record({"files": ["a.py"], "citations": ["invented"]})
        rows = evaluate_runs([run], {"issue": ["a.py"]}, [context()])
        expected = hashlib.sha256(json.dumps(run, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
        self.assertEqual(rows[0]["record_sha256"], expected)
        with tempfile.TemporaryDirectory() as directory, patch("graphtrust.metrics._figures", return_value=[]):
            write_report(rows, directory)
            table = (Path(directory) / "REPORT.md").read_text()
            self.assertIn("Contract parseable", table)
            self.assertIn("Invalid prediction", table)


if __name__ == "__main__":
    unittest.main()
