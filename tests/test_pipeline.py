"""Research-integrity regressions, using temporary artifacts without a model."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from graphtrust.graph import build_graph
from graphtrust.io import digest, read_json, read_jsonl, write_json, write_jsonl
from graphtrust.pipeline import _packed_source_graph, create_contexts, freeze_protocol, load_graph, materialize_case, prepare_case, save_graph
from graphtrust.provenance import extractor_sha256, implementation_sha256
from graphtrust.prediction import RECORD_SCHEMA_VERSION, RESPONSE_CONTRACT_VERSION, validate_prediction


ROOT = Path(__file__).resolve().parents[1]


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.protocol = read_json(ROOT / "configs/protocol.json")
        source = "SOURCE sample.py::f FILE sample.py LINES 1-2 TRUNCATED false\ndef f():\n    pass\nEND SOURCE\n"
        self.contexts = []
        for issue in range(self.protocol["pilot_issues"]):
            repo = self.protocol["development_repositories"][issue % 4]
            for condition in self.protocol["conditions"]:
                prompt = f"ISSUE\nissue {issue}\nEND ISSUE\nSOURCE PACK\n{source}END SOURCE PACK\nRELATIONSHIPS\n{condition}\nEND RELATIONSHIPS\n"
                self.contexts.append({"case_id": f"dev-{issue}", "repo": repo, "condition": condition,
                                      "prompt": prompt, "context_sha256": text_hash(prompt),
                                      "source_sha256": text_hash(source), "input_tokens": len(prompt),
                                      "token_method": "tokenizer", "response_contract_version": RESPONSE_CONTRACT_VERSION,
                                      "visible_files": ["sample.py"], "visible_source_ids": ["sample.py::f"],
                                      "visible_edge_ids": ["edge-1"] if condition != "source_only" else []})
        self.backend = {"name": "transformers", "resolved_revision": "a" * 40,
                        "chat_template_sha256": "b" * 64, "enable_thinking": False,
                        "tokenizer_sha256": "c" * 64}
        self.generation = {"max_output_tokens": self.protocol["max_output_tokens"],
                           "temperature": self.protocol["temperature"], "thinking": False,
                           "timeout_seconds": self.protocol["timeout_seconds"]}
        self.records = [{"case_id": row["case_id"], "repo": row["repo"], "condition": row["condition"], "seed": seed,
                         "model_name": "pinned-e2b", "status": "ok", "synthetic": False,
                         "source_sha256": row["source_sha256"], "context_sha256": row["context_sha256"],
                         "input_tokens": row["input_tokens"], "output_tokens": 20, "latency_seconds": 1,
                         "backend": deepcopy(self.backend), "generation": deepcopy(self.generation),
                         "response": {"files": ["sample.py"],
                                      "citations": ["edge-1"] if row["condition"] == "clean" else [], "abstain": False}}
                        for row in self.contexts for seed in self.protocol["sampling_seeds_primary"]]
        for record in self.records:
            arm = next(c for c in self.contexts if c["case_id"] == record["case_id"] and c["condition"] == record["condition"])
            record.update(schema_version=RECORD_SCHEMA_VERSION, response_contract_version=RESPONSE_CONTRACT_VERSION,
                          contract_parseable=True, prediction=deepcopy(record["response"]),
                          raw_output=json.dumps(record["response"]))
            record.update(validate_prediction(record["response"], arm))

    def write_pilot(self):
        case_ids = sorted({row["case_id"] for row in self.contexts})
        write_json(self.root / "manifest.json", {"schema_version": 2, "response_contract_version": RESPONSE_CONTRACT_VERSION,
                   "stage": "pilot", "token_method": "tokenizer",
                   "protocol_sha256": digest(self.protocol), "contexts_sha256": digest(self.contexts),
                   "cases": self.protocol["pilot_issues"], "case_ids": case_ids,
                   "selection_sha256": digest(case_ids), "implementation_sha256": implementation_sha256(),
                   "contexts": len(self.contexts), "tokenizer_identity": "c" * 64})
        write_jsonl(self.root / "contexts.jsonl", self.contexts)
        (self.root / "records.jsonl").write_text("".join(json.dumps(r, ensure_ascii=True) + "\n" for r in self.records), encoding="utf-8")

    def freeze(self):
        self.write_pilot()
        return freeze_protocol(self.protocol, self.root, self.root / "frozen.json")

    def test_complete_consistent_pilot_freezes(self):
        result = self.freeze()
        self.assertEqual(result["status"], "frozen")
        self.assertEqual(result["parse_rate"], 1)
        self.assertEqual(result["graph_citation_rate"], 1)
        self.assertEqual(result["backend_sha256"], digest(self.backend))

    def test_synthetic_or_mock_records_cannot_freeze(self):
        for mutation in ({"synthetic": True}, {"backend": {"name": "mock"}}):
            with self.subTest(mutation=mutation):
                original = self.records[0]
                self.records[0] = dict(original, **mutation)
                with self.assertRaises(ValueError):
                    self.freeze()
                self.records[0] = original

    def test_stale_prompt_or_source_record_is_rejected(self):
        for field in ("context_sha256", "source_sha256"):
            with self.subTest(field=field):
                original = self.records[0][field]
                self.records[0][field] = "stale"
                with self.assertRaisesRegex(ValueError, "Stale|hash"):
                    self.freeze()
                self.records[0][field] = original

    def test_prompt_hash_is_verified_independently_of_manifest(self):
        self.contexts[0]["prompt"] += "changed after tokenization"
        with self.assertRaisesRegex(ValueError, "prompt hash"):
            self.freeze()

    def test_mixed_runtime_cannot_hide_behind_one_model_label(self):
        self.records[0]["backend"]["resolved_revision"] = "d" * 40
        with self.assertRaisesRegex(ValueError, "mixed runtime"):
            self.freeze()

    def test_generation_change_is_rejected(self):
        for field, value in (("thinking", True), ("max_output_tokens", 999), ("temperature", 0.7), ("timeout_seconds", 60)):
            with self.subTest(field=field):
                original = self.records[0]["generation"][field]
                self.records[0]["generation"][field] = value
                with self.assertRaisesRegex(ValueError, "generation"):
                    self.freeze()
                self.records[0]["generation"][field] = original

    def test_runtime_token_mismatch_and_output_excess_are_rejected(self):
        for field, value in (("input_tokens", self.records[0]["input_tokens"] + 1), ("input_tokens", 9000), ("output_tokens", 999)):
            with self.subTest(field=field, value=value):
                original = self.records[0][field]
                self.records[0][field] = value
                with self.assertRaisesRegex(ValueError, "token"):
                    self.freeze()
                self.records[0][field] = original

    def test_incomplete_seed_schedule_is_rejected(self):
        self.records.pop()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.freeze()

    def test_missing_arm_cannot_be_hidden_by_a_recomputed_manifest(self):
        self.contexts = [row for row in self.contexts if row["condition"] != "deleted"]
        self.records = [row for row in self.records if row["condition"] != "deleted"]
        with self.assertRaises(ValueError):
            self.freeze()

    def test_manifest_case_count_cannot_replace_actual_pilot_cases(self):
        self.contexts = [row for row in self.contexts if row["case_id"] != "dev-9"]
        self.records = [row for row in self.records if row["case_id"] != "dev-9"]
        with self.assertRaises(ValueError):
            self.freeze()

    def test_duplicate_arm_seed_records_are_rejected_without_last_wins(self):
        self.records.append(deepcopy(self.records[0]))
        with self.assertRaises(ValueError):
            self.freeze()

    def test_mismatched_tokenizer_identity_is_rejected(self):
        for record in self.records:
            record["backend"]["tokenizer_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "tokenizer identity"):
            self.freeze()

    def test_implementation_change_invalidates_pilot(self):
        self.write_pilot()
        with patch("graphtrust.pipeline.implementation_sha256", return_value="different"), self.assertRaisesRegex(ValueError, "Implementation changed"):
            freeze_protocol(self.protocol, self.root, self.root / "frozen.json")

    def update_prediction(self, record, data):
        arm = next(c for c in self.contexts if c["case_id"] == record["case_id"] and c["condition"] == record["condition"])
        record.update(response=deepcopy(data), prediction=deepcopy(data), raw_output=json.dumps(data))
        record.update(validate_prediction(data, arm))
        record["status"] = "invalid_prediction" if record["invalid_prediction"] else "ok"

    def test_semantic_invalid_outputs_count_as_parseable_and_are_disclosed(self):
        for record in self.records:
            self.update_prediction(record, {**record["response"], "extra": "fixture"})
        result = self.freeze()
        self.assertEqual(result["within_budget_contract_parse_rate"], 1)
        self.assertEqual(result["invalid_prediction_rate"], 1)

    def test_unknown_citations_never_satisfy_graph_usage_gate(self):
        for record in self.records:
            if record["condition"] == "clean":
                self.update_prediction(record, {**record["response"], "citations": ["invented"]})
        with self.assertRaisesRegex(ValueError, "Graph evidence rarely"):
            self.freeze()

    def test_legacy_records_missing_raw_and_incorrect_flags_cannot_freeze(self):
        for mutation in ({"schema_version": "1.0"}, {"response_contract_version": "old"},
                         {"contract_parseable": False}, {"invalid_prediction": True}):
            with self.subTest(mutation=mutation):
                original = deepcopy(self.records[0])
                self.records[0].update(mutation)
                with self.assertRaises(ValueError):
                    self.freeze()
                self.records[0] = original
        del self.records[0]["raw_output"]
        with self.assertRaisesRegex(ValueError, "raw output"):
            self.freeze()

    def test_at_least_114_of_120_attempts_must_parse_within_budget(self):
        # Seven distinct issue/arm failures keep timeout policy out of this check.
        original = deepcopy(self.records)
        for i in range(6):
            self.records[i].update(status="parse_error", raw_output="truncated {", response=None,
                                   prediction=None, contract_parseable=False, invalid_prediction=False)
        result = self.freeze()
        self.assertEqual(result["parse_rate"], .95)
        (self.root / "frozen.json").unlink()
        self.records[6].update(status="parse_error", raw_output="truncated {", response=None,
                               prediction=None, contract_parseable=False, invalid_prediction=False)
        with self.assertRaisesRegex(ValueError, "below pilot threshold"):
            self.freeze()
        self.records = original

    def test_late_valid_and_invalid_outputs_are_observed_but_not_gate_success(self):
        record = self.records[0]
        self.update_prediction(record, {"files": ["sample.py"], "citations": ["invented"], "abstain": False})
        record.update(completed_status=record["status"], status="timeout", latency_seconds=91)
        result = self.freeze()
        self.assertEqual(result["within_budget_contract_parse_rate"], 119 / 120)
        self.assertEqual(result["observed_contract_parse_rate"], 1)
        self.assertEqual(result["invalid_prediction_rate"], 1 / 120)

    def test_late_out_of_memory_cannot_hide_behind_timeout_status(self):
        self.records[0].update(status="timeout", completed_status="error", raw_output=None, response=None,
                               prediction=None, contract_parseable=False, invalid_prediction=False,
                               error_kind="out_of_memory", error="fixture", latency_seconds=91)
        with self.assertRaisesRegex(ValueError, "memory fitting"):
            self.freeze()

    def test_rejected_literal_surrogate_is_durable_and_does_not_crash_freeze_digest(self):
        self.records[0].update(status="parse_error", raw_output='{"files":["' + chr(0xd800) + '.py"]}',
                               response=None, prediction=None, contract_parseable=False, invalid_prediction=False)
        result = self.freeze()
        self.assertEqual(result["parse_rate"], 119 / 120)
        self.assertEqual(result["pilot_records_digest_rule"], "sorted_compact_ascii_json_v2")
        self.assertEqual(result["pilot_records_file_sha256"], hashlib.sha256((self.root / "records.jsonl").read_bytes()).hexdigest())

    def test_timing_metadata_cannot_promote_late_returns(self):
        for mutation in ({"latency_seconds": 91}, {"latency_seconds": -1}, {"latency_seconds": None},
                         {"latency_seconds": float("inf")}, {"latency_seconds": 1, "status": "timeout", "completed_status": "ok"}):
            with self.subTest(mutation=mutation):
                original = deepcopy(self.records[0])
                self.records[0].update(mutation)
                with self.assertRaisesRegex(ValueError, "latency|budget|timeout"):
                    self.freeze()
                self.records[0] = original


class ReplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.protocol = {**read_json(ROOT / "configs/protocol.json"), "holdout_repositories": ["r/r", "s/s"],
                         "holdout_per_repository": 2, "replication_per_repository": 1}
        self.cases = [{"case_id": f"{repo}-{suffix}", "repo": repo + "/" + repo,
                       "split": "test", "commit": "a" * 40, "issue_text": "localize failure"}
                      for repo in ("r", "s") for suffix in ("primary-a", "primary-b", "outside")]
        graph = {"snapshot": {"commit": "a" * 40}, "extractor_sha256": extractor_sha256()}
        save_graph(self.root / "prepared" / "graph.json.gz", graph)
        graph_sha = hashlib.sha256((self.root / "prepared" / "graph.json.gz").read_bytes()).hexdigest()
        for case in self.cases:
            write_json(self.root / "prepared" / "cases" / (case["case_id"] + ".json"),
                       {"preparation_schema_version": 2, "status": "ok", "commit": case["commit"], "graph_path": "graph.json.gz",
                        "case_sha256": digest(case), "graph_file_sha256": graph_sha,
                        "implementation_sha256": implementation_sha256()})
        case_ids = ["r-primary-a", "r-primary-b", "s-primary-a", "s-primary-b"]
        self.primary = {"stage": "holdout", "status": "prepared_not_frozen", "case_ids": case_ids,
                        "cases": 4, "contexts": 24, "selection_sha256": digest(case_ids),
                        "protocol_sha256": digest(self.protocol), "tokenizer_identity": "e2b-tokenizer",
                        "implementation_sha256": implementation_sha256()}

    def materializer(self, case, graph, protocol, token_counter):
        rows = [{"case_id": case["case_id"], "condition": arm, "prompt": "source unchanged",
                 "source_sha256": "fixed", "token_method": "tokenizer"} for arm in protocol["conditions"]]
        return rows, {"eligible": case["case_id"] != getattr(self, "ineligible", None)}

    def create(self, primary=None):
        with patch("graphtrust.pipeline.materialize_case", side_effect=self.materializer):
            return create_contexts(self.cases, self.root / "prepared", self.root / "replication", self.protocol,
                                   "replication", lambda text: len(text), "e4b-tokenizer", self.primary if primary is None else primary)

    def test_replication_remains_balanced_preregistered_primary_subset(self):
        manifest = self.create()
        self.assertEqual(manifest["case_ids"], ["r-primary-a", "s-primary-a"])
        self.assertTrue(set(manifest["case_ids"]) < set(self.primary["case_ids"]))
        self.assertFalse(any("outside" in case for case in manifest["case_ids"]))
        self.assertEqual(manifest["sampling_seeds"], [17])

    def test_second_runtime_ineligibility_does_not_replace_a_selected_case(self):
        self.ineligible = "r-primary-a"
        with self.assertRaisesRegex(ValueError, "preregistered primary subset"):
            self.create()
        self.assertFalse((self.root / "replication" / "contexts.jsonl").exists())

    def test_primary_manifest_is_required(self):
        with self.assertRaisesRegex(ValueError, "primary holdout manifest"):
            create_contexts([], self.root, self.root / "missing", self.protocol, "replication")

    def test_primary_manifest_protocol_mismatch_is_rejected(self):
        primary = dict(self.primary, protocol_sha256="different")
        with self.assertRaises(ValueError):
            self.create(primary)

    def test_primary_manifest_must_be_holdout_and_have_valid_selection_hash(self):
        for mutation in ({"stage": "pilot"}, {"selection_sha256": "different"}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.create(dict(self.primary, **mutation))

    def test_stale_extractor_is_rejected_even_when_graph_checksum_is_updated(self):
        graph_path = self.root / "prepared" / "graph.json.gz"
        graph = load_graph(graph_path)
        graph["extractor_sha256"] = "previous-extractor"
        save_graph(graph_path, graph)
        graph_sha = hashlib.sha256(graph_path.read_bytes()).hexdigest()
        for case in self.cases:
            path = self.root / "prepared" / "cases" / (case["case_id"] + ".json")
            record = read_json(path)
            record["graph_file_sha256"] = graph_sha
            write_json(path, record)
        with self.assertRaisesRegex(ValueError, "preregistered primary subset"):
            self.create()

    def test_stale_or_unversioned_preparation_is_rejected(self):
        path = self.root / "prepared" / "cases" / "r-primary-a.json"
        original = read_json(path)
        for mutation in ({"implementation_sha256": "old-code"}, {"case_sha256": "old-case"},
                         {"graph_file_sha256": None}, {"implementation_sha256": None},
                         {"preparation_schema_version": 1}, {"preparation_schema_version": None}):
            with self.subTest(mutation=mutation):
                write_json(path, dict(original, **mutation))
                with self.assertRaisesRegex(ValueError, "preregistered primary subset"):
                    self.create()
        write_json(path, original)

    def test_changed_case_metadata_cannot_reuse_preparation(self):
        self.cases[0]["issue_text"] = "changed after CPU preparation"
        with self.assertRaisesRegex(ValueError, "preregistered primary subset"):
            self.create()


class MaterializationTests(unittest.TestCase):
    def test_invisible_clean_callsite_removed_before_any_intervention(self):
        graph = build_graph(ROOT / "fixtures" / "synthetic", "fixture")
        edge = graph["edges"][0]
        node_ids = [node["id"] for node in graph["nodes"]]
        visible_source = f"SOURCE sample FILE {edge['path']} LINES {edge['line']}-{edge['line']} TRUNCATED true\npass\nEND SOURCE\n"
        pack = {"source_text": visible_source, "node_ids": node_ids}
        packed, spans, induced_count = _packed_source_graph(graph, pack)
        self.assertEqual(induced_count, len(graph["edges"]))
        self.assertIn(edge["id"], {e["id"] for e in packed["edges"]})
        self.assertTrue(all(e["path"] == edge["path"] and e["line"] == edge["line"] for e in packed["edges"]))
        pack["source_text"] = visible_source.replace(f"LINES {edge['line']}-{edge['line']}", "LINES 9999-9999")
        packed, _, _ = _packed_source_graph(graph, pack)
        self.assertEqual(packed["edges"], [])

    def test_source_bytes_identical_and_actual_corruption_count_matched(self):
        protocol = {**read_json(ROOT / "configs/protocol.json"), "max_source_tokens": 10000,
                    "max_input_tokens": 16000, "max_relation_tokens": 6000}
        graph = build_graph(ROOT / "fixtures" / "synthetic", "fixture")
        rows, qualification = materialize_case({"case_id": "fixture", "repo": "test/test", "issue_text": "normalize storage process"}, graph, protocol)
        self.assertTrue(qualification["eligible"])
        sources = [row["prompt"].split("SOURCE PACK\n", 1)[1].split("END SOURCE PACK\n", 1)[0] for row in rows]
        self.assertEqual(len(set(sources)), 1)
        self.assertEqual({row["source_sha256"] for row in rows}, {text_hash(sources[0])})
        self.assertEqual(qualification["deletion"]["achieved_edge_count"], qualification["rewiring"]["achieved_edge_count"])
        self.assertGreater(qualification["rewiring"]["achieved_edge_count"], 0)
        arms = {row["condition"]: row for row in rows}
        self.assertEqual(arms["clean"]["visible_edge_ids"], arms["clean_checked"]["visible_edge_ids"])
        self.assertEqual(arms["rewired"]["visible_edge_ids"], arms["rewired_checked"]["visible_edge_ids"])
        self.assertEqual(set(arms["clean"]["visible_edge_ids"]) - set(arms["deleted"]["visible_edge_ids"]), set(qualification["deletion"]["deleted_edge_ids"]))
        self.assertTrue(all("known_false_edge_ids" not in row["prompt"] and "test_patch" not in row["prompt"] for row in rows))
        for row in rows:
            self.assertEqual(row["visible_edge_ids"], row["visible_callsite_edge_ids"])
        self.assertEqual(qualification["visible_clean_callsites"], qualification["visible_edges"])
        self.assertEqual(qualification["visible_false_callsites"], qualification["visible_false_edges"])


class GraphCacheTests(unittest.TestCase):
    def test_current_cache_key_with_stale_extractor_metadata_is_not_blessed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = {"case_id": "case", "repo": "r/r", "commit": "a" * 40,
                    "issue_text": "failure", "split": "dev"}
            graph_key = digest({"repo": case["repo"], "commit": case["commit"], "extractor_sha256": extractor_sha256()})
            path = root / "graphs" / (graph_key + ".json.gz")
            graph = {"snapshot": {"commit": case["commit"]}, "extractor_sha256": "stale"}
            save_graph(path, graph)
            before = path.read_bytes()
            with patch("graphtrust.pipeline.prepare_snapshot", return_value=root):
                record = prepare_case(case, str(root), str(root), read_json(ROOT / "configs/protocol.json"))
            self.assertEqual(record["status"], "error")
            self.assertIn("extractor fingerprint", record["reason"])
            self.assertEqual(path.read_bytes(), before)

    def test_extractor_change_builds_a_new_graph_and_preserves_prior_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = ROOT / "fixtures" / "synthetic"
            case = {"case_id": "case", "repo": "r/r", "commit": "a" * 40,
                    "issue_text": "normalize storage process", "split": "dev"}
            protocol = {**read_json(ROOT / "configs/protocol.json"), "max_source_tokens": 10000}
            with patch("graphtrust.pipeline.prepare_snapshot", return_value=source), patch("graphtrust.graph.build_graph", wraps=build_graph) as build:
                # Patching the loaded fingerprint models separate fresh
                # processes, rather than permitting code changes mid-process.
                with patch("graphtrust.pipeline.implementation_sha256", return_value="old-code"), patch("graphtrust.pipeline._LOADED_IMPLEMENTATION", "old-code"), patch("graphtrust.pipeline.extractor_sha256", return_value="old-extractor"):
                    first = prepare_case(case, str(root), str(root), protocol)
                old_graph_bytes = (root / first["graph_path"]).read_bytes()
                with patch("graphtrust.pipeline.implementation_sha256", return_value="new-code"), patch("graphtrust.pipeline._LOADED_IMPLEMENTATION", "new-code"), patch("graphtrust.pipeline.extractor_sha256", return_value="new-extractor"):
                    second = prepare_case(case, str(root), str(root), protocol)
                self.assertEqual(build.call_count, 2)
            self.assertEqual((first["status"], second["status"]), ("ok", "ok"))
            self.assertNotEqual(first["graph_path"], second["graph_path"])
            self.assertEqual((root / first["graph_path"]).read_bytes(), old_graph_bytes)
            self.assertEqual(load_graph(root / second["graph_path"])["extractor_sha256"], "new-extractor")

    def test_code_mutation_before_preparation_stops_before_source_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = {"case_id": "case", "repo": "r/r", "commit": "a" * 40,
                    "issue_text": "failure", "split": "dev"}
            with patch("graphtrust.pipeline.implementation_sha256", return_value="changed-after-import"), patch("graphtrust.pipeline.prepare_snapshot") as prepare:
                with self.assertRaisesRegex(RuntimeError, "Executable files changed"):
                    prepare_case(case, str(root), str(root), read_json(ROOT / "configs/protocol.json"))
            prepare.assert_not_called()
            self.assertFalse((root / "cases" / "case.json").exists())

    def test_code_mutation_during_preparation_is_recorded_as_error(self):
        from graphtrust import pipeline
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = {"case_id": "case", "repo": "r/r", "commit": "a" * 40,
                    "issue_text": "normalize storage process", "split": "dev"}
            protocol = {**read_json(ROOT / "configs/protocol.json"), "max_source_tokens": 10000}
            with patch("graphtrust.pipeline.prepare_snapshot", return_value=ROOT / "fixtures" / "synthetic"), patch("graphtrust.pipeline.implementation_sha256", side_effect=[pipeline._LOADED_IMPLEMENTATION, "changed-during-preparation"]):
                record = prepare_case(case, str(root), str(root), protocol)
            self.assertEqual(record["status"], "error")
            self.assertFalse(record["eligible"])
            self.assertIn("Executable files changed", record["reason"])
            self.assertEqual(read_json(root / "cases" / "case.json"), record)

    def test_gzip_artifact_bytes_are_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.gz", Path(directory) / "second.gz"
            graph = {"schema_version": 1, "nodes": [{"id": "café::f"}], "edges": []}
            save_graph(first, graph)
            save_graph(second, graph)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(load_graph(first), graph)

    def test_concurrent_same_graph_writes_use_unique_atomic_staging(self):
        from graphtrust import pipeline
        original = pipeline.gzip.GzipFile
        barrier = threading.Barrier(2)
        def overlapping_gzip(*args, **kwargs):
            barrier.wait(timeout=3)
            return original(*args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json.gz"
            graph = {"nodes": [], "edges": [], "snapshot": {"commit": "same"}}
            with patch("graphtrust.pipeline.gzip.GzipFile", side_effect=overlapping_gzip), ThreadPoolExecutor(2) as pool:
                results = [pool.submit(save_graph, path, graph) for _ in range(2)]
                for result in results:
                    result.result()
            self.assertEqual(load_graph(path), graph)
            self.assertFalse(list(Path(directory).glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
