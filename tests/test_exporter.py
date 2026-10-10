"""Fabricated unit fixtures only: no model calls or empirical evidence."""
from copy import deepcopy
from contextlib import redirect_stdout
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from graphtrust.exporter import ExportBoundaryError, export_public_results
from graphtrust.cli import main
from graphtrust.io import digest, read_json, read_jsonl, write_json, write_jsonl
from graphtrust.metrics import CONDITIONS, evaluate_runs
from graphtrust.prediction import (RECORD_DIGEST_RULE, RESPONSE_CONTRACT_VERSION,
                                   canonical_record, parse_prediction, record_digest, validate_prediction)
from graphtrust.provenance import implementation_sha256

ROOT = Path(__file__).resolve().parents[1]


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="graphtrust-export-unit-")
        self.root = Path(self.tmp.name)
        self.protocol = read_json(ROOT / "configs/protocol.json")
        self.backend = {"name": "transformers", "enable_thinking": False,
                        "checkpoint_sha256": "a" * 64, "tokenizer_sha256": "b" * 64,
                        "model_path": "private/runtime/path"}
        self.generation = {"max_output_tokens": 256, "temperature": .2, "thinking": False, "timeout_seconds": 90}
        self.model = "private/model/label"
        self.contexts, self.values, self.starts = [], [], []
        source = "fixture source\n"
        for repo in self.protocol["holdout_repositories"]:
            case_id = repo.replace("/", "__") + "-unit"
            for condition in CONDITIONS:
                prompt = "\nISSUE\nfixture\nEND ISSUE\n\nSOURCE PACK\n" + source + "END SOURCE PACK\n\nRELATIONSHIPS\nfixture\nEND RELATIONSHIPS\n"
                context = {"case_id": case_id, "repo": repo, "condition": condition,
                    "response_contract_version": RESPONSE_CONTRACT_VERSION, "prompt": prompt,
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "context_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "snapshot_sha256": "c" * 64, "input_tokens": 80, "token_method": "tokenizer",
                    "visible_files": ["pkg/a.py", "pkg/b.py"], "visible_source_ids": ["pkg/a.py::<module>"],
                    "visible_edge_ids": [] if condition == "source_only" else ["e_" + "d" * 24],
                    "known_false_edge_ids": ["e_" + "d" * 24] if condition.startswith("rewired") else [],
                    "protocol_sha256": digest(self.protocol), "source_pack_rule": self.protocol["source_pack_rule"],
                    "model_edge_rule": self.protocol["model_edge_rule"]}
                self.contexts.append(context)
                for seed in (17, 42):
                    key = {"context_sha256": context["context_sha256"], "case_id": case_id, "condition": condition,
                           "model_name": self.model, "backend": self.backend, "seed": seed,
                           "generation": self.generation, "response_contract_version": RESPONSE_CONTRACT_VERSION}
                    value = {"schema_version": "2.0", "response_contract_version": RESPONSE_CONTRACT_VERSION,
                        "run_id": digest(key), "case_id": case_id, "repo": repo, "condition": condition,
                        "seed": seed, "model_name": self.model, "backend": self.backend, "generation": self.generation,
                        "source_sha256": context["source_sha256"], "context_sha256": context["context_sha256"],
                        "visible_files": context["visible_files"], "visible_source_ids": context["visible_source_ids"],
                        "visible_edge_ids": context["visible_edge_ids"], "started_at": "2026-10-10T00:00:00+00:00",
                        "synthetic": False, "input_tokens": 80, "input_token_method": "backend_tokenizer",
                        "output_tokens": 12, "latency_seconds": 1.0, "timeout_enforcement": "elapsed_after_return"}
                    self.set_output(value, context, '{"files":["pkg/a.py"],"citations":[]}')
                    self.values.append(value)
                    start = dict(value, status="started", raw_output=None, response=None, prediction=None,
                                 contract_parseable=False, invalid_prediction=False, output_tokens=None,
                                 input_token_method="tokenizer")
                    start.pop("latency_seconds")
                    for field in ("prediction_flags", "invalid_files", "invalid_citations", "valid_graph_citations", "valid_source_id_citations", "valid_file_citations"):
                        start.pop(field)
                    self.starts.append(start)
        self.manifest = {"schema_version": 2, "response_contract_version": RESPONSE_CONTRACT_VERSION,
            "stage": "holdout", "status": "prepared_not_frozen", "implementation_sha256": implementation_sha256(),
            "protocol_sha256": digest(self.protocol), "tokenizer_identity": "b" * 64,
            "source_pack_rule": self.protocol["source_pack_rule"], "model_edge_rule": self.protocol["model_edge_rule"],
            "token_method": "tokenizer", "case_ids": [c["case_id"] for c in self.contexts[::6]],
            "cases": 6, "contexts": 36,
            "shortfalls": {repo: {"requested": 10, "available": 1} for repo in self.protocol["holdout_repositories"]},
            "exclusions": [{"case_id": "excluded-unit", "reason": "private failure https://host/?secret=value"}],
            "sampling_seeds": [17, 42], "selection_uses_gold": False}
        self.freeze = {"schema_version": 2, "response_contract_version": RESPONSE_CONTRACT_VERSION,
            "status": "frozen", "protocol": self.protocol, "implementation_sha256": implementation_sha256(),
            "protocol_sha256": digest(self.protocol), "primary_model": self.model, "backend_sha256": digest(self.backend),
            "tokenizer_identity": "b" * 64, "pilot_manifest_sha256": "e" * 64, "pilot_records_sha256": "f" * 64,
            "pilot_records_file_sha256": "a" * 64, "pilot_records_digest_rule": RECORD_DIGEST_RULE,
            "parse_rate": 1., "contract_parse_rate": 1., "graph_citation_rate": .5,
            "within_budget_contract_parse_rate": 1., "observed_contract_parse_rate": 1., "invalid_prediction_rate": 0.}
        self.write()

    def tearDown(self):
        self.tmp.cleanup()

    def set_output(self, value, context, raw):
        prediction = parse_prediction(raw)
        checked = validate_prediction(prediction, context)
        value.update(raw_output=raw, prediction=prediction, response=prediction,
                     contract_parseable=True, **checked)
        value["status"] = "invalid_prediction" if checked["invalid_prediction"] else "ok"

    def write(self):
        self.manifest["contexts_sha256"] = digest(self.contexts)
        self.manifest["selection_sha256"] = digest(self.manifest["case_ids"])
        for name, rows in (("records", self.values), ("contexts", self.contexts), ("records.jsonl.attempts", self.starts)):
            write_jsonl(self.root / (name + ".jsonl"), rows)
        write_json(self.root / "manifest.json", self.manifest)
        write_json(self.root / "freeze.json", self.freeze)

    def export(self, **kwargs):
        return export_public_results(self.root / "records.jsonl", self.root / "contexts.jsonl",
                                     self.root / "manifest.json", self.root / "freeze.json", self.root / "public", **kwargs)

    def test_complete_shortfall_export_retains_all_attempts_and_hashes(self):
        with redirect_stdout(io.StringIO()) as captured:
            main(["export", "--records", str(self.root / "records.jsonl"), "--contexts", str(self.root / "contexts.jsonl"),
                  "--manifest", str(self.root / "manifest.json"), "--freeze", str(self.root / "freeze.json"),
                  "--out", str(self.root / "public")])
        result = json.loads(captured.getvalue())
        self.assertEqual(result["attempts"], 72)
        rows = read_jsonl(self.root / "public/records.jsonl")
        self.assertEqual(len(rows), len(self.values))
        self.assertEqual(rows[0]["original_record_sha256"], record_digest(self.values[0]))
        self.assertEqual(rows[0]["model_configuration_sha256"], evaluate_runs(self.values[:1], {}, self.contexts)[0]["model_configuration_sha256"])
        self.assertEqual(read_json(self.root / "public/manifest.json")["shortfalls"], self.manifest["shortfalls"])
        self.assertTrue(all(row["metrics"]["file_recall_at5"] is None for row in rows))
        context = read_jsonl(self.root / "public/contexts.jsonl")[0]
        self.assertNotIn("prompt", context)
        self.assertNotIn("known_false_edge_ids", context)
        self.assertNotIn("source", context)

    def test_malicious_nested_extras_and_invalid_slots_are_hashed_not_dropped(self):
        secret = "sk-" + "SECRET" * 8
        self.set_output(self.values[0], self.contexts[0], json.dumps({"files": [secret, "pkg/a.py", "pkg/a.py"],
            "citations": ["https://signed.example/?token=" + secret], "extra": {"credentials": secret}}))
        self.values[0]["error"] = "https://signed.example/?token=" + secret
        self.write()
        self.export()
        text = "".join(path.read_text() for path in (self.root / "public").glob("*.json*"))
        self.assertNotIn(secret, text)
        self.assertNotIn("signed.example", text)
        self.assertNotIn("private/runtime/path", text)
        self.assertNotIn("private failure", text)
        row = read_jsonl(self.root / "public/records.jsonl")[0]
        self.assertEqual([slot["rank"] for slot in row["files"]], [1, 2, 3])
        self.assertTrue(row["files"][0]["redacted"])
        self.assertEqual(row["files"][0]["original_value_sha256"], record_digest(secret))
        self.assertEqual(row["files"][1]["reference"], "pkg/a.py")
        self.assertTrue(row["invalid_prediction"])

    def test_parse_errors_and_timeouts_keep_denominators_without_raw_text(self):
        first, late = self.values[:2]
        for name in ("prediction_flags", "invalid_files", "invalid_citations", "valid_graph_citations", "valid_source_id_citations", "valid_file_citations"):
            first.pop(name)
        first.update(status="parse_error", raw_output="malformed secret response", response=None, prediction=None,
                     contract_parseable=False, invalid_prediction=False, error="https://error/?secret=value")
        late.update(status="timeout", completed_status="ok", latency_seconds=91.)
        self.write()
        self.export()
        rows = read_jsonl(self.root / "public/records.jsonl")
        self.assertEqual(len(rows), 72)
        self.assertEqual([row["status"] for row in rows[:2]], ["parse_error", "timeout"])
        self.assertTrue(rows[1]["contract_parseable"])
        self.assertFalse(rows[1]["within_budget_contract_parseable"])
        self.assertNotIn("raw_output", rows[0])
        self.assertNotIn("error", rows[0])

    def test_scored_join_publishes_only_scalar_labels(self):
        scored = evaluate_runs(self.values, {case: ["pkg/a.py"] for case in self.manifest["case_ids"]}, self.contexts)
        path = self.root / "scored.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(scored[0]))
            writer.writeheader()
            writer.writerows(scored)
        self.export(scored=path, figures=True)
        self.assertEqual(read_jsonl(self.root / "public/records.jsonl")[0]["metrics"]["file_recall_at5"], 1.)
        summary = read_json(self.root / "public/summary.json")
        arm = next(iter(summary["models"].values()))["conditions"]["clean"]
        self.assertEqual((arm["runs"], arm["issues"]), (12, 6))
        text = "".join(p.read_text() for p in (self.root / "public").glob("*.json*"))
        self.assertNotIn("reference_files", text)
        self.assertNotIn(self.model, text)
        manifest = read_json(self.root / "public/manifest.json")
        self.assertEqual(len(manifest["figures"]), 3)
        for name in manifest["figures"]:
            image = (self.root / "public" / name).read_bytes()
            self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(manifest["public_files_sha256"][name], hashlib.sha256(image).hexdigest())

    def test_scored_issue_labels_cannot_vary_by_arm_or_seed(self):
        scored = evaluate_runs(self.values, {case: ["pkg/a.py", "pkg/b.py"] for case in self.manifest["case_ids"]}, self.contexts)
        path = self.root / "inconsistent-results.csv"
        original = deepcopy(scored[0])
        for changes in ({"gold_present": False, "file_recall_at5": None, "hit_at5": None, "coverage_ceiling": None},
                        {"coverage_ceiling": .5}):
            scored[0] = dict(original, **changes)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(scored[0]))
                writer.writeheader()
                writer.writerows(scored)
            with self.subTest(changes=changes), self.assertRaises(ExportBoundaryError):
                self.export(scored=path)
        self.assertFalse((self.root / "public").exists())

    def test_primary_tokenizer_mismatch_refuses(self):
        self.freeze["tokenizer_identity"] = "9" * 64
        self.write()
        with self.assertRaises(ExportBoundaryError):
            self.export()

    def test_incomplete_or_duplicate_journal_is_refused(self):
        self.starts.pop()
        self.write()
        with self.assertRaises(ExportBoundaryError):
            self.export()
        self.assertFalse((self.root / "public").exists())

    def test_synthetic_or_legacy_inputs_are_refused_entirely(self):
        for field, value in (("synthetic", True), ("schema_version", "1.0"), ("status", "invalid_output")):
            original = deepcopy(self.values[0])
            self.values[0][field] = value
            self.write()
            with self.subTest(field=field), self.assertRaises(ExportBoundaryError):
                self.export()
            self.assertFalse((self.root / "public").exists())
            self.values[0] = original

    def test_unknown_manifest_field_and_signed_visible_metadata_refuse(self):
        self.manifest["credentials"] = {"nested": "private"}
        self.write()
        with self.assertRaises(ExportBoundaryError):
            self.export()
        self.manifest.pop("credentials")
        self.contexts[0]["visible_source_ids"] = ["https://host/?signature=private"]
        self.write()
        with self.assertRaises(ExportBoundaryError):
            self.export()
        self.assertFalse((self.root / "public").exists())

    def test_wrong_structural_shortfall_refuses(self):
        self.manifest["shortfalls"][self.protocol["holdout_repositories"][0]]["available"] = 2
        self.write()
        with self.assertRaises(ExportBoundaryError):
            self.export()

    def test_replication_requires_complete_fixed_primary_and_accepted_runtime(self):
        primary = deepcopy(self.manifest)
        primary_path = self.root / "primary.json"
        self.manifest.update(stage="replication", sampling_seeds=[17])
        self.values = [row for row in self.values if row["seed"] == 17]
        self.starts = [row for row in self.starts if row["seed"] == 17]
        self.backend.update(name="llama_cpp", model_sha256=self.backend.pop("checkpoint_sha256"))
        for value, start in zip(self.values, self.starts):
            key = {"context_sha256": value["context_sha256"], "case_id": value["case_id"], "condition": value["condition"],
                   "model_name": self.model, "backend": self.backend, "seed": 17, "generation": self.generation,
                   "response_contract_version": RESPONSE_CONTRACT_VERSION}
            value["run_id"] = start["run_id"] = digest(key)
        self.write()
        lock_path = self.root / "runtime.json"
        lock = {"status": "development_runtime_accepted", "build_and_runtime_tested": True,
            "backend_sha256": digest(self.backend), "llama_cpp_python_commit": "1652066e0af45f2313b339670ef9555e8a54e545",
            "vendored_llama_cpp_commit": "0c1e57098bba43ac29e6e3b677cdceebdd22334f", "llama_cpp_python_version": "0.3.36",
            "cuda_cmake_args": "-DGGML_CUDA=on", "jinja2_version": "3.1.6", "model_sha256": self.backend["model_sha256"],
            "wheel_path": "/kaggle/input/private-development-wheel/wheel.whl"}
        lock.update({name: "e" * 64 for name in ("built_wheel_sha256", "development_records_sha256", "build_log_sha256", "environment_sha256")})
        write_json(lock_path, lock)
        wrong = deepcopy(primary)
        wrong["shortfalls"][self.protocol["holdout_repositories"][0]]["available"] = 2
        write_json(primary_path, wrong)
        with self.assertRaises(ExportBoundaryError):
            self.export(primary_manifest=primary_path, runtime_lock=lock_path)
        write_json(primary_path, primary)
        with self.assertRaises(ExportBoundaryError):
            self.export(primary_manifest=primary_path)
        lock["build_and_runtime_tested"] = False
        write_json(lock_path, lock)
        with self.assertRaises(ExportBoundaryError):
            self.export(primary_manifest=primary_path, runtime_lock=lock_path)
        lock["build_and_runtime_tested"] = True
        write_json(lock_path, lock)
        self.assertEqual(self.export(primary_manifest=primary_path, runtime_lock=lock_path)["attempts"], 36)
        self.assertEqual(read_json(self.root / "public/manifest.json")["shortfalls"], primary["shortfalls"])
        self.assertNotIn(lock["wheel_path"], (self.root / "public/manifest.json").read_text())

    def test_raw_classification_run_identity_and_journal_tampering_refuse(self):
        original = deepcopy(self.values[0])
        for field, altered in (("raw_output", '{"files":["pkg/b.py"]}'), ("run_id", "0" * 64), ("output_tokens", 1.5)):
            self.values[0] = dict(original, **{field: altered})
            self.write()
            with self.subTest(field=field), self.assertRaises(ExportBoundaryError):
                self.export()
        self.values[0] = original
        self.starts[0]["prediction"] = {"files": ["pkg/a.py"]}
        self.write()
        with self.assertRaises(ExportBoundaryError):
            self.export()
        self.assertFalse((self.root / "public").exists())

    def test_private_values_in_unknown_freeze_fields_or_model_hash_cannot_escape(self):
        secret = "https://private.example/?credential=sk-" + "X" * 40
        self.freeze["private_metadata"] = {"nested": secret}
        self.write()
        with self.assertRaises(ExportBoundaryError) as error:
            self.export()
        self.assertNotIn(secret, str(error.exception))
        self.freeze.pop("private_metadata")
        self.backend["model_sha256"] = secret
        self.write()
        with self.assertRaises(ExportBoundaryError) as error:
            self.export()
        self.assertNotIn(secret, str(error.exception))
        self.assertFalse((self.root / "public").exists())

    def test_case_id_container_and_snapshot_mismatch_refuse(self):
        identities = self.manifest["case_ids"]
        self.manifest["case_ids"] = {case_id: {"private": "https://private/?secret=value"} for case_id in identities}
        self.write()
        with self.assertRaises(ExportBoundaryError):
            self.export()
        self.manifest["case_ids"] = identities
        self.contexts[1]["snapshot_sha256"] = "9" * 64
        self.write()
        with self.assertRaises(ExportBoundaryError):
            self.export()
        self.assertFalse((self.root / "public").exists())

    def test_rejected_literal_surrogate_raw_response_preserves_hash_and_failure(self):
        first = self.values[0]
        for name in ("prediction_flags", "invalid_files", "invalid_citations", "valid_graph_citations", "valid_source_id_citations", "valid_file_citations"):
            first.pop(name)
        first.update(status="parse_error", raw_output='{"files":["' + chr(0xD800) + '.py"]}',
                     response=None, prediction=None, contract_parseable=False, invalid_prediction=False)
        (self.root / "records.jsonl").write_text("\n".join(canonical_record(row) for row in self.values) + "\n", encoding="utf-8")
        self.export()
        public = read_jsonl(self.root / "public/records.jsonl")[0]
        self.assertEqual(public["status"], "parse_error")
        self.assertEqual(public["original_record_sha256"], record_digest(first))
        self.assertNotIn("raw_output", public)

    def test_existing_export_is_not_overwritten(self):
        self.export()
        before = (self.root / "public/manifest.json").read_bytes()
        with self.assertRaises(ExportBoundaryError):
            self.export()
        self.assertEqual(before, (self.root / "public/manifest.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
