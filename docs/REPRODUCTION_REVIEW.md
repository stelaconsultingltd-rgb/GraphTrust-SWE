# Reproduction review — 10 October 2026

**Initial audit superseded; final revision rechecked in the addendum below.** After the initial checks, a development source-visibility audit triggered one bounded, pre-model source-packing revision. The initial identified wheel must not be used for the revised pilot. The addendum identifies the replacement wheel and fresh checks.

**Latest runtime status:** the v8 private Kaggle pilot stopped at the tokenizer identity guard before localization. The protocol remains unfrozen. The final addenda document this preserved failure, the updated diagnostic notebook, and the independently verified v9 replacement bundle prepared from actual Kaggle tokenizer assets. Successful runtime guards and real pilot acceptance remain pending.

This review covers the identified local implementation and its portable Kaggle pilot harness. It does not establish model throughput, pilot acceptance, a frozen protocol, or an empirical benchmark result. The local demonstrations use `synthetic-mock` and are excluded from research evidence.

## Identified artifacts

| Artifact | SHA-256 |
|---|---|
| Release wheel `dist/graphtrust_swe-0.1.0-py3-none-any.whl` | `da5f34fa0f6e62e738933356385eb5c7f53990444556a45ae052361d3a059088` |
| Python implementation, canonical relative-path/file-hash inventory | `defd3dc1dc2d30cf05cedbdce1e887fe29712bcd1313db4a71b9e5b1bfb47789` |
| Protocol, canonical JSON digest | `f22143a1f57b4ee7ebd443246d5ad8ae04cd2b45ac322fc948ed996504793333` |
| Protocol file bytes | `ce32c138477ae6434a6812e620c99da7efa1734cfefe6a96175a6a42ff3b53ee` |
| Kaggle notebook | `7f7fc5e98b8d223cb63530c9846ee168c0e32bffdd9d7073c7cd77c702521145` |
| Demonstration notebook | `f273150efdf74dd633fee60ef4ef1f8325a865495e47276741388fc8ad69fb1d` |
| Script bundler | `f74a65ecdef80bc8fdc5d027594865b4769c3a5cba10a543ec24d5f9d5ba3d32` |

The release wheel was freshly rebuilt with `.venv/Scripts/python.exe -m build --wheel`. Its packaged Python inventory exactly matches the source implementation digest. Its bundled protocol is byte-identical to `configs/protocol.json`; the primary contrast uses **file recall@5**, with false minus missing relationships. The implementation digest was unchanged before building and after the checks below. Package source was not edited during this review.

`runs/reproduction-review/wheel-inventory.json` records the entire wheel inventory. The wheel includes original code, synthetic fixtures, the protocol, license, notice, and distribution metadata. It contains no evaluator directory, gold JSON, context JSONL, corpus parquet, model weights, or reference patches/tests. The code's evaluator functions do not include evaluator data.

## Fresh checks and evidence

Local environment: Windows 11, Python 3.12.14. Evidence files are preserved under `runs/reproduction-review/`; their hashes and environment details are recorded in `verification-metadata.json`.

| Check | Result | Evidence |
|---|---|---|
| Metrics unit tests | 19 passed | `metrics-tests.log` |
| Full unittest discovery | 125 passed | `full-tests.log` |
| Build release wheel | Passed | `build.log` |
| Execute demonstration notebook code cells in order with a fresh output directory | Five cells passed; six conditions, twelve synthetic attempts | `notebook-execution.log`, `demo/` |
| Execute Kaggle notebook code cells in order with `GRAPHTRUST_RUN_REAL=0` and a fresh working directory | Five cells passed; installs, model loading, inference, and freeze skipped | `notebook-execution.log` |
| Install wheel with `pip --no-deps --target` and run CLI from a separate working directory | Passed using packaged protocol and synthetic fixtures | `wheel-install.log`, `wheel-standalone.log`, `standalone-cwd/demo/` |
| Compile both notebooks' code cells | Passed | Included in notebook execution |
| Wheel Python identity, packaged protocol bytes, license inventory, excluded assets | Passed | `wheel-inventory.json` |

The full test log's SHA-256 is `78704b46b0f454568de26632b57e42fcee95deeeff2cfef51a797c3756c094a7`. The notebook execution log's SHA-256 is `46f6b5b2962b3492d470db8c66de2154ad2047ef818e4d2a6e7fa193015ca174`.

## Real pilot preflight review

The real notebook path requires a verified local release wheel, attached official model checkpoint, exact-tokenizer pilot contexts, and protocol. Online bootstrap pins Transformers 5.19.0 and Jinja2 3.1.6 while retaining Kaggle's installed CUDA-compatible Torch; it records the resolved package environment. Offline bootstrap accepts a supplied hashed wheelhouse lock. Runtime checkpoint files are hashed and preserved in the model manifest.

Before attempting localization, the harness validates ten issues and sixty contexts, requires a free T4 session, checks package implementation/protocol/tokenizer identities, and recounts every rendered prompt with the loaded inference backend. Any mismatch stops inference. Generation uses paired seeds 17 and 42, at most 256 output tokens, disabled thinking, a ninety-second elapsed-time allowance, and at most 120 pilot calls. The notebook invokes the package freeze gate and saves its stdout, stderr, exit status, and acceptance/failure diagnostic.

The portable bundler accepts exactly four archive assets: the release wheel, contexts JSONL, context manifest, and protocol. It checks exact-tokenizer eligibility, all six conditions per issue, prompt/source integrity, gold-independent selection, protocol identity, and wheel-code identity. Its supervisor imposes a wall-clock budget of at most three hours, preserves logs and terminal failures, and records interrupted attempts. Model weights are attached separately through Kaggle model data sources.

The GPU branch has been inspected and compiled, but has **not** been executed in this review. Only successful real pilot records and the freeze gate can establish readiness for holdout inference. Kaggle kernel submission, runtime outcome, and competition submission are outside these local checks.

## Pilot v7 bundle

The v7 bundle was held before generation when the source-visibility audit triggered a bounded source-packing revision: anchor shared source windows at deterministic clean callsites and filter displayed relationships to visible callsites before corruption. A matching wheel and exact-tokenizer contexts must be rebuilt after this revision. No v7 or validation-only fixture script should be submitted. The final matching bundle's exact inventory, context digest, script digest, and strict validation result will be appended after it is built.

## Final source-visibility revision addendum — 10 October 2026

The final source-pack rule is `bm25_diverse_anchors_fair_supported_neighbors_callsite_v4`; the model-edge rule is `supported_endpoints_and_original_callsite_visible_v1`. Source windows prioritize clean callsite lines, and graph metadata is filtered before interventions and structural qualification. This is a bounded development revision made before any model outcomes. Visible callsites enable direct source inspection but do not guarantee all needed binding or definition context is visible. The checker still consults the full snapshot; its access advantage must remain explicit in scientific interpretation.

| Current artifact | SHA-256 |
|---|---|
| Replacement release wheel `dist/graphtrust_swe-0.1.0-py3-none-any.whl` | `c492f95f679792c81e9063d73825179dcab686e5bfadb1a63f05b8e256c77b71` |
| Source and wheel Python implementation | `bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae` |
| Current protocol, canonical JSON digest | `f12e3788aff29530923d70b2af732ed8d63a43125aa171168579bc6bd5166dff` |
| Current protocol file bytes | `daa0d8f4402eacdd46a8fe56527d95c41fa63bc04c393b5210a0a0cef3a386e9` |

Fresh post-revision checks passed: release wheel build; **127 full-suite tests**; both five-code-cell notebooks in order with inference disabled; a fresh twelve-attempt synthetic demo; and an isolated installed-wheel CLI demo from a separate working directory. Python implementation hashes remained stable before and after checking. Package source was not edited by this reviewer. Wheel inventory inspection again found no evaluator/corpus/gold/model-weight assets and confirmed byte-identical protocol resources plus preserved license/notice.

Evidence is in `runs/reproduction-review/final/`. The full test log digest is `2653dbd3c670c37892ddd919ddcade3416db215e3fa3700d752cca8353e90d3a`; the notebook execution log digest is `3e22269c29bf57989d2cff768f924d83130089cf1ee7551e35954d14f7717b04`. Notebook hashes in the initial table remain unchanged. During final bundle inspection, a one-line bundler change fixed Windows newline translation so the written script's actual byte hash equals its sidecar hash. The final bundler hash is `31ae6bd63d84a90b7c80bf17b47748f9027dd97c25f1eeaecf2470427b3233ab`; package code was unchanged. Current full inventories and other evidence hashes are in `final/wheel-inventory.json` and `final/verification-metadata.json`.

GGUF checkpoint selection and source-build preparation were independently reviewed through read-only official APIs and primary documentation, recorded in `MODEL_LOCK.json` and `GGUF_REPLICATION.md`. Their build and runtime paths remain untested. The official version-2 QAT Q4_0 filenames and byte counts match API snapshots; cryptographic model hashes remain unknown until actual attachment files are inspected. The selected Python binding and vendored llama.cpp commits contain Gemma 4 architecture support and template keyword forwarding. This source inspection does not replace a development runtime smoke check.

## Final pilot v8 bundle inspection

Strict bundling and independent archive inspection passed for `runs/kaggle-pilot-v8/graphtrust_pilot.py`. The written file is **175,063 bytes** and its actual SHA-256 matches the sidecar. Both the outer supervisor and notebook worker compile without executing inference.

| Identity | SHA-256 |
|---|---|
| Script file bytes | `5588da9da11ad42ba8d8a95b8427fee3959e4fee890dc359a1b1a6b593ecf3a3` |
| Embedded archive bytes | `3114904539bc1b4449d13f5a7dd6e2ce137bda35c7573ad739c6666bd0e8a334` |
| Notebook worker code | `82ce8e92577542d7ee66843ddb5dc4cf4c140de81e00eedf6c4785c8920a5caa` |
| Contexts, canonical JSON rows | `65ba6eabb2a8c3f66fdbb8f95ca6af7282b336dd70ff5d64725a0abd5bbf58d6` |
| Tokenizer identity | `6ea0b23474e17e998bf2d0b4b2e593c93b91526bc478818a4f9b74d64c68a4a4` |

The archive contains exactly `package/graphtrust_swe-0.1.0-py3-none-any.whl`, `contexts/contexts.jsonl`, `contexts/manifest.json`, and `protocol.json`. Every embedded asset's byte count and SHA-256 matches metadata. Wheel code, protocol and context identities match the final implementation. No evaluator data, reference patches/tests or model weights are embedded; known-false relationship labels are evaluator metadata outside prompt text.

CLI validation confirms ten issues, sixty contexts and exact tokenizer accounting. The pilot includes three sqlfluff issues, three pydicom issues, two astroid issues and two pvlib issues. Prompt sizes range from 2,749 to 3,928 tokens. All 73 clean relationships and 20 false relationships have their recorded original callsites visible. This visibility is a CPU structural diagnostic, not a measured model result or proof of complete binding context. Gold labels did not determine source packs or case selection.

The supervisor limits attempts to 120 and wall time to 10,800 seconds; model weights must be separately attached. Inspection evidence is preserved in `final/v8-bundle-inspection.json`, `final/v8-bundler.log`, and `final/v8-cli-validation.log`. No local real inference or remote GPU launch occurred during this review. Protocol freeze and any efficacy claim remain contingent on complete real development-pilot records passing the package gate.

## Actual Kaggle tokenizer preflight failure and diagnostic update

The v8 bundle was subsequently run by the parent task as private Kaggle committed version 2. Preserved outputs under `runs/kaggle-pilot-v8/version-2-output/` show two Tesla T4 GPUs, successful weight loading, then an assertion that the context tokenizer identity differed from the attached model's tokenizer. The supervisor recorded exit code 1 and `not_frozen`; no localization records or attempt journal were present. Its approximately 193.5 seconds of total startup/preflight time is not localization latency or benchmark throughput. This failed preflight remains part of the experiment history and must not be reported as a completed pilot or a localization failure rate.

Independent byte-hash comparison confirms that the original pinned HF tokenizer and the actual Kaggle-version tokenizer share `tokenizer.json`, `config.json`, and `processor_config.json`, while `tokenizer_config.json` and `chat_template.jinja` differ. Thus identical vocabulary/config files and model names were insufficient to establish identical tokenizer/chat framing. Evidence is `runs/reproduction-review/tokenizer-guard/tokenizer-file-comparison.json`. The original HF lock is historical for v8 preparation; v9 must use the actual Kaggle assets and a matching regenerated manifest. No package source or protocol was changed for this tokenizer correction.

The notebook was updated to save `model-manifest-used.json` immediately after checkpoint inspection and `backend-identity.json` immediately after backend initialization, before the tokenizer guard. The late duplicate model-manifest write was removed. Independent compilation and AST ordering checks confirm one write per diagnostic: checkpoint inspection at combined worker line 64, model manifest at 65, backend initialization at 99, backend identity at 100, tokenizer guard at 106, and localization call at 115. If initialization reaches the tokenizer guard, these diagnostic files are already written. Failures within checkpoint inspection or backend initialization can still precede the respective completed identity object.

With `GRAPHTRUST_RUN_REAL` **unset**, the updated notebook's five code cells execute successfully from a fresh working directory. A subprocess trap observed zero command calls; no Torch import or file creation occurred. The real branch remains disabled by default. This local default-path check does not demonstrate a successful GPU rerun.

| Updated identity | SHA-256 |
|---|---|
| Kaggle notebook bytes | `cce99dfa28f02f9667cac544bd4fe86da6be21b9f55667c362b00d6ed5db22ef` |
| Updated notebook worker code | `fed08bf935165456ab0c20d1f796396adf47726f78e453aab91e8c3431e631cf` |
| Default execution JSON evidence | `44192c8577d7c1b020c61910bfabdceb28f7f6ed37d595db928bdacca935905f` |
| Preserved remote runtime log | `733b5c217efdf40ea2fb5967dfc7d8ee6107646f7c4c22c2fe3ec604d810357a` |

The unchanged implementation remains `bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`. Separate fresh full-suite evidence under `runs/reproduction-review/cpu-diagnostics/` records **131 passing tests** under the same stable implementation; its full-test log digest is `fd6942c10e7d4ecf7c7bb86ed47906d76430f776eb2283cbc24d4674c93f1d41`. This notebook review did not repeat the full suite for a diagnostic-order change.

Local review evidence and hashes are saved under `runs/reproduction-review/tokenizer-guard/`. The v8 script, archive and outputs have been preserved without overwrite. A strict matching v9 bundle and an accepted real pilot remain pending.

## Independent v9 bundle review

The replacement `runs/kaggle-pilot-v9/graphtrust_pilot.py` passed independent review against the active Kaggle tokenizer lock, unchanged wheel/protocol, and updated notebook. The outer script and worker compile without execution. The actual written script bytes match its sidecar; archive constants and every embedded asset hash/byte count match.

| V9 identity | SHA-256 |
|---|---|
| Script file, 175,175 bytes | `998af06694c8a8b59d7b0a1b41fd1df2629bcd4ce1d6a2eff4a642a8e322f227` |
| Embedded archive | `df612bca32d8ec62ac16e49dca4be00a56ecd3da0bb9458bf05b0180b8bbf1c4` |
| Active Kaggle tokenizer identity | `ca7db376622726274dd8d16d6fa0a7fe86001167152052945d235c3b8b13bbf6` |

The archive contains exactly the release wheel, contexts JSONL, context manifest, and protocol. It contains no evaluator gold or model weights. The wheel remains `c492f95f679792c81e9063d73825179dcab686e5bfadb1a63f05b8e256c77b71`, implementation `bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`, and protocol `f12e3788aff29530923d70b2af732ed8d63a43125aa171168579bc6bd5166dff`.

Independent offline loading of the active tokenizer assets reproduced the locked identity and exactly recounted all sixty prompt token totals, with maximum 3,928. All five local tokenizer asset hashes and byte counts match `TOKENIZER_LOCK.json`. This verifies the tokenizer-only CPU path; the attached model's `AutoProcessor` identity and exact counts must still pass runtime guards before any attempt.

V9 context JSONL bytes are identical to v8, including prompts, source packs, ordering, token totals and interventions. Case IDs/order and selection digest `3bc5419a3516a77d1a43ce9002706f76bf82dbe6e9bee24f50d6f279c7509396` are unchanged. The only differing manifest field is `tokenizer_identity`. Thus this correction did not revise cases or content using model outcomes; the failed v8 run produced no localization outcomes. Both versions preserve six conditions per issue with identical source bytes within each issue.

The embedded worker is exactly the current diagnostic notebook code: notebook digest `cce99dfa28f02f9667cac544bd4fe86da6be21b9f55667c362b00d6ed5db22ef`, worker digest `fed08bf935165456ab0c20d1f796396adf47726f78e453aab91e8c3431e631cf`. Model manifest/backend identity writes at lines 65/100 precede the tokenizer guard at 106 and localization at 115. Attempt and runtime caps remain 120 calls and 10,800 seconds.

## Implementation-preview packaging audit

A targeted `MANIFEST.in` now includes public configuration, scripts, notebooks,
docs, synthetic fixtures, and all repository tests in the source distribution.
Private handoffs, data, runs, model assets, virtual environments, build outputs,
and logs are excluded. This corrects the earlier generated source-file manifest,
which omitted the tools and configs required by several repository tests.
No executable package or protocol change was made for this packaging audit.

The separately built source archive was inspected member by member and installed
without network access or runtime dependencies to a fresh target outside this
checkout. Running the installed package with site packages disabled produced six
contexts and twelve synthetic attempts, retained identical source, and passed
manifest validation. The public scripts' help commands worked from the extracted
tree. Both notebooks' five code cells compiled; their saved outputs and execution
counts are empty. This is software reproduction evidence, not Gemma inference.

The public candidate-file scan found no matches for the inspected credential,
signed-URL, or absolute-machine-path patterns. The identifier-only dataset
manifest was verified against all 323 regenerated public cases without opening
evaluator storage, and all inspected relative Markdown links resolve locally.
These checks are bounded to the inspected files; changes require a new inventory.

The original local dependency inventory is retained privately. Its public copy
is labeled as observed provenance and normalizes the editable path to `-e .`.
The public reproduction instructions now pin the dataset revision and use shipped
validation commands instead of a private helper. The full latest integration log
records 154 tests passing in 25.227 seconds; its SHA-256 is
`67c45f8dcd34a447114a3feb8cd341c019d4ba3bc5477ffa3507ed54c53e44c7`.
The packaging audit did not rerun that broad suite.

Implementation `bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`,
canonical protocol `f12e3788aff29530923d70b2af732ed8d63a43125aa171168579bc6bd5166dff`,
and current wheel `c492f95f679792c81e9063d73825179dcab686e5bfadb1a63f05b8e256c77b71`
remain unchanged. Actual source-archive hashes, byte inventories, build and
offline-install logs, and scan results are retained in `runs/release-audit/`.
The first no-isolation build attempt found setuptools absent from the local venv;
the isolated build succeeded with setuptools 84.0.0 without modifying that venv.

[RELEASE_READINESS.md](RELEASE_READINESS.md) and [release notes](../RELEASE_NOTES.md)
identify the public staging scope and outstanding publication/scientific work.
No public release, GPU launch, accepted pilot, or competition submission is
established by this audit.

Repeatable review code and outputs are preserved under `runs/reproduction-review/v9-bundle/` (`review_checks.py`, `inspection.json`, `inspection.log`). V8 script bytes were checked before and after review and remain unchanged. No source/config edit or real inference was performed by this reviewer. A successful real pilot and scientific freeze remain pending.
