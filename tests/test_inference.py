import hashlib
import json
from pathlib import Path
import tempfile
import inspect
import unittest
from unittest.mock import Mock, patch
from contextlib import nullcontext
from types import SimpleNamespace

from graphtrust.inference import LlamaCppBackend, MockBackend, PredictionError, TransformersBackend, checkpoint_manifest, parse_prediction, run_contexts, tokenizer_fingerprint


def context_fixture():
    prompt = "SOURCE pkg/a.py::f FILE pkg/a.py LINES 1-2 TRUNCATED false\ndef f():\n    pass\nEND SOURCE\n"
    return {"case_id": "fixture-1", "repo": "fixture", "condition": "source_only", "prompt": prompt, "source_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "context_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "visible_files": ["pkg/a.py"], "visible_source_ids": ["pkg/a.py::f"], "visible_edge_ids": [], "input_tokens": len(prompt), "token_method": "byte_upper_bound"}


class BrokenBackend:
    synthetic = True
    identity = {"name": "broken_fixture"}

    def __init__(self):
        self.calls = 0

    def generate(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("fixture failure")


class InferenceTests(unittest.TestCase):
    def test_strict_json_validation(self):
        prediction = {"files": ["pkg/a.py"], "source_ids": [], "edge_ids": [], "abstain": False}
        self.assertEqual(parse_prediction(json.dumps(prediction)), prediction)
        invalid = [
            "```json\n" + json.dumps(prediction) + "\n```",
            json.dumps(dict(prediction, abstain="false")),
            json.dumps(dict(prediction, files=["../escape.py"])),
            json.dumps(dict(prediction, files=["a.py"] * 6)),
            json.dumps(dict(prediction, files=[])),
            json.dumps(dict(prediction, abstain=True)),
            json.dumps(dict(prediction, unknown=1)),
            '{"files":["a.py"],"files":["b.py"],"source_ids":[],"edge_ids":[],"abstain":false}',
        ]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(PredictionError):
                parse_prediction(text)

    def test_resume_and_generation_config_key(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            contexts = [context_fixture()]
            first = run_contexts(contexts, output, MockBackend(), [11, 22], "synthetic")
            self.assertEqual(first["attempted"], 2)
            self.assertEqual(first["statuses"], {"ok": 2})
            second = run_contexts(contexts, output, MockBackend(), [11, 22], "synthetic")
            self.assertEqual(second["attempted"], 0)
            self.assertEqual(second["resumed"], 2)
            changed = run_contexts(contexts, output, MockBackend(), [11], "synthetic", temperature=0.3)
            self.assertEqual(changed["attempted"], 1)
            records = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(len(records), 3)
            self.assertTrue(all(r["synthetic"] for r in records))
            self.assertEqual(len({r["run_id"] for r in records}), 3)
            self.assertEqual(records[0]["response"], records[0]["prediction"])

    def test_errors_preserved_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            backend = BrokenBackend()
            run_contexts([context_fixture()], output, backend, [1], "broken")
            second = run_contexts([context_fixture()], output, backend, [1], "broken")
            self.assertEqual(backend.calls, 1)
            self.assertEqual(second["statuses"], {"error": 1})
            self.assertIn("fixture failure", json.loads(output.read_text())["error"])

    def test_elapsed_timeout_recorded_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            with patch("graphtrust.inference.time.monotonic", side_effect=[100, 191]):
                result = run_contexts([context_fixture()], output, MockBackend(), [1], "synthetic", timeout_seconds=90)
            record = json.loads(output.read_text())
            self.assertEqual(result["statuses"], {"timeout": 1})
            self.assertEqual(record["completed_status"], "ok")
            self.assertEqual(record["timeout_enforcement"], "elapsed_after_return")

    def test_invalid_citations_and_paths_preserved(self):
        response = {"files": ["unknown.py"], "source_ids": ["unknown"], "edge_ids": ["invented"], "abstain": False}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            run_contexts([context_fixture()], output, MockBackend(response), [1], "synthetic")
            record = json.loads(output.read_text())
            self.assertEqual(record["status"], "parse_error")
            self.assertEqual(record["invalid_files"], ["unknown.py"])
            self.assertEqual(record["invalid_edge_ids"], ["invented"])
            self.assertEqual(record["response"], response)

    def test_corrupt_existing_log_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            output.write_text('{"run_id":', encoding="utf-8")
            with self.assertRaises(ValueError):
                run_contexts([context_fixture()], output, MockBackend(), [1], "synthetic")

    def test_duplicate_requested_arms_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            with self.assertRaises(ValueError):
                run_contexts([context_fixture(), context_fixture()], output, MockBackend(), [1], "synthetic")
            context = context_fixture()
            context["prompt"] += "tamper"
            with self.assertRaises(ValueError):
                run_contexts([context], output, MockBackend(), [1], "synthetic")

    def test_max_calls_bounds_new_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            result = run_contexts([context_fixture()], output, MockBackend(), [1, 2, 3], "synthetic", max_calls=1)
            self.assertEqual(result["attempted"], 1)
            self.assertEqual(result["remaining"], 2)
            result = run_contexts([context_fixture()], output, MockBackend(), [1, 2, 3], "synthetic", max_calls=1)
            self.assertEqual(result["attempted"], 1)
            self.assertEqual(result["resumed"], 1)

    def test_unfinished_journal_recovers_as_interrupted_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            run_contexts([context_fixture()], output, MockBackend(), [1], "synthetic")
            # Simulate process death after fsynced start but before terminal write.
            output.write_text("", encoding="utf-8")
            result = run_contexts([context_fixture()], output, MockBackend(), [1], "synthetic")
            self.assertEqual(result["attempted"], 0)
            self.assertEqual(result["statuses"], {"interrupted": 1})
            self.assertIsNone(json.loads(output.read_text())["latency_seconds"])

    def test_keyboard_interrupt_persists_terminal_record(self):
        class InterruptingBackend(BrokenBackend):
            def generate(self, *args, **kwargs):
                raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            with self.assertRaises(KeyboardInterrupt):
                run_contexts([context_fixture()], output, InterruptingBackend(), [1], "interrupted")
            self.assertEqual(json.loads(output.read_text())["status"], "interrupted")

    def test_transformers_uses_same_nonthinking_chat_framing_for_counts_and_generation(self):
        class Inputs(dict):
            def to(self, device):
                self.device = device
                return self
        class Sequence(list):
            @property
            def shape(self):
                return (len(self),)
            def __getitem__(self, index):
                value = super().__getitem__(index)
                return Sequence(value) if isinstance(index, slice) else value
        backend = object.__new__(TransformersBackend)
        processor = Mock()
        processor.apply_chat_template.return_value = "rendered nonthinking chat"
        processor.return_value = Inputs(input_ids=SimpleNamespace(shape=(1, 5)))
        processor.decode.return_value = '{"files":[],"source_ids":[],"edge_ids":[],"abstain":true}'
        backend.processor = processor
        backend.model = Mock(device="cpu")
        backend.model.generate.return_value = [Sequence(range(8))]
        backend.torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), inference_mode=nullcontext)
        set_seed = Mock()
        with patch.dict("sys.modules", {"transformers": SimpleNamespace(set_seed=set_seed)}):
            self.assertEqual(backend.count_tokens("prompt"), 5)
            result = backend.generate("prompt", seed=42, max_output_tokens=256, temperature=0.2)
        self.assertEqual(result["input_tokens"], 5)
        self.assertEqual(result["output_tokens"], 3)
        for call in processor.apply_chat_template.call_args_list:
            self.assertFalse(call.kwargs["enable_thinking"])
            self.assertTrue(call.kwargs["add_generation_prompt"])
        for call in processor.call_args_list:
            self.assertFalse(call.kwargs["add_special_tokens"])
        self.assertEqual(backend.model.generate.call_args.kwargs["max_new_tokens"], 256)
        set_seed.assert_called_once_with(42)

    def test_local_checkpoint_manifest_tracks_weight_and_tokenizer_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "model.safetensors").write_bytes(b"synthetic weights")
            (root / "config.json").write_text('{"model_type":"fixture"}')
            (root / "tokenizer.json").write_text('{"tokenizer":"fixture"}')
            first = checkpoint_manifest(root)
            self.assertEqual(first, checkpoint_manifest(root))
            self.assertEqual(len(first["files"]), 3)
            (root / "README.md").write_text("documentation")
            self.assertEqual(first, checkpoint_manifest(root))
            (root / "model.safetensors").write_bytes(b"changed synthetic weights")
            self.assertNotEqual(first["sha256"], checkpoint_manifest(root)["sha256"])
            second = checkpoint_manifest(root)
            (root / "tokenizer.json").write_text('{"tokenizer":"changed"}')
            self.assertNotEqual(second["sha256"], checkpoint_manifest(root)["sha256"])
        self.assertIsNone(checkpoint_manifest("google/gemma-4-E2B-it"))

    def test_local_checkpoint_manifest_requires_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "tokenizer.json").write_text("{}")
            with self.assertRaises(ValueError):
                checkpoint_manifest(directory)
            self.assertEqual(len(checkpoint_manifest(directory, require_weights=False)["files"]), 1)

    def test_gguf_default_capacity_reserves_output_and_rejects_overflow(self):
        default_ctx = inspect.signature(LlamaCppBackend).parameters["n_ctx"].default
        self.assertGreaterEqual(default_ctx, 4000 + 256)
        backend = object.__new__(LlamaCppBackend)
        backend.n_ctx = 4096
        backend.llm = Mock()
        backend.llm.tokenize.return_value = list(range(4000))
        backend._format = Mock(return_value=SimpleNamespace(prompt="chat", stop=[], stopping_criteria=None))
        with self.assertRaisesRegex(ValueError, "exceeds n_ctx"):
            backend.validate_context("prompt", 256)
        with self.assertRaisesRegex(ValueError, "exceeds n_ctx"):
            backend.generate("prompt", 17, 256, 0.2)
        backend.llm.create_completion.assert_not_called()

    def test_runner_performs_backend_capacity_preflight_before_attempting(self):
        backend = MockBackend()
        backend.validate_context = Mock(side_effect=ValueError("context overflow"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            with self.assertRaisesRegex(ValueError, "context overflow"):
                run_contexts([context_fixture()], output, backend, [1], "synthetic")
            self.assertFalse(output.exists())

    def test_tokenizer_identity_changes_with_vocab_template_and_special_tokens(self):
        class Tokenizer:
            def __init__(self):
                self.backend_tokenizer = SimpleNamespace(to_str=lambda: '{"vocab":{"a":1}}')
                self.chat_template = "template"
                self.special_tokens_map = {"eos_token": "<eos>", "additional_special_tokens": ["<special>"]}
        first = Tokenizer()
        second = Tokenizer()
        self.assertEqual(tokenizer_fingerprint(first), tokenizer_fingerprint(second))
        second.chat_template = "different template"
        self.assertNotEqual(tokenizer_fingerprint(first), tokenizer_fingerprint(second))
        second = Tokenizer()
        second.backend_tokenizer.to_str = lambda: '{"vocab":{"a":2}}'
        self.assertNotEqual(tokenizer_fingerprint(first), tokenizer_fingerprint(second))
        second = Tokenizer()
        second.special_tokens_map["eos_token"] = "changed"
        self.assertNotEqual(tokenizer_fingerprint(first), tokenizer_fingerprint(second))


if __name__ == "__main__":
    unittest.main()
