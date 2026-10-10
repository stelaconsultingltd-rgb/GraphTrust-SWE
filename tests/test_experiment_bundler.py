"""Ephemeral synthetic tooling fixtures; never experimental acceptance/evidence."""
import base64
from copy import deepcopy
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location("experiment_bundler", ROOT / "scripts/bundle_kaggle_experiment.py")
bundler = module_from_spec(SPEC)
SPEC.loader.exec_module(bundler)


class ExperimentBundlerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protocol = bundler.read_json(ROOT / "configs/protocol.json")
        self.wheel = ROOT / "dist/graphtrust_swe-0.1.0-py3-none-any.whl"
        self.code_hash = bundler.wheel_implementation(self.wheel)
        self.backend = {"name": "transformers", "model_path": "/kaggle/input/models/example/e2b/1",
            "checkpoint_sha256": "a" * 64, "tokenizer_sha256": "b" * 64, "enable_thinking": False}
        self.freeze = {"status": "frozen", "protocol": self.protocol,
            "protocol_sha256": bundler.digest(self.protocol), "implementation_sha256": self.code_hash,
            "pilot_manifest_sha256": "c" * 64, "pilot_records_sha256": "d" * 64,
            "backend_sha256": bundler.digest(self.backend), "tokenizer_identity": "b" * 64,
            "parse_rate": 1, "graph_citation_rate": 1, "primary_model": "test-fixture-only"}
        self.rows, self.manifest = self.cohort("holdout", self.backend)
        self.policy = {"session_seconds": 3600, "stage_seconds": 86400,
            "free_quota_seconds": 86400, "max_sessions": 8, "batch_max_calls": 120, "free_t4_only": True}

    def cohort(self, stage, backend):
        rows, ids = [], []
        number = 10 if stage == "holdout" else 5
        for repo in self.protocol["holdout_repositories"]:
            for index in range(number):
                identity = repo.replace("/", "__") + "-" + str(index)
                ids.append(identity)
                source = f"SOURCE s FILE source.py LINES 1-2\ndef f(): pass # {identity}\n"
                for condition in bundler.CONDITIONS:
                    prompt = "ISSUE fixture-only\nSOURCE PACK\n" + source + "END SOURCE PACK\n" + condition
                    rows.append({"case_id": identity, "repo": repo, "condition": condition, "prompt": prompt,
                        "context_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                        "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "input_tokens": 100,
                        "token_method": "tokenizer"})
        manifest = {"stage": stage, "token_method": "tokenizer", "implementation_sha256": self.code_hash,
            "protocol_sha256": bundler.digest(self.protocol), "contexts_sha256": bundler.digest(rows),
            "tokenizer_identity": backend["tokenizer_sha256"], "case_ids": ids, "selection_sha256": bundler.digest(ids),
            "cases": len(ids), "contexts": len(rows), "shortfalls": {}, "selection_uses_gold": False,
            "source_pack_rule": self.protocol["source_pack_rule"], "model_edge_rule": self.protocol["model_edge_rule"],
            "sampling_seeds": [17, 42] if stage == "holdout" else [17]}
        return rows, manifest

    def validate(self, **kwargs):
        values = dict(contexts=self.rows, manifest=self.manifest, protocol=self.protocol,
            frozen=self.freeze, backend=self.backend)
        values.update(kwargs)
        return bundler.validate_inputs(**values)

    def inputs(self):
        paths = {}
        for name, value in (("manifest", self.manifest), ("protocol", self.protocol), ("freeze", self.freeze), ("backend", self.backend)):
            paths[name] = self.root / (name + ".json")
            bundler.save(paths[name], value)
        paths["contexts"] = self.root / "contexts.jsonl"
        paths["contexts"].write_text("".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf8")
        return paths

    def expected(self):
        return bundler.schedule(self.rows, [17, 42], self.freeze["primary_model"], self.backend, self.protocol)

    def record(self, run_id, expected, status):
        return {**expected[run_id], "run_id": run_id, "status": status, "synthetic": False}

    def test_complete_schedule_and_allowlisted_generated_archive(self):
        paths = self.inputs()
        output = self.root / "batch.py"
        result = bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"],
            paths["freeze"], paths["backend"], output, self.policy)
        self.assertEqual(result["schedule_attempts"], 720)
        generated = module_from_spec(spec_from_file_location("generated_test", output))
        generated.__spec__.loader.exec_module(generated)
        archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(generated.BUNDLE_BASE64)))
        self.assertEqual(set(archive.namelist()), {"contexts/contexts.jsonl", "contexts/manifest.json", "protocol.json",
            "accepted-freeze.json", "accepted-backend.json", "package/" + self.wheel.name})
        with patch.object(generated, "BUNDLE_BASE64", generated.BUNDLE_BASE64):
            generated.extract_bundle(self.root / "extracted")
        self.assertEqual((self.root / "extracted/contexts/contexts.jsonl").read_bytes(), paths["contexts"].read_bytes())
        with self.assertRaisesRegex(ValueError, "immutable"):
            bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"], paths["freeze"], paths["backend"], output, self.policy)

    def test_no_freeze_or_backend_substitution(self):
        with self.assertRaisesRegex(ValueError, "accepted scientific freeze"):
            self.validate(frozen={**self.freeze, "status": "development_not_frozen"})
        changed = {**self.backend, "torch": "different"}
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.validate(backend=changed)
        with self.assertRaisesRegex(ValueError, "cohort"):
            self.validate(contexts=self.rows[:-6], manifest={**self.manifest, "contexts_sha256": bundler.digest(self.rows[:-6])})

    def test_declared_primary_shortfalls_and_corresponding_replication_subset(self):
        requested = dict(zip(self.protocol["holdout_repositories"], [10, 3, 0, 8, 6, 4]))
        selected = [identity for repo, count in requested.items() for identity in self.manifest["case_ids"]
            if identity.startswith(repo.replace("/", "__") + "-") and int(identity.rsplit("-", 1)[1]) < count]
        rows = [row for row in self.rows if row["case_id"] in selected]
        deficits = {repo: {"requested": 10, "available": count} for repo, count in requested.items() if count < 10}
        manifest = {**self.manifest, "case_ids": selected, "cases": len(selected), "contexts": len(rows),
            "selection_sha256": bundler.digest(selected), "contexts_sha256": bundler.digest(rows), "shortfalls": deficits}
        seeds = self.validate(contexts=rows, manifest=manifest)
        self.assertEqual(len(bundler.schedule(rows, seeds, "primary", self.backend, self.protocol)), 372)
        old_rows, old_manifest = self.rows, self.manifest
        self.rows, self.manifest = rows, manifest
        paths = self.inputs()
        result = bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"],
            paths["freeze"], paths["backend"], self.root / "shortfall.py", self.policy)
        self.rows, self.manifest = old_rows, old_manifest
        self.assertEqual(result["schedule_attempts"], 372)
        self.assertEqual(result["nominal_attempts"], 720)
        self.assertEqual(result["actual_issues"], 31)
        self.assertEqual(result["declared_shortfalls"], deficits)
        wrong = deepcopy(manifest)
        wrong["shortfalls"][self.protocol["holdout_repositories"][1]]["available"] = 4
        with self.assertRaisesRegex(ValueError, "declared structural shortfalls"):
            self.validate(contexts=rows, manifest=wrong)
        with self.assertRaisesRegex(ValueError, "Missing arms"):
            self.validate(contexts=rows[1:], manifest={**manifest, "contexts_sha256": bundler.digest(rows[1:])})
        backend = {"name": "llama_cpp", "model_path": "/kaggle/input/official/e4b.gguf", "model_sha256": "e" * 64,
            "tokenizer_sha256": "f" * 64, "enable_thinking": False}
        secondary, secondary_manifest = self.cohort("replication", backend)
        fixed_ids = [identity for repo, count in requested.items() for identity in selected
            if identity.startswith(repo.replace("/", "__") + "-") and int(identity.rsplit("-", 1)[1]) < min(5, count)]
        secondary = [row for row in secondary if row["case_id"] in fixed_ids]
        secondary_manifest.update(case_ids=fixed_ids, cases=len(fixed_ids), contexts=len(secondary),
            selection_sha256=bundler.digest(fixed_ids), contexts_sha256=bundler.digest(secondary), shortfalls=deficits)
        lock = self.gguf_lock(backend)
        seeds = self.validate(contexts=secondary, manifest=secondary_manifest, backend=backend, primary_manifest=manifest, runtime_lock=lock)
        self.assertEqual(len(fixed_ids), 22)
        self.assertEqual(len(bundler.schedule(secondary, seeds, "secondary", backend, self.protocol)), 132)

    def gguf_lock(self, backend):
        lock = {"status": "development_runtime_accepted", "build_and_runtime_tested": True,
            "backend_sha256": bundler.digest(backend), "llama_cpp_python_commit": bundler.GGUF_COMMIT,
            "vendored_llama_cpp_commit": bundler.LLAMA_COMMIT, "llama_cpp_python_version": "0.3.36",
            "cuda_cmake_args": "-DGGML_CUDA=on", "jinja2_version": "3.1.6", "model_sha256": backend["model_sha256"],
            "wheel_path": "/kaggle/input/runtime/llama_cpp_python.whl"}
        lock.update({name: "a" * 64 for name in ("built_wheel_sha256", "development_records_sha256", "build_log_sha256", "environment_sha256")})
        return lock

    def test_source_and_evaluator_leakage_guards(self):
        rows = deepcopy(self.rows)
        rows[0]["patch"] = "gold"
        with self.assertRaisesRegex(ValueError, "Evaluator"):
            self.validate(contexts=rows, manifest={**self.manifest, "contexts_sha256": bundler.digest(rows)})
        rows = deepcopy(self.rows)
        rows[0]["prompt"] = rows[0]["prompt"].replace("def f", "def g")
        rows[0]["context_sha256"] = hashlib.sha256(rows[0]["prompt"].encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, "Source checksum"):
            self.validate(contexts=rows, manifest={**self.manifest, "contexts_sha256": bundler.digest(rows)})

    def test_failures_and_orphan_starts_retained_without_retry(self):
        expected = self.expected()
        first, second = list(expected)[:2]
        terminal = self.record(first, expected, "timeout")
        starts = [self.record(first, expected, "started"), self.record(second, expected, "started")]
        output = self.root / "records.jsonl"
        original = json.dumps(terminal) + "\n"
        output.write_text(original, encoding="utf8")
        Path(str(output) + ".attempts.jsonl").write_text("".join(json.dumps(row) + "\n" for row in starts), encoding="utf8")
        results, journal = bundler.finalize_interrupted(output, expected)
        self.assertEqual(results[first]["status"], "timeout")
        self.assertEqual(results[second]["status"], "interrupted")
        self.assertEqual(len(journal), 2)
        self.assertTrue(output.read_text(encoding="utf8").startswith(original))
        once = output.read_bytes()
        bundler.finalize_interrupted(output, expected)
        self.assertEqual(output.read_bytes(), once)

    def test_resume_bundle_retains_all_history_and_rejects_removal(self):
        paths = self.inputs()
        first_result = bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"],
            paths["freeze"], paths["backend"], self.root / "first.py", self.policy)
        expected = self.expected()
        first = next(iter(expected))
        resume = self.root / "resume"
        resume.mkdir()
        records, journal = resume / "records.jsonl", resume / "records.jsonl.attempts.jsonl"
        records.write_text(json.dumps(self.record(first, expected, "parse_error")) + "\n", encoding="utf8")
        journal.write_text(json.dumps(self.record(first, expected, "started")) + "\n", encoding="utf8")
        ledger = bundler.reserve_session({}, first_result["experiment_sha256"], self.policy)
        ledger["sessions"][-1].update(status="finished", records_sha256=bundler.file_hash(records), journal_sha256=bundler.file_hash(journal), history_after=bundler.history_snapshot(records))
        bundler.save(resume / "session-ledger.json", ledger)
        output = self.root / "second.py"
        second_result = bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"],
            paths["freeze"], paths["backend"], output, self.policy, resume=resume)
        self.assertEqual(second_result["experiment_sha256"], first_result["experiment_sha256"])
        module = module_from_spec(spec_from_file_location("generated_resume_test", output))
        module.__spec__.loader.exec_module(module)
        archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(module.BUNDLE_BASE64)))
        self.assertEqual(archive.read("resume/records.jsonl"), records.read_bytes())
        self.assertEqual(archive.read("resume/records.jsonl.attempts.jsonl"), journal.read_bytes())
        records.write_text("", encoding="utf8")
        journal.write_text("", encoding="utf8")
        with self.assertRaisesRegex(ValueError, "pinned session prefix"):
            bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"], paths["freeze"], paths["backend"], self.root / "bad-resume.py", self.policy, resume=resume)

    def test_setup_failure_empty_logs_are_resumable(self):
        output = self.root / "records.jsonl"
        terminal, journal = bundler.finalize_interrupted(output, self.expected())
        self.assertEqual(terminal, {})
        self.assertEqual(journal, {})
        self.assertEqual(output.read_bytes(), b"")
        self.assertEqual(Path(str(output) + ".attempts.jsonl").read_bytes(), b"")

    def test_finalized_failure_cannot_disappear_after_later_reserved_crash(self):
        paths = self.inputs()
        initial = bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"],
            paths["freeze"], paths["backend"], self.root / "initial.py", self.policy)
        expected = self.expected()
        first = next(iter(expected))
        resume = self.root / "crash-resume"
        resume.mkdir()
        records = resume / "records.jsonl"
        journal = resume / "records.jsonl.attempts.jsonl"
        records.write_text(json.dumps(self.record(first, expected, "parse_error")) + "\n", encoding="utf8")
        journal.write_text(json.dumps(self.record(first, expected, "started")) + "\n", encoding="utf8")
        ledger = bundler.reserve_session({}, initial["experiment_sha256"], self.policy)
        ledger["sessions"][-1].update(status="finished", records_sha256=bundler.file_hash(records), journal_sha256=bundler.file_hash(journal), history_after=bundler.history_snapshot(records))
        ledger = bundler.reserve_session(ledger, initial["experiment_sha256"], self.policy, records, expected)
        bundler.save(resume / "session-ledger.json", ledger)
        records.write_bytes(b"")
        journal.write_bytes(b"")
        with self.assertRaises(ValueError):
            bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"],
                paths["freeze"], paths["backend"], self.root / "lost-failure.py", self.policy, resume=resume)

    def test_valid_crash_extension_preserves_failure_and_orphan_without_retry(self):
        paths = self.inputs()
        initial = bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"],
            paths["freeze"], paths["backend"], self.root / "initial-crash-extension.py", self.policy)
        expected = self.expected()
        first, second, third = list(expected)[:3]
        resume = self.root / "valid-crash-extension"
        resume.mkdir()
        records, journal = resume / "records.jsonl", resume / "records.jsonl.attempts.jsonl"
        ledger = bundler.reserve_session({}, initial["experiment_sha256"], self.policy, records, expected)
        records.write_text(json.dumps(self.record(first, expected, "parse_error")) + "\n", encoding="utf8")
        journal.write_text(json.dumps(self.record(first, expected, "started")) + "\n", encoding="utf8")
        ledger["sessions"][-1].update(status="finished", history_after=bundler.history_snapshot(records))
        baseline_records, baseline_journal = records.read_bytes(), journal.read_bytes()
        ledger = bundler.reserve_session(ledger, initial["experiment_sha256"], self.policy, records, expected)
        self.assertEqual(ledger["sessions"][-1]["history_before"]["records"]["bytes"], len(baseline_records))
        with records.open("a", encoding="utf8", newline="\n") as handle:
            handle.write(json.dumps(self.record(second, expected, "timeout")) + "\n")
        with journal.open("a", encoding="utf8", newline="\n") as handle:
            handle.write(json.dumps(self.record(second, expected, "started")) + "\n")
            handle.write(json.dumps(self.record(third, expected, "started")) + "\n")
        bundler.save(resume / "session-ledger.json", ledger)
        result = bundler.build_bundle(self.wheel, paths["contexts"], paths["manifest"], paths["protocol"],
            paths["freeze"], paths["backend"], self.root / "valid-next.py", self.policy, resume=resume)
        self.assertEqual(result["experiment_sha256"], initial["experiment_sha256"])
        before_recovery = records.read_bytes()
        recovered, terminal, starts = bundler.recover_history(ledger, records, expected)
        self.assertTrue(records.read_bytes().startswith(before_recovery))
        self.assertTrue(records.read_bytes().startswith(baseline_records))
        self.assertTrue(journal.read_bytes().startswith(baseline_journal))
        self.assertEqual([terminal[key]["status"] for key in (first, second, third)], ["parse_error", "timeout", "interrupted"])
        self.assertEqual(len(starts), 3)
        self.assertEqual(recovered["sessions"][-1]["recovery_kind"], "reserved_session_crash")
        final_bytes = records.read_bytes()
        again, _, _ = bundler.recover_history(recovered, records, expected)
        self.assertEqual(records.read_bytes(), final_bytes)
        next_ledger = bundler.reserve_session(again, initial["experiment_sha256"], self.policy, records, expected)
        self.assertEqual(next_ledger["sessions"][-1]["history_before"]["records"]["rows"], 3)
        # A valid JSON status edit is still an impermissible prefix rewrite.
        records.write_bytes(final_bytes.replace(b'"parse_error"', b'"error"', 1))
        with self.assertRaisesRegex(ValueError, "pinned session prefix"):
            bundler.validate_ledger_history(next_ledger, records, expected)

    def test_legacy_reserved_history_requires_explicit_recovery(self):
        expected = self.expected()
        output = self.root / "legacy-records.jsonl"
        bundler.finalize_interrupted(output, expected)
        ledger = {"schema_version": 1, "experiment_sha256": "experiment", "policy": self.policy,
            "sessions": [{"session": 1, "status": "reserved", "reservation_seconds": self.policy["session_seconds"]}]}
        with self.assertRaisesRegex(ValueError, "Legacy ledger"):
            bundler.reserve_session(ledger, "experiment", self.policy, output, expected)

    def test_schedule_matches_current_runner_and_batch_cap_counts_new_attempts(self):
        from graphtrust.inference import MockBackend, run_contexts
        backend = MockBackend({"files": ["invisible.py"], "source_ids": [], "edge_ids": [], "abstain": False})
        rows = self.rows[:2]
        output = self.root / "synthetic-contract-only.jsonl"
        expected = bundler.schedule(rows, [17, 42], "fixture", backend.identity, self.protocol)
        first = run_contexts(rows, output, backend, [17, 42], "fixture", max_calls=2,
            max_output_tokens=self.protocol["max_output_tokens"], timeout_seconds=self.protocol["timeout_seconds"], temperature=self.protocol["temperature"])
        old_bytes = output.read_bytes()
        second = run_contexts(rows, output, backend, [17, 42], "fixture", max_calls=1,
            max_output_tokens=self.protocol["max_output_tokens"], timeout_seconds=self.protocol["timeout_seconds"], temperature=self.protocol["temperature"])
        records = bundler.read_jsonl(output)
        self.assertEqual(first["attempted"], 2)
        self.assertEqual(second["attempted"], 1)
        self.assertTrue(output.read_bytes().startswith(old_bytes))
        self.assertEqual([r["run_id"] for r in records], list(expected)[:3])
        self.assertEqual([r["status"] for r in records], ["parse_error"] * 3)
        self.assertTrue(all(r["synthetic"] for r in records))
        with self.assertRaisesRegex(ValueError, "Synthetic"):
            bundler.validate_history(records, bundler.read_jsonl(Path(str(output) + ".attempts.jsonl")), expected)

    def test_foreign_duplicate_and_changed_history_rejected(self):
        expected = self.expected()
        first = next(iter(expected))
        record = self.record(first, expected, "error")
        start = self.record(first, expected, "started")
        for rows, starts in (([{**record, "run_id": "foreign"}], [start]), ([record, record], [start]),
                ([{**record, "generation": {}}], [start]), ([record], []), ([record], [start, start])):
            with self.assertRaises(ValueError):
                bundler.validate_history(rows, starts, expected)
        path = self.root / "truncated.jsonl"
        path.write_text(json.dumps(record), encoding="utf8")
        with self.assertRaisesRegex(ValueError, "Unterminated"):
            bundler.read_jsonl(path)

    def test_conservative_crashed_session_quota_and_session_cap(self):
        policy = {**self.policy, "stage_seconds": 7200, "free_quota_seconds": 7200, "max_sessions": 2}
        bundler.validate_policy("holdout", policy)
        ledger = bundler.reserve_session({}, "experiment", policy)
        self.assertEqual(ledger["sessions"][0]["status"], "reserved")
        ledger = bundler.reserve_session(ledger, "experiment", policy)
        with self.assertRaisesRegex(ValueError, "exhausted"):
            bundler.reserve_session(ledger, "experiment", policy)
        with self.assertRaisesRegex(ValueError, "different"):
            bundler.reserve_session(ledger, "other", policy)
        for changed in ({"session_seconds": 10801}, {"free_t4_only": False}, {"max_sessions": 9}, {"batch_max_calls": 721}):
            with self.assertRaises(ValueError):
                bundler.validate_policy("holdout", {**self.policy, **changed})

    def test_backend_and_checkpoint_saved_before_mismatch_guard(self):
        class FixtureBackend:
            identity = {**self.backend, "tokenizer_sha256": "wrong", "local_checkpoint": {"sha256": "actual-checkpoint"}}
            def count_tokens(self, prompt):
                raise AssertionError("Mismatch must fail before count/generation")
        with self.assertRaisesRegex(ValueError, "Actual backend"):
            bundler.check_backend_preflight(FixtureBackend(), self.rows, self.manifest, self.protocol, self.backend, self.root)
        self.assertEqual(bundler.read_json(self.root / "actual-backend.json")["tokenizer_sha256"], "wrong")
        self.assertEqual(bundler.read_json(self.root / "actual-checkpoint-manifest.json")["sha256"], "actual-checkpoint")

    def test_count_mismatch_persists_diagnostic(self):
        class FixtureBackend:
            identity = self.backend
            def count_tokens(self, prompt):
                return 101
        with self.assertRaisesRegex(ValueError, "exact token counts"):
            bundler.check_backend_preflight(FixtureBackend(), self.rows, self.manifest, self.protocol, self.backend, self.root)
        self.assertEqual(bundler.read_json(self.root / "token-count-preflight.json")["status"], "mismatch")

    def test_replication_fixed_subset_and_real_development_lock_required(self):
        backend = {"name": "llama_cpp", "model_path": "/kaggle/input/official/e4b.gguf", "model_sha256": "e" * 64,
            "tokenizer_sha256": "f" * 64, "enable_thinking": False}
        rows, manifest = self.cohort("replication", backend)
        with self.assertRaisesRegex(ValueError, "runtime remains untested"):
            self.validate(contexts=rows, manifest=manifest, backend=backend, primary_manifest=self.manifest)
        lock = self.gguf_lock(backend)
        seeds = self.validate(contexts=rows, manifest=manifest, backend=backend, primary_manifest=self.manifest, runtime_lock=lock)
        self.assertEqual(len(bundler.schedule(rows, seeds, "replication", backend, self.protocol)), 180)
        primary = deepcopy(self.manifest)
        primary["case_ids"][0], primary["case_ids"][5] = primary["case_ids"][5], primary["case_ids"][0]
        primary["selection_sha256"] = bundler.digest(primary["case_ids"])
        with self.assertRaisesRegex(ValueError, "fixed first five"):
            self.validate(contexts=rows, manifest=manifest, backend=backend, primary_manifest=primary, runtime_lock=lock)

    def test_model_or_evaluator_wheel_assets_refused(self):
        for name in ("graphtrust/models/weights.safetensors", "graphtrust/evaluator/gold.jsonl", "../escape.py", "tests/test.py"):
            wheel = self.root / "bad.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(name, b"fixture")
            with self.assertRaises(ValueError):
                bundler.wheel_implementation(wheel)


if __name__ == "__main__":
    unittest.main()
