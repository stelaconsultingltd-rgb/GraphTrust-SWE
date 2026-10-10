import copy
import hashlib
import math
import re
from collections import Counter
import unittest

from graphtrust.context import ContextBudgetError, _rank_nodes, _terms, build_context, build_source_pack, is_production_path


def graph_fixture(files=12):
    nodes = []
    for i in range(files):
        path = f"pkg/f{i}.py"
        nodes.append({"id": f"{path}::f{i}", "path": path, "kind": "function", "start_line": 1, "end_line": 2, "text": f"def f{i}():\n    return {i}\n"})
    edges = [{"id": "e1", "source": nodes[0]["id"], "target": nodes[1]["id"], "type": "calls", "path": nodes[0]["path"], "line": 2, "resolution": "supported"}] if files >= 2 else []
    return {"nodes": nodes, "edges": edges, "snapshot": {"commit": "fixture", "source_sha256": "fixture"}, "unknown": [], "errors": []}


class ContextTests(unittest.TestCase):
    def test_retrieval_reproducible_diverse_and_gold_independent(self):
        graph = graph_fixture()
        before = copy.deepcopy(graph)
        pack = build_source_pack(graph, "f8 fails", max_source_tokens=2400)
        self.assertEqual(pack, build_source_pack(graph, "f8 fails", max_source_tokens=2400))
        self.assertGreaterEqual(len(pack["files"]), 10)
        self.assertEqual(graph, before)
        self.assertEqual(pack["source_sha256"], hashlib.sha256(pack["source_text"].encode()).hexdigest())
        self.assertLessEqual(pack["source_tokens"], 2400)
        self.assertEqual(pack["token_method"], "byte_upper_bound")

    def test_production_filter_excludes_tests(self):
        for path in ("tests/unit.py", "pkg/test_x.py", "pkg/x_test.py", "conftest.py", "vendor/pkg/a.py"):
            self.assertFalse(is_production_path(path))
        self.assertTrue(is_production_path("pkg/testing_helpers.py"))
        graph = graph_fixture(1)
        graph["nodes"].append(dict(graph["nodes"][0], id="tests/t.py::fake", path="tests/t.py", text="GOLD_SENTINEL"))
        self.assertNotIn("GOLD_SENTINEL", build_source_pack(graph, "GOLD_SENTINEL")["source_text"])

    def test_source_identical_across_all_conditions(self):
        graph = graph_fixture()
        pack = build_source_pack(graph, "f0 f1 fails")
        case = {"case_id": "fixture-1", "repo": "fixture", "issue_text": "f0 fails", "patch": "SECRET_GOLD", "test_patch": "SECRET_TEST"}
        contexts = []
        for condition in ("source_only", "clean", "deleted", "rewired", "clean_checked", "rewired_checked"):
            arm = copy.deepcopy(graph)
            if condition == "deleted":
                arm["edges"] = []
            if condition.startswith("rewired"):
                arm["edges"][0]["target"] = graph["nodes"][2]["id"]
                arm["edges"][0]["corruption"] = "SECRET_LABEL"
            context = build_context(case, pack, arm, condition, checker_statuses={"e1": "contradicted"})
            contexts.append(context)
            self.assertIn(pack["source_text"], context["prompt"])
            self.assertNotIn("SECRET_", context["prompt"])
        self.assertEqual(len({c["source_sha256"] for c in contexts}), 1)
        self.assertEqual(contexts[0]["visible_edge_ids"], [])

    def test_overbudget_rejects_without_mutating_pack(self):
        graph = graph_fixture()
        pack = build_source_pack(graph, "f0 fails")
        original = copy.deepcopy(pack)
        with self.assertRaises(ContextBudgetError):
            build_context({"case_id": "a", "issue_text": "x" * 5000}, pack, graph, "clean")
        self.assertEqual(pack, original)

    def test_exact_counter_and_hash_validation(self):
        graph = graph_fixture(2)
        counter = lambda text: len(text)
        pack = build_source_pack(graph, "fails", token_counter=counter)
        context = build_context({"case_id": "a", "issue_text": "fails"}, pack, graph, "clean", token_counter=counter)
        self.assertEqual(context["input_tokens"], len(context["prompt"]))
        self.assertEqual(context["token_method"], "tokenizer")
        pack["source_text"] += "tamper"
        with self.assertRaises(ValueError):
            build_context({"case_id": "a"}, pack, graph, "clean")

    def test_dynamic_and_invisible_relationships_not_supplied(self):
        graph = graph_fixture(2)
        graph["edges"].extend([
            dict(graph["edges"][0], id="dynamic", resolution="unresolved"),
            dict(graph["edges"][0], id="hidden", target="outside.py::hidden"),
        ])
        pack = build_source_pack(graph, "f0 f1")
        context = build_context({"case_id": "a"}, pack, graph, "clean")
        self.assertEqual(context["visible_edge_ids"], ["e1"])

    def test_checker_control_and_missing_status(self):
        graph = graph_fixture(2)
        pack = build_source_pack(graph, "f0 f1")
        with self.assertRaises(ValueError):
            build_context({"case_id": "a"}, pack, graph, "clean_checked")
        context = build_context({"case_id": "a"}, pack, graph, "clean_checked", checker_statuses={})
        self.assertIn('"source_check":"unresolved"', context["prompt"])
        context = build_context({"case_id": "a"}, pack, graph, "clean_checked", checker_statuses={"e1": "unknown"})
        self.assertIn('"source_check":"unresolved"', context["prompt"])

    def test_frozen_relation_subset_can_require_no_arm_truncation(self):
        graph = graph_fixture(2)
        pack = build_source_pack(graph, "f0 f1")
        with self.assertRaises(ContextBudgetError):
            build_context({"case_id": "a"}, pack, graph, "clean", max_relation_tokens=1, require_all_relations=True)
        context = build_context({"case_id": "a"}, pack, graph, "clean", max_relation_tokens=1)
        self.assertEqual(context["visible_edge_ids"], [])

    def test_structural_neighbors_follow_diverse_anchors(self):
        graph = graph_fixture(2)
        graph["nodes"].append({"id": "pkg/f0.py::buddy", "path": "pkg/f0.py", "kind": "function", "start_line": 4, "end_line": 5, "text": "def buddy():\n    return 3\n"})
        graph["edges"].append({"id": "neighbor", "source": "pkg/f0.py::f0", "target": "pkg/f0.py::buddy", "type": "calls", "path": "pkg/f0.py", "line": 2, "resolution": "supported"})
        pack = build_source_pack(graph, "f0", min_files=2)
        self.assertIn("pkg/f0.py::buddy", pack["node_ids"])
        self.assertEqual(len(pack["files"]), 2)

    def test_minimum_diversity_best_effort_with_tiny_budget(self):
        pack = build_source_pack(graph_fixture(), "f0", max_source_tokens=20)
        self.assertLessEqual(pack["source_tokens"], 20)
        self.assertEqual(pack["files"], [])

    def test_streamed_query_counts_preserve_full_vocabulary_bm25_ranking(self):
        graph = graph_fixture()
        graph["nodes"][0]["text"] += "unrelated_unique = unrelated_unique\n"
        query = Counter(_terms("f8 f0 unrelatedUnique"))
        nodes = graph["nodes"]
        documents = [Counter(_terms(n["path"] + " " + n["id"] + " " + n["text"])) for n in nodes]
        frequency = Counter(term for doc in documents for term in doc)
        lengths = [sum(doc.values()) for doc in documents]
        average = sum(lengths) / len(lengths)
        scored = []
        for node, doc, length in zip(nodes, documents, lengths):
            score = 0.0
            for term in query:
                tf = doc.get(term, 0)
                if tf:
                    idf = math.log(1 + (len(nodes) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                    score += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / average))
            scored.append((score, node))
        expected = [n["id"] for _, n in sorted(scored, key=lambda item: (-item[0], item[1]["path"], item[1]["id"]))]
        self.assertEqual([n["id"] for n in _rank_nodes(nodes, "f8 f0 unrelatedUnique")], expected)

    def test_long_module_is_split_once_per_selection_phase(self):
        class CountedText(str):
            splits = 0
            def splitlines(self, *args, **kwargs):
                type(self).splits += 1
                return super().splitlines(*args, **kwargs)
        graph = graph_fixture(2)
        graph["nodes"][0]["kind"] = "module"
        graph["nodes"][0]["text"] = CountedText("item = 1\n" * 1000)
        graph["nodes"][0]["end_line"] = 1000
        build_source_pack(graph, "item f1", min_files=2)
        self.assertLessEqual(CountedText.splits, 3)

    def test_long_neighbor_does_not_starve_other_structural_endpoints(self):
        graph = graph_fixture(10)
        for i in range(6):
            node = {"id": f"pkg/f0.py::neighbor{i}", "path": "pkg/f0.py", "kind": "function", "start_line": 10 + i * 100, "end_line": 10 + i * 100 + 80, "text": f"def neighbor{i}():\n" + "    item = 1\n" * 80}
            graph["nodes"].append(node)
            graph["edges"].append({"id": f"n{i}", "source": "pkg/f0.py::f0", "target": node["id"], "type": "calls", "path": "pkg/f0.py", "line": 2, "resolution": "supported"})
        # A simple character counter keeps the fixture focused on allocation.
        pack = build_source_pack(graph, "f0", max_source_tokens=3200, token_counter=len)
        self.assertEqual(len(pack["files"]), 10)
        self.assertGreaterEqual(sum("::neighbor" in node_id for node_id in pack["node_ids"]), 5)

    def test_truncated_caller_anchors_at_clean_callsite_before_lexical_match(self):
        graph = graph_fixture(2)
        caller = graph["nodes"][0]
        caller["text"] = "def f0():\n    needle = 1\n" + "    padding = 0\n" * 100 + "    return f1()\n" + "    padding = 0\n" * 100
        caller["end_line"] = 203
        graph["edges"][0]["line"] = 103
        original = copy.deepcopy(graph)
        pack = build_source_pack(graph, "needle", min_files=2, max_source_tokens=500, token_counter=len)
        match = re.search(r"SOURCE pkg/f0.py::f0 FILE pkg/f0.py LINES (\d+)-(\d+)", pack["source_text"])
        self.assertIsNotNone(match)
        self.assertLessEqual(int(match[1]), 103)
        self.assertGreaterEqual(int(match[2]), 103)
        self.assertIn("return f1()", pack["source_text"])
        self.assertEqual(graph, original)
        self.assertEqual(pack, build_source_pack(graph, "needle", min_files=2, max_source_tokens=500, token_counter=len))


if __name__ == "__main__":
    unittest.main()
