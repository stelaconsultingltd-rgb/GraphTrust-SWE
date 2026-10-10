"""Scientific CLI preflight tests; all backend identities and counts are fixtures."""

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from graphtrust.cli import main
from graphtrust.io import digest, read_json, write_json, write_jsonl
from graphtrust.provenance import implementation_sha256
from graphtrust.prediction import RESPONSE_CONTRACT_VERSION


ROOT = Path(__file__).resolve().parents[1]


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


class InferencePreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.protocol = read_json(ROOT / "configs/protocol.json")
        self.protocol_path = self.root / "protocol.json"
        write_json(self.protocol_path, self.protocol)
        self.contexts_path = self.root / "contexts.jsonl"
        self.manifest_path = self.root / "manifest.json"
        self.freeze_path = self.root / "frozen.json"
        self.rows = []
        source = "SOURCE fixture.py::f FILE fixture.py LINES 1-2 TRUNCATED false\ndef f():\n    pass\nEND SOURCE\n"
        for case in range(10):
            for condition in self.protocol["conditions"]:
                prompt = f"ISSUE\nfixture {case}\nEND ISSUE\nSOURCE PACK\n{source}END SOURCE PACK\nRELATIONSHIPS\n{condition}\nEND RELATIONSHIPS\n"
                self.rows.append({"response_contract_version": RESPONSE_CONTRACT_VERSION,
                                  "case_id": f"fixture-{case}", "repo": "r/r", "condition": condition,
                                  "prompt": prompt, "context_sha256": text_hash(prompt),
                                  "source_sha256": text_hash(source), "input_tokens": len(prompt),
                                  "token_method": "tokenizer", "visible_files": ["fixture.py"],
                                  "visible_source_ids": ["fixture.py::f"], "visible_edge_ids": []})
        self.backend = Mock()
        self.backend.identity = {"name": "transformers", "checkpoint_sha256": "a" * 64,
                                 "tokenizer_sha256": "b" * 64, "enable_thinking": False}
        self.backend.count_tokens.side_effect = lambda prompt: len(prompt)
        self.backend.generate.side_effect = AssertionError("Offline CLI tests never generate model output")
        case_ids = [f"fixture-{case}" for case in range(10)]
        self.manifest = {"schema_version": 2, "response_contract_version": RESPONSE_CONTRACT_VERSION,
                         "stage": "pilot", "contexts_sha256": digest(self.rows),
                         "protocol_sha256": digest(self.protocol), "implementation_sha256": implementation_sha256(),
                         "token_method": "tokenizer", "tokenizer_identity": "b" * 64,
                         "sampling_seeds": [17, 42], "case_ids": case_ids,
                         "selection_sha256": digest(case_ids), "cases": 10, "contexts": 60}
        self.frozen = {"schema_version": 2, "response_contract_version": RESPONSE_CONTRACT_VERSION,
                       "status": "frozen", "protocol_sha256": digest(self.protocol),
                       "implementation_sha256": implementation_sha256(), "backend_sha256": digest(self.backend.identity)}
        self.persist()

    def persist(self):
        write_jsonl(self.contexts_path, self.rows)
        write_json(self.manifest_path, self.manifest)
        write_json(self.freeze_path, self.frozen)

    def invoke(self, backend="transformers", seeds="17,42"):
        args = ["--protocol", str(self.protocol_path), "infer", "--contexts", str(self.contexts_path),
                "--out", str(self.root / "records.jsonl"), "--backend", backend, "--model", "offline-fixture-model",
                "--seeds", seeds, "--max-calls", "120", "--freeze", str(self.freeze_path)]
        constructor = "TransformersBackend" if backend == "transformers" else "LlamaCppBackend"
        with patch("graphtrust.inference." + constructor, return_value=self.backend) as build, patch("graphtrust.inference.run_contexts", return_value={"status": "offline_preflight_only"}) as run, redirect_stdout(io.StringIO()):
            try:
                main(args)
            except BaseException:
                self.assertFalse(run.called, "Invalid preflight must fail before scheduling generation")
                raise
        self.backend.generate.assert_not_called()
        return build, run

    def test_current_exact_pilot_preflight_forwards_the_registered_configuration(self):
        build, run = self.invoke()
        build.assert_called_once_with("offline-fixture-model")
        self.assertEqual(self.backend.count_tokens.call_count, 60)
        self.assertEqual(run.call_args.args[:5], (self.rows, str(self.root / "records.jsonl"), self.backend, [17, 42], "offline-fixture-model"))
        self.assertEqual(run.call_args.kwargs, {"max_output_tokens": 256, "timeout_seconds": 90, "temperature": 0.2, "max_calls": 120})

    def test_real_inference_requires_the_companion_manifest(self):
        self.manifest_path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.invoke()

    def test_context_artifact_checksum_mismatch_is_rejected(self):
        self.rows[0]["prompt"] += "changed"
        write_jsonl(self.contexts_path, self.rows)
        with self.assertRaisesRegex(ValueError, "checksum-verified"):
            self.invoke()

    def test_legacy_manifest_fails_before_backend_loading(self):
        self.manifest["schema_version"] = 1
        self.persist()
        with self.assertRaisesRegex(ValueError, "response-contract v2"):
            self.invoke()

    def test_foreign_protocol_and_implementation_are_rejected(self):
        original = deepcopy(self.manifest)
        for field in ("protocol_sha256", "implementation_sha256"):
            with self.subTest(field=field):
                self.manifest = dict(original, **{field: "different"})
                self.persist()
                with self.assertRaisesRegex(ValueError, "current, exact"):
                    self.invoke()

    def test_approximate_token_accounting_cannot_run_a_real_backend(self):
        self.manifest["token_method"] = "byte_upper_bound"
        self.persist()
        with self.assertRaisesRegex(ValueError, "current, exact"):
            self.invoke()

    def test_wrong_sampling_seed_schedule_is_rejected(self):
        for seeds in ("17", "17,99", "42,17"):
            with self.subTest(seeds=seeds), self.assertRaisesRegex(ValueError, "Sampling seeds"):
                self.invoke(seeds=seeds)

    def test_matching_counts_do_not_override_a_wrong_tokenizer_identity(self):
        self.backend.identity["tokenizer_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "tokenizer differs"):
            self.invoke()

    def test_runtime_count_mismatch_rejects_before_generation(self):
        self.rows[0]["input_tokens"] += 1
        self.manifest["contexts_sha256"] = digest(self.rows)
        self.persist()
        with self.assertRaisesRegex(ValueError, "Runtime tokenizer counts"):
            self.invoke()

    def test_matching_primary_holdout_freeze_is_accepted(self):
        self.manifest["stage"] = "holdout"
        self.persist()
        _, run = self.invoke()
        self.assertTrue(run.called)

    def test_primary_holdout_rejects_a_different_runtime_or_checkpoint(self):
        self.manifest["stage"] = "holdout"
        self.persist()
        self.backend.identity["checkpoint_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "accepted pilot freeze"):
            self.invoke()

    def test_primary_holdout_requires_a_current_matching_scientific_freeze(self):
        self.manifest["stage"] = "holdout"
        original = deepcopy(self.frozen)
        for field, value in (("status", "development"), ("protocol_sha256", "different"), ("implementation_sha256", "different")):
            with self.subTest(field=field):
                self.frozen = dict(original, **{field: value})
                self.persist()
                with self.assertRaisesRegex(ValueError, "accepted pilot freeze"):
                    self.invoke()

    def test_separate_replication_runtime_uses_its_own_exact_identity_and_seed(self):
        self.manifest.update(stage="replication", sampling_seeds=[17])
        self.backend.identity["name"] = "llama_cpp"
        self.backend.identity["tokenizer_sha256"] = "e" * 64
        self.manifest["tokenizer_identity"] = "e" * 64
        self.persist()
        _, run = self.invoke(backend="gguf", seeds="17")
        self.assertEqual(run.call_args.args[3], [17])

    def test_mock_inference_remains_available_without_scientific_manifest(self):
        self.manifest_path.unlink()
        args = ["--protocol", str(self.protocol_path), "infer", "--contexts", str(self.contexts_path),
                "--out", str(self.root / "mock-records.jsonl"), "--backend", "mock", "--model", "synthetic-mock", "--seeds", "99"]
        with patch("graphtrust.inference.run_contexts", return_value={"status": "synthetic"}) as run, redirect_stdout(io.StringIO()):
            main(args)
        self.assertTrue(run.call_args.args[2].synthetic)
        self.assertEqual(run.call_args.args[3], [99])


if __name__ == "__main__":
    unittest.main()
