from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from graphtrust.graph import build_graph, edge_identifier
from graphtrust.interventions import check_edges, perturb_graph


class InterventionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        (root / "main.py").write_text("""def x():
    pass
def y():
    pass
def z():
    pass
def a():
    x()
def b():
    y()
def c():
    z()
def d():
    x()
""", encoding="utf-8")
        self.graph = build_graph(root, "base123")

    def test_seeded_deletion_preserves_all_source_and_original_graph(self):
        original = deepcopy(self.graph)
        deleted, sidecar = perturb_graph(self.graph, "delete", 0.5, 19)
        self.assertEqual(self.graph, original)
        self.assertEqual(deleted["snapshot"], original["snapshot"])
        self.assertEqual(deleted["nodes"], original["nodes"])
        self.assertEqual(deleted["unknown"], original["unknown"])
        self.assertEqual(sidecar["achieved_edge_count"], 2)
        self.assertEqual(sidecar["achieved_severity"], 0.5)
        self.assertEqual((deleted, sidecar), perturb_graph(self.graph, "delete", 0.5, 19))
        self.assertEqual(set(sidecar["deleted_edge_ids"]), {edge["id"] for edge in original["edges"]} - {edge["id"] for edge in deleted["edges"]})

    def test_rewire_is_paired_compatible_false_and_checker_detects_it(self):
        original = deepcopy(self.graph)
        rewired, sidecar = perturb_graph(self.graph, "rewire", 1.0, 27)
        self.assertEqual(self.graph, original)
        self.assertEqual(rewired["nodes"], original["nodes"])
        self.assertEqual(rewired["snapshot"], original["snapshot"])
        self.assertEqual((rewired, sidecar), perturb_graph(self.graph, "rewire", 1.0, 27))
        self.assertEqual(sidecar["achieved_edge_count"], 4)
        original_relations = {(edge["source"], edge["target"], edge["type"]) for edge in original["edges"]}
        nodes = {node["id"]: node for node in original["nodes"]}
        false_ids = set(sidecar["false_edge_ids"])
        self.assertEqual(len(false_ids), 4)
        self.assertEqual(sorted(edge["target"] for edge in rewired["edges"]), sorted(edge["target"] for edge in original["edges"]))
        for edge in rewired["edges"]:
            if edge["id"] in false_ids:
                self.assertNotIn((edge["source"], edge["target"], edge["type"]), original_relations)
                self.assertEqual(nodes[edge["target"]]["kind"], "function")
        self.assertEqual(set(check_edges(rewired, original).values()), {"contradicted"})
        self.assertEqual(set(check_edges(original, original).values()), {"supported"})

    def test_cannot_rewire_into_relation_valid_at_another_line(self):
        original = deepcopy(self.graph)
        edge = next(edge for edge in original["edges"] if edge["source"] == "main.py::a")
        valid_elsewhere = dict(edge, target="main.py::y", line=9)
        valid_elsewhere["id"] = edge_identifier(valid_elsewhere)
        original["edges"].append(valid_elsewhere)
        for seed in range(20):
            observed, sidecar = perturb_graph(original, "rewire", 1.0, seed)
            forbidden = {(item["source"], item["target"], item["type"]) for item in original["edges"]}
            for item in observed["edges"]:
                if item["id"] in sidecar["false_edge_ids"]:
                    self.assertNotIn((item["source"], item["target"], item["type"]), forbidden)

    def test_packed_graph_cannot_rewire_into_omitted_source_supported_relation(self):
        root = Path(self.directory.name)
        (root / "main.py").write_text("""def x():
    pass
def y():
    pass
def a():
    x()
    y()
def b():
    y()
""", encoding="utf-8")
        source_graph = build_graph(root, "base123")
        packed = deepcopy(source_graph)
        packed["edges"] = [edge for edge in source_graph["edges"]
                           if not (edge["source"] == "main.py::a" and edge["target"] == "main.py::y")]
        before = deepcopy(packed)
        forbidden = {(edge["source"], edge["target"], edge["type"]) for edge in source_graph["edges"]}
        # Reproduce the scientific-review counterexample: checking only the
        # packed metadata admits a true function-level relation at another site.
        unguarded, unguarded_sidecar = perturb_graph(packed, "rewire", 1.0, 1729)
        replacements = [edge for edge in unguarded["edges"] if edge["id"] in unguarded_sidecar["false_edge_ids"]]
        self.assertEqual(len(replacements), 2)
        self.assertTrue(any((edge["source"], edge["target"], edge["type"]) in forbidden for edge in replacements))
        self.assertEqual(set(check_edges(unguarded, source_graph).values()), {"contradicted"})
        for seed in range(20):
            with self.subTest(seed=seed):
                observed, sidecar = perturb_graph(packed, "rewire", 1.0, seed, source_graph=source_graph)
                self.assertEqual(observed, before)
                self.assertEqual(sidecar["achieved_edge_count"], 0)
                self.assertEqual(sidecar["exclusions"]["unachieved_edge_count"], 2)
                self.assertGreater(sidecar["exclusions"]["candidate_rejections"]["originally_supported_relation"], 0)
        self.assertEqual(packed, before)

    def test_source_support_requires_identical_snapshot(self):
        for mutation in [{"source_sha256": "other"}, {"commit": "other"}, {"files": []}]:
            source_graph = deepcopy(self.graph)
            source_graph["snapshot"].update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ValueError, "same source snapshot"):
                    perturb_graph(self.graph, "rewire", 0.5, 1, source_graph=source_graph)
        with self.assertRaisesRegex(ValueError, "same source snapshot"):
            perturb_graph(dict(self.graph, snapshot={}), "rewire", 0.5, 1,
                          source_graph=dict(self.graph, snapshot={}))

    def test_full_source_support_preserves_determinism_and_source_bytes(self):
        source_graph = deepcopy(self.graph)
        packed = deepcopy(self.graph)
        packed["edges"] = packed["edges"][:2]
        observed, sidecar = perturb_graph(packed, "rewire", 1.0, 27, source_graph=source_graph)
        self.assertEqual((observed, sidecar), perturb_graph(packed, "rewire", 1.0, 27, source_graph=source_graph))
        self.assertEqual(sidecar["achieved_edge_count"], 2)
        self.assertEqual(observed["nodes"], packed["nodes"])
        self.assertEqual(observed["snapshot"], packed["snapshot"])
        self.assertEqual(set(check_edges(observed, source_graph).values()), {"contradicted"})
        self.assertEqual(source_graph, self.graph)

    def test_constrained_graph_reports_shortfall_instead_of_invalid_edges(self):
        constrained = deepcopy(self.graph)
        constrained["edges"] = [edge for edge in constrained["edges"] if edge["target"] == "main.py::x"]
        observed, sidecar = perturb_graph(constrained, "rewire", 1.0, 5)
        self.assertEqual(observed, constrained)
        self.assertEqual(sidecar["achieved_edge_count"], 0)
        self.assertEqual(sidecar["exclusions"]["unachieved_edge_count"], 2)
        self.assertGreater(sidecar["exclusions"]["candidate_rejections"]["unchanged_target"], 0)

    def test_odd_count_and_empty_graph_are_explicit(self):
        observed, sidecar = perturb_graph(self.graph, "rewire", 0.75, 9)
        self.assertEqual(sidecar["requested_edge_count"], 3)
        self.assertEqual(sidecar["achieved_edge_count"], 2)
        self.assertEqual(sidecar["exclusions"]["odd_pair_shortfall"], 1)
        empty = dict(self.graph, edges=[])
        result, empty_sidecar = perturb_graph(empty, "rewire", 0.5, 1)
        self.assertEqual(result, empty)
        self.assertEqual(empty_sidecar["achieved_severity"], 0)

    def test_checker_preserves_unknown_calls_and_snapshot_mismatch(self):
        reference = deepcopy(self.graph)
        uncertain = {"source": "main.py::a", "path": "main.py", "line": 100,
                     "expression": "dynamic.method", "reason": "dynamic_receiver"}
        reference["unknown"].append(uncertain)
        added = {**uncertain, "target": "main.py::x", "type": "calls", "resolution": "supported"}
        added.pop("reason")
        added["id"] = edge_identifier(added)
        observed = dict(reference, edges=[added])
        self.assertEqual(check_edges(observed, reference), {added["id"]: "unknown"})
        mismatch = deepcopy(reference)
        mismatch["snapshot"]["source_sha256"] = "different"
        self.assertEqual(set(check_edges(self.graph, mismatch).values()), {"unknown"})

    def test_checker_uses_call_expression_to_disambiguate_same_line(self):
        reference = deepcopy(self.graph)
        edge = reference["edges"][0]
        other = dict(edge, target="main.py::z", expression="z")
        other["id"] = edge_identifier(other)
        reference["edges"].append(other)
        false = dict(edge, target="main.py::z")
        false["id"] = edge_identifier(false)
        observed = dict(reference, edges=[false])
        self.assertEqual(check_edges(observed, reference)[false["id"]], "contradicted")

    def test_invalid_parameters_fail_loudly(self):
        for kind, severity, seed in [("other", 0.3, 1), ("delete", -0.1, 1),
                                     ("rewire", 1.1, 1), ("delete", float("nan"), 1),
                                     ("delete", 0.3, "seed")]:
            with self.subTest(kind=kind, severity=severity, seed=seed):
                with self.assertRaises(ValueError):
                    perturb_graph(self.graph, kind, severity, seed)


if __name__ == "__main__":
    unittest.main()
