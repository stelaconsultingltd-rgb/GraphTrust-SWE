"""Deterministic sibling-publication regressions; no research evidence."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import graphtrust.pipeline as pipeline
from graphtrust.graph import build_graph
from graphtrust.io import digest, read_json
from graphtrust.provenance import extractor_sha256


ROOT = Path(__file__).resolve().parents[1]


class PublicationRaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="graphtrust-publication-race-")
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        self.source = ROOT / "fixtures" / "synthetic"
        self.case = {"case_id": "synthetic-race", "repo": "fixture/fixture", "commit": "a" * 40,
                     "issue_text": "normalize storage process", "split": "dev"}
        self.protocol = {**read_json(ROOT / "configs/protocol.json"), "max_source_tokens": 10000}
        key = digest({"repo": self.case["repo"], "commit": self.case["commit"],
                      "extractor_sha256": extractor_sha256()})
        self.graph_path = self.output / "graphs" / (key + ".json.gz")
        self.graph = build_graph(self.source, commit=self.case["commit"])
        self.assertNotIn("extractor_sha256", self.graph)
        self.published_bytes = None

    def call(self, graph_builder=None):
        with patch("graphtrust.pipeline.prepare_snapshot", return_value=self.source):
            if graph_builder is None:
                return pipeline.prepare_case(self.case, str(self.output), str(self.output), self.protocol)
            with patch("graphtrust.graph.build_graph", side_effect=graph_builder):
                return pipeline.prepare_case(self.case, str(self.output), str(self.output), self.protocol)

    def sibling_race(self, modify=None):
        entered, published = threading.Event(), threading.Event()
        sibling = deepcopy(self.graph)
        sibling["extractor_sha256"] = extractor_sha256()
        if modify:
            modify(sibling)

        def publisher():
            if not entered.wait(5):
                raise AssertionError("The fresh builder did not reach the barrier")
            pipeline.save_graph(self.graph_path, sibling)
            self.published_bytes = self.graph_path.read_bytes()
            published.set()

        def fresh_builder(*args, **kwargs):
            self.assertFalse(self.graph_path.exists())
            entered.set()
            if not published.wait(5):
                raise AssertionError("The sibling did not publish at the barrier")
            return deepcopy(self.graph)  # Actual extractor returns no annotation.

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(publisher)
            result = self.call(fresh_builder)
            future.result(timeout=5)
        self.assertEqual(self.graph_path.read_bytes(), self.published_bytes)
        self.assertFalse(list(self.graph_path.parent.glob("*.lock")))
        self.assertFalse(list(self.graph_path.parent.glob("*.tmp")))
        return result

    def test_fresh_graph_without_sibling_succeeds(self):
        result = self.call()
        self.assertEqual(result["status"], "ok", result)

    def test_valid_sibling_publication_is_not_misclassified_as_stale_cache(self):
        # Publication occurs while the fresh extraction is blocked, not on a
        # probabilistic sleep. Repeat with independent output directories.
        for iteration in range(3):
            with self.subTest(iteration=iteration):
                if iteration:
                    self.setUp()
                result = self.sibling_race()
                self.assertEqual(result["status"], "ok", result)

    def test_existing_stale_cache_is_refused_without_overwriting(self):
        stale = deepcopy(self.graph)
        stale["extractor_sha256"] = "stale"
        pipeline.save_graph(self.graph_path, stale)
        before = self.graph_path.read_bytes()
        result = self.call()
        self.assertEqual(result["status"], "error")
        self.assertIn("extractor fingerprint", result["reason"])
        self.assertEqual(self.graph_path.read_bytes(), before)

    def test_sibling_stale_cache_is_refused_without_overwriting(self):
        result = self.sibling_race(lambda g: g.update(extractor_sha256="stale"))
        self.assertEqual(result["status"], "error")
        self.assertIn("extractor fingerprint", result["reason"])

    def test_sibling_different_graph_is_refused_without_overwriting(self):
        result = self.sibling_race(lambda g: g["snapshot"].update(source_sha256="different"))
        self.assertEqual(result["status"], "error")

    def test_retry_uses_valid_published_cache_and_preserves_its_bytes(self):
        self.sibling_race()
        before = self.graph_path.read_bytes()
        result = self.call()
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(self.graph_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
