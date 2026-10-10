"""Prospective output contract tests; synthetic infrastructure evidence only."""
import json
import unittest

from graphtrust.prediction import PredictionError, parse_prediction, validate_prediction


CONTEXT = {"visible_files": ["pkg/a.py", "pkg/b.py"],
           "visible_source_ids": ["pkg/a.py::f"], "visible_edge_ids": ["edge-1"]}


class PredictionTests(unittest.TestCase):
    def test_compact_schema_and_exact_whole_envelopes(self):
        expected = {"files": ["pkg/a.py"], "citations": [], "abstain": False}
        for text in ('{"files":["pkg/a.py"]}', ' \r\n```JSON\r\n{"files":["pkg/a.py"]}\r\n```\t'):
            self.assertEqual(parse_prediction(text), expected)

    def test_no_salvage_of_prose_fragments_or_multiple_objects(self):
        texts = ['prefix {"files":[]}', '{"files":[]} trailing', '{} {}', '{"files":[',
                 '```\n{"files":[]}\n```', '```json\n{"files":[]}\n```\nmore',
                 '```python\n{"files":[]}\n```', '```json\n{"files":[]}\n```\n```json\n{}\n```']
        for text in texts:
            with self.subTest(text=text), self.assertRaises(PredictionError):
                parse_prediction(text)

    def test_duplicate_keys_and_all_type_failures(self):
        texts = ['{"files":[],"files":[]}', '{"files":[],"extra":{"x":1,"x":2}}',
                 '{}', '[]', '{"files":null}', '{"files":[0]}', '{"files":[],"citations":null}',
                 '{"files":[],"citations":[false]}', '{"files":[],"abstain":0}']
        for text in texts:
            with self.subTest(text=text), self.assertRaises(PredictionError):
                parse_prediction(text)

    def test_nonfinite_numbers_and_unpaired_unicode_fail_even_in_extra_fields(self):
        texts = ['{"files":[],"extra":NaN}', '{"files":[],"extra":Infinity}',
                 '{"files":[],"extra":1e999}', '{"files":[],"extra":[-1e999]}',
                 '{"files":["\\ud800"]}', '{"files":[],"\\udfff":0}',
                 '{"files":[],"extra":["\\ud800"]}']
        for text in texts:
            with self.subTest(text=text), self.assertRaises(PredictionError):
                parse_prediction(text)
        self.assertEqual(parse_prediction('{"files":["\\ud83d\\ude80.py"]}')["files"], ["🚀.py"])

    def test_semantic_errors_do_not_become_parse_failures_or_replace_slots(self):
        files = ["../pkg/a.py", "pkg//a.py", "pkg\\a.py", "pkg/a.py", "pkg/a.py", "pkg/b.py"]
        prediction = parse_prediction(json.dumps({"files": files, "citations": ["unknown"] * 3, "extra": 1}))
        checked = validate_prediction(prediction, CONTEXT)
        self.assertEqual(prediction["files"], files)
        self.assertTrue(checked["invalid_prediction"])
        self.assertEqual(checked["invalid_files"], files[:3])
        for flag in ("duplicate_files", "duplicate_citations", "too_many_files", "too_many_citations", "extra_fields"):
            self.assertTrue(checked["prediction_flags"][flag], flag)

    def test_all_three_visible_citation_namespaces(self):
        for ref, field in (("edge-1", "valid_graph_citations"), ("pkg/a.py::f", "valid_source_id_citations"),
                           ("pkg/a.py", "valid_file_citations")):
            checked = validate_prediction(parse_prediction(json.dumps({"files": ["pkg/a.py"], "citations": [ref]})), CONTEXT)
            self.assertFalse(checked["invalid_prediction"])
            self.assertEqual(checked[field], [ref])

    def test_exact_refs_no_header_extraction_or_ambiguous_namespace(self):
        context = {**CONTEXT, "visible_edge_ids": ["edge-1", "pkg/a.py"]}
        prediction = parse_prediction(json.dumps({"files": ["pkg/a.py"], "citations": ["SOURCE pkg/a.py::f", "pkg/a.py"]}))
        checked = validate_prediction(prediction, context)
        self.assertEqual(checked["invalid_citations"], prediction["citations"])
        self.assertEqual(checked["valid_graph_citations"], [])

    def test_empty_prediction_and_abstain_conflict_are_semantic(self):
        for data, flag in (({"files": []}, "empty_without_abstain"),
                           ({"files": ["pkg/a.py"], "abstain": True}, "abstain_with_files")):
            checked = validate_prediction(parse_prediction(json.dumps(data)), CONTEXT)
            self.assertTrue(checked["prediction_flags"][flag])
        self.assertFalse(validate_prediction(parse_prediction('{"files":[],"abstain":true}'), CONTEXT)["invalid_prediction"])


if __name__ == "__main__":
    unittest.main()
