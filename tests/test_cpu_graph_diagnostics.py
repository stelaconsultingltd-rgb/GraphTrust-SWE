"""Integration invariants for the standalone CPU resource, not model evidence."""
from importlib import import_module
from pathlib import Path
from copy import deepcopy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from graphtrust.graph import build_graph
from graphtrust.io import digest, read_json, write_json
from graphtrust.pipeline import save_graph
from graphtrust.provenance import extractor_sha256, implementation_sha256

ROOT = Path(__file__).resolve().parents[1]
# Spawned Windows workers must be able to import the top-level job by name.
sys.path.insert(0, str(ROOT / "scripts"))
diagnostics = import_module("cpu_graph_diagnostics")


class FullGraphDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "source"
        source.mkdir()
        (source / "a.py").write_text("def x():\n    pass\ndef y():\n    pass\ndef a():\n    x()\ndef b():\n    y()\ndef c():\n    x()\n", encoding="utf8")
        self.graph = build_graph(source, "base")
        self.graph["extractor_sha256"] = extractor_sha256()
        self.protocol = read_json(ROOT / "configs/protocol.json")
        self.protocol_path = self.root / "protocol.json"
        write_json(self.protocol_path, self.protocol)
        self.prepared = self.root / "prepared"
        graph_path = self.prepared / "graphs/shared.json.gz"
        save_graph(graph_path, self.graph)
        self.record = {"status": "ok", "preparation_schema_version": 2,
            "implementation_sha256": implementation_sha256(), "protocol_sha256": digest(self.protocol),
            "graph_path": "graphs/shared.json.gz", "graph_file_sha256": diagnostics.file_hash(graph_path),
            "commit": "base", "snapshot_sha256": self.graph["snapshot"]["source_sha256"],
            "case_id": "synthetic-a", "repo": "synthetic", "split": "dev", "case_sha256": "fixture"}
        write_json(self.prepared / "cases/a.json", self.record)
        write_json(self.prepared / "cases/b.json", {**self.record, "case_id": "synthetic-b"})
        self.output = self.root / "out"

    def execute(self, **kwargs):
        return diagnostics.run(self.prepared, self.output, self.protocol_path,
                               allow_partial=True, synthetic=True, **kwargs)

    def test_full_source_invariants_parity_and_snapshot_deduplication(self):
        summary = self.execute()
        self.assertEqual(summary["successful_cases"], 2)
        self.assertEqual(summary["unique_graphs"], 1)
        self.assertEqual(summary["status"], "partial_cpu_diagnostics")
        self.assertTrue(summary["synthetic"])
        side = read_json(next((self.output / "graphs").glob("*.json")))
        self.assertEqual(len(side["variants"]), 18)
        self.assertTrue(all(v["source_and_nodes_unchanged"] for v in side["variants"]))
        self.assertTrue(all(v["full_source_false_relation_guard"] for v in side["variants"]))
        self.assertTrue(any(v["sidecar"]["achieved_edge_count"] == 0 for v in side["variants"]))
        rewired = [v for v in side["variants"] if v["sidecar"]["kind"] == "rewire"]
        self.assertTrue(all(v["degree_sequences_unchanged"] for v in rewired))
        self.assertTrue(any(v["sidecar"]["exclusions"]["odd_pair_shortfall"] for v in rewired))
        with patch.object(diagnostics, "diagnose_graph", side_effect=AssertionError("resume regenerated graph")):
            self.assertEqual(self.execute()["variant_grid"], summary["variant_grid"])

    def test_changed_graph_and_stale_implementation_are_reported(self):
        stale = {**self.record, "implementation_sha256": "stale"}
        write_json(self.prepared / "cases/a.json", stale)
        (self.prepared / "graphs/shared.json.gz").write_bytes(b"tampered")
        summary = self.execute()
        self.assertEqual(summary["successful_cases"], 0)
        self.assertEqual(len(summary["failures"]), 2)
        self.assertIn("implementation", summary["failures"][0]["error"])
        self.assertIn("Graph bytes", summary["failures"][1]["error"])

    def test_cached_diagnostic_tampering_rejected_and_version_identity_preserved(self):
        self.execute()
        path = next((self.output / "graphs").glob("*.json"))
        changed = read_json(path)
        changed["variants"][0]["source_and_nodes_unchanged"] = False
        write_json(path, changed)
        self.assertEqual(len(self.execute()["failures"]), 2)
        with self.assertRaisesRegex(ValueError, "identity differs"):
            self.execute(expected_cases=2)

    def test_public_case_identity_guard_and_final_completion_guard(self):
        public = self.root / "public.json"
        write_json(public, {"cases": [{"case_id": "synthetic-a", "repo": "wrong", "commit": "base", "split": "dev", "public_case_sha256": "fixture"}]})
        summary = self.execute(case_manifest=public)
        self.assertEqual(summary["successful_cases"], 0)
        with self.assertRaisesRegex(ValueError, "requires 300"):
            diagnostics.run(self.prepared, self.root / "final", self.protocol_path, synthetic=True)

    def add_second_graph(self):
        graph = deepcopy(self.graph)
        graph["snapshot"]["commit"] = "other-base"
        path = self.prepared / "graphs/other.json.gz"
        save_graph(path, graph)
        record = {**self.record, "case_id": "synthetic-c", "commit": "other-base",
                  "graph_path": "graphs/other.json.gz", "graph_file_sha256": diagnostics.file_hash(path)}
        write_json(self.prepared / "cases/c.json", record)
        return graph, path, record

    def test_serial_parallel_scientific_parity_and_cross_worker_resume(self):
        self.add_second_graph()
        serial = self.execute(workers=1)
        serial_manifest = read_json(self.output / "MANIFEST.json")
        serial_graphs = {p.name: read_json(p) for p in (self.output / "graphs").glob("*.json")}
        self.output = self.root / "parallel"
        parallel = self.execute(workers=2)
        parallel_manifest = read_json(self.output / "MANIFEST.json")
        parallel_graphs = {p.name: read_json(p) for p in (self.output / "graphs").glob("*.json")}
        self.assertEqual(diagnostics.scientific_payload(serial), diagnostics.scientific_payload(parallel))
        self.assertEqual(diagnostics.scientific_payload(serial_manifest), diagnostics.scientific_payload(parallel_manifest))
        self.assertEqual(serial_graphs.keys(), parallel_graphs.keys())
        for key in serial_graphs:
            self.assertEqual(diagnostics.scientific_payload(serial_graphs[key]), diagnostics.scientific_payload(parallel_graphs[key]))
            self.assertEqual(serial_graphs[key]["scientific_sha256"], parallel_graphs[key]["scientific_sha256"])
        self.assertEqual(parallel["unique_graphs"], 2)
        self.assertEqual(parallel["successful_cases"], 3)
        before = {p.name: p.read_bytes() for p in (self.output / "graphs").glob("*.json")}
        with patch.object(diagnostics, "diagnose_graph", side_effect=AssertionError("resume regenerated graph")):
            self.assertEqual(self.execute(workers=1), parallel)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.output / "graphs").glob("*.json")})
        events = [json.loads(line) for line in (self.output / "EXECUTIONS.jsonl").read_text().splitlines()]
        self.assertEqual([e["workers"] for e in events if e["event"] == "start"], [2, 1])
        self.assertTrue(all(e["reused"] for e in events if e["event"] == "graph_validated" and e["execution_id"] == events[-1]["execution_id"]))

    def test_parallel_worker_failure_is_reported_and_cannot_complete(self):
        graph, path, record = self.add_second_graph()
        graph.pop("edges")
        save_graph(path, graph)
        record["graph_file_sha256"] = diagnostics.file_hash(path)
        write_json(self.prepared / "cases/c.json", record)
        summary = self.execute(workers=2)
        self.assertEqual(summary["successful_cases"], 2)
        self.assertEqual(summary["unique_graphs"], 1)
        self.assertEqual(summary["status"], "partial_cpu_diagnostics")
        self.assertEqual([r["case_id"] for r in summary["failures"]], ["synthetic-c"])
        with self.assertRaisesRegex(ValueError, "requires 300"):
            diagnostics.run(self.prepared, self.root / "strict", self.protocol_path,
                            workers=2, synthetic=True)

    def test_every_alias_source_identity_is_validated(self):
        write_json(self.prepared / "cases/b.json", {**self.record, "case_id": "synthetic-b",
                                                    "snapshot_sha256": "contradictory-alias"})
        summary = self.execute(workers=2)
        self.assertEqual(summary["successful_cases"], 0)
        self.assertEqual(len(summary["failures"]), 2)
        self.assertTrue(all("source identity" in r["error"] for r in summary["failures"]))

    def test_schema_one_output_cannot_be_relabelled_for_schema_two(self):
        self.execute()
        identity = read_json(self.output / "IDENTITY.json")
        identity["schema_version"] = 1
        write_json(self.output / "IDENTITY.json", identity)
        with self.assertRaisesRegex(ValueError, "identity differs"):
            self.execute(workers=2)

    def test_invalid_worker_counts_fail_before_writing_outputs(self):
        for count in (0, -1, True, 1.5):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "workers must"):
                self.execute(workers=count)
        self.assertFalse(self.output.exists())

    def test_parallel_all_300_gate_requires_exact_ids_no_filter_and_no_failures(self):
        # Only a control-flow fixture: temporary synthetic records deliberately
        # exercise synthetic=False, and are never published as corpus evidence.
        self.prepared = self.root / "all-300-fixture"
        path = self.prepared / "graphs/shared.json.gz"
        save_graph(path, self.graph)
        cases = []
        for index in range(300):
            case_id = f"synthetic-{index:03}"
            record = {**self.record, "case_id": case_id, "split": "test"}
            write_json(self.prepared / "cases" / (case_id + ".json"), record)
            cases.append({"case_id": case_id, "repo": record["repo"], "split": "test",
                          "commit": record["commit"], "public_case_sha256": record["case_sha256"]})
        public = self.root / "all-300-public-fixture.json"
        write_json(public, {"synthetic_control_flow_fixture": True, "cases": cases})
        def execute(name, **kwargs):
            return diagnostics.run(self.prepared, self.root / name, self.protocol_path,
                                   case_manifest=public, workers=2, **kwargs)
        self.assertEqual(execute("positive-fixture")["status"], "complete_cpu_resource")
        self.assertEqual(execute("filtered", allow_partial=True, case_ids=[c["case_id"] for c in cases])["status"],
                         "partial_cpu_diagnostics")
        missing = self.prepared / "cases" / "synthetic-000.json"
        missing.unlink()
        with self.assertRaisesRegex(ValueError, "requires 300"):
            execute("missing")
        write_json(missing, {**self.record, "case_id": "synthetic-000", "split": "test",
                             "implementation_sha256": "stale"})
        failed = execute("invalid", allow_partial=True)
        self.assertEqual(failed["status"], "partial_cpu_diagnostics")
        self.assertEqual(failed["successful_cases"], 299)
        self.assertEqual(len(failed["failures"]), 1)


if __name__ == "__main__":
    unittest.main()
