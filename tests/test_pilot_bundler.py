"""Private pilot packaging/version checks using synthetic tooling assets."""
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import unittest

import tests.test_experiment_bundler as fixture_module


ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location("pilot_bundler", ROOT / "scripts/bundle_kaggle_pilot.py")
bundler = module_from_spec(SPEC)
SPEC.loader.exec_module(bundler)


class PilotBundlerTests(unittest.TestCase):
    def setUp(self):
        fixture = fixture_module.ExperimentBundlerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.wheel, self.protocol = fixture.root, fixture.wheel, fixture.protocol
        self.rows = deepcopy(fixture.rows[:60])
        ids = list(dict.fromkeys(row["case_id"] for row in self.rows))
        for row in self.rows:
            row["repo"] = self.protocol["development_repositories"][ids.index(row["case_id"]) % 4]
        self.manifest = {"schema_version": 2, "response_contract_version": "files_citations_v2",
            "stage": "pilot", "token_method": "tokenizer", "selection_uses_gold": False,
            "cases": 10, "contexts": 60, "case_ids": ids, "implementation_sha256": fixture.code_hash,
            "contexts_sha256": bundler.digest(self.rows), "protocol_sha256": bundler.digest(self.protocol)}

    def test_current_pilot_bundle_preserves_bytes_and_contains_v2_notebook_guards(self):
        contexts, manifest, protocol = (self.root / name for name in ("contexts.jsonl", "manifest.json", "protocol.json"))
        contexts.write_text("".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8")
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        protocol.write_text(json.dumps(self.protocol), encoding="utf-8")
        output = self.root / "pilot.py"
        result = bundler.build_bundle(self.wheel, contexts, manifest, protocol, output,
            ROOT / "notebooks/kaggle_gemma_pilot.ipynb")
        inspected = bundler.inspect_script(output)
        self.assertEqual(inspected["files"], result["files"])
        self.assertEqual(len(result["bundle_sha256"]), 64)
        source = output.read_text(encoding="utf-8")
        self.assertIn("RESPONSE_CONTRACT_VERSION", source)
        self.assertIn("Rebuild fresh response-contract v2 contexts", source)
        self.assertEqual(result["files"]["contexts/contexts.jsonl"]["bytes"], len(contexts.read_bytes()))

    def test_legacy_manifest_or_context_or_protocol_cannot_enter_v2_pilot(self):
        for target in ("protocol", "manifest", "context"):
            rows, manifest, protocol = deepcopy(self.rows), deepcopy(self.manifest), deepcopy(self.protocol)
            value = {"protocol": protocol, "manifest": manifest, "context": rows[0]}[target]
            value["response_contract_version"] = "legacy"
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "response-contract v2"):
                bundler.validate_inputs(rows, manifest, protocol)


if __name__ == "__main__":
    unittest.main()
