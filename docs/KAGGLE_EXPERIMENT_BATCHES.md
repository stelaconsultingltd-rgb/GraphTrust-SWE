# Frozen Kaggle experiment batches

`scripts/bundle_kaggle_experiment.py` builds a self-contained Python script; it never launches a session or submits to the competition. This tooling is separate from the development pilot and does not change `src/`, `configs/`, the release wheel, or the current pilot harness.

**Current launch blockers:** no accepted complete real pilot freeze or primary holdout contexts exist yet. The official Kaggle E2B tokenizer mismatch is being resolved on development cases. GGUF build, loading, memory fit and generation remain untested. Local unit tests are synthetic tooling checks and cannot satisfy any scientific acceptance gate. Do not invent accepted files to bypass these blockers.

The builder requires the full immutable context JSONL and its companion manifest, the exact protocol JSON, a genuine `freeze_protocol` output, the accepted actual backend identity saved by that pilot, and the release wheel matching the manifest's implementation hash. Primary inference must preserve the entire accepted backend identity, including checkpoint, active tokenizer/template, model mount path, Torch/Transformers versions, dtype, device map and GPU names. A mismatch stops before inference and requires an explicit development/runtime decision.

The nominal schedule is 60 issues across six repositories, six conditions and seeds 17/42 (720 primary attempts). A complete declared cohort below 60 is accepted when the current structural selection manifest discloses exact per-repository `requested: 10` and `available` deficits. The actual issue counts must match every declaration, with all arms and seeds present. No qualifying cases means no GPU launch. Bundle metadata records the nominal target, actual issues/attempts and declared deficits.

Replication preserves the current API's repository-grouped primary selection order and takes the first five cases, or every available case when fewer than five were selected, per repository. Its nominal target is 30 issues/six conditions/seed 17 (180 attempts); corresponding primary shortfalls reduce the actual fixed schedule. The builder also retains the replication manifest's qualification-population shortfalls, which the current context API measures against ten even though the selected subset is at most five. All six arms retain identical source hashes. Missing arms, inconsistent deficits, changed prompts, approximate token counts and evaluator-only fields block bundle generation. Keep the primary manifest for the replication builder; do not replace a case when a secondary tokenizer cannot materialize it.

## Resource reservations

Pass all limits explicitly. Each session has a hard supervisor deadline of at most 10,800 seconds, including dependency setup, checkpoint hashing/loading, token preflight and generation. The supervisor reserves ten seconds for stopping its process group and saving the attempt journal. The package's 90-second allowance remains an elapsed-after-return classification, not a separate hard GPU interruption per call.

Primary stage limits are at most 24 wall-clock hours and eight sessions; replication limits are at most six hours and two sessions. This leaves ten of the approved 40 hours for development and other overhead. A 120-new-call primary batch or 90-new-call replication batch is a cap, not a throughput promise. If the hard deadline cuts generation short, its started attempt becomes terminal `interrupted`; the next batch continues with the next unattempted arm.

The session ledger conservatively charges the entire requested session reservation even after an early exit or crash. Its limits never reclaim unused time automatically. `--free-quota-seconds` is the externally verified free quota allocation for this stage, carried unchanged across all resumes. T4 device names cannot verify Kaggle account billing mode, account-wide consumption or weekly reset: check the free quota dashboard and session settings before committing each run, and assign reservations across the approved weeks. Never launch a paid or L4 session. No platform credentials are read by this script.

Example **after** genuine freeze and exact holdout preparation, with placeholder artifact locations to replace:

```powershell
.venv/Scripts/python.exe -B scripts/bundle_kaggle_experiment.py `
  --wheel dist/graphtrust_swe-0.1.0-py3-none-any.whl `
  --contexts runs/holdout/contexts.jsonl --manifest runs/holdout/manifest.json `
  --protocol configs/protocol.json --freeze runs/protocol-frozen.json `
  --backend-identity runs/accepted-pilot/actual-backend.json `
  --session-seconds 10800 --stage-seconds 86400 --free-quota-seconds 86400 `
  --max-sessions 8 --batch-max-calls 120 --output runs/batches/primary-01.py
```

Inspect the generated `.manifest.json`, verify the script checksum, and use a private Kaggle notebook with the exact official model attachment and free T4 settings. The builder neither discovers nor substitutes weights: the actual mount path must match `accepted-backend.json`. The generated script uses the existing `run_contexts` API directly to preserve the accepted pilot's `model_name` as well as its backend identity; the CLI currently derives `model_name` from a model path.

## Durable resume and diagnostics

Download the entire `/kaggle/working/graphtrust-experiment` directory after every session, including all session subdirectories. Preserve it under a versioned local evidence path. To create the next bundle, pass the same immutable inputs and policy plus `--resume <downloaded-directory>` and a new `--output` filename. The embedded allowlist retains the exact bytes of all cumulative `records.jsonl`, `records.jsonl.attempts.jsonl` and `session-ledger.json`. Keep prior session logs/diagnostics on disk; they are not re-embedded.

Every terminal failure, timeout, invalid answer and interrupted start is retained. Schema-v2 ledgers pin exact byte lengths, SHA-256 hashes and row counts for both cumulative files before every reservation, and again after each finalized session. Builder, supervisor and worker resume paths verify every prior prefix. Finalized histories must remain exact; a crashed `reserved` session accepts only a valid append-only extension within its attempt cap. A later crash cannot make an earlier finalized failure disappear.

Resume also rejects duplicate/foreign IDs, changed generation/backend/context identities, missing original starts, truncated or unterminated JSONL, and unreserved extensions of finalized histories. A crashed session still consumes its full quota reservation. Recovery verifies the prefixes first, finalizes missing terminal records as `interrupted` without retry, and seals the recovered crash boundary before another reservation or completion check. Schema-v1 or otherwise unanchored ledgers are rejected: retain their original artifacts and obtain an explicit documented recovery from the preserved prior finalized logs. No automatic migration reconstructs missing evidence. Preserve and explicitly recover malformed partial lines before another batch; do not trim them silently. Retain the original damaged bytes and document any recovery separately.

The cumulative files use one writer, guarded by an exclusive lock. Before tokenizer or exact-count assertions, the worker saves `actual-backend.json` and `actual-checkpoint-manifest.json`. It saves the checkpoint manifest even before model construction, so a constructor failure still leaves hashes with hardware/environment and the worker log. The supervisor moves available diagnostics into immutable `session-NNN/` directories and saves status and a ledger on every exit. A setup failure creates empty cumulative record/journal files for a diagnosable subsequent resume. It spends a session reservation and makes no synthetic inference records.

## GGUF replication and an accepted primary fallback

Model weights and any compiled CUDA runtime wheel must be attached separately; they are excluded from the archive. The builder requires a separately accepted development runtime lock for every GGUF backend, including an entire-study E2B fallback accepted before primary freeze. It will reject the current untested `MODEL_LOCK.json` as an acceptance artifact.

The new runtime-lock contract is a JSON object with these fields, filled only from a real pinned build and development smoke:

| Field | Required value/evidence |
|---|---|
| `status`, `build_and_runtime_tested` | `development_runtime_accepted`, `true` |
| `backend_sha256` | Hash of the actual accepted GGUF backend identity |
| `llama_cpp_python_commit` | `1652066e0af45f2313b339670ef9555e8a54e545` |
| `vendored_llama_cpp_commit` | `0c1e57098bba43ac29e6e3b677cdceebdd22334f` |
| `llama_cpp_python_version`, `jinja2_version` | `0.3.36`, `3.1.6` |
| `cuda_cmake_args` | `-DGGML_CUDA=on` |
| `model_sha256` | Actual separately attached official text GGUF hash |
| `built_wheel_sha256`, `wheel_path` | Actual CUDA wheel hash and `/kaggle/input/...` attachment path |
| `development_records_sha256` | Genuine development smoke records hash |
| `build_log_sha256`, `environment_sha256` | Preserved actual build log and environment hashes |

Retain the underlying evidence, compiler/CMake/CUDA versions, source licenses and dependency environment described in [GGUF_REPLICATION.md](GGUF_REPLICATION.md). This file is an operational lock contract, not a new scientific freeze or proof that a development smoke happened. Primary Transformers identity must still match its genuine pilot freeze; replication is a separately reported runtime comparison. Rebuild exact contexts with the GGUF tokenizer; Transformers token counts cannot be reused.

For a later validated replication bundle, add `--primary-manifest runs/holdout/manifest.json --runtime-lock <accepted-runtime.json>`, provide the actual replication backend identity and context files, and use `--stage-seconds 21600 --free-quota-seconds 21600 --max-sessions 2 --batch-max-calls 90`. The generated worker installs only the exact separately attached hashed GGUF wheel, with no automatic source build or alternative checkpoint fallback during holdout execution. Kaggle runtime validation remains outstanding.

The archive member allowlist includes only the GraphTrust wheel, contexts/manifest, protocol/freeze/backend identities, optional primary/runtime manifests and optional cumulative history. Wheel inventory rejects evaluator folders, tests and weight/parquet binaries. No patches, evaluator tests, corpus download or model weights are bundled.

Local verification: `.venv/Scripts/python.exe -B -m unittest discover -s tests -p test_experiment_bundler.py -v`. Seventeen focused tests pass in `runs/tests-experiment-history-prefix-v2.log`. The specific finalized-failure → reserved crash → omitted failure regression failed against the old code, preserved in `runs/tests-experiment-history-loss-red.log`. The new tests also verify a legitimate crash extension, interruption recovery, prefix rewrite rejection and legacy-ledger rejection. This verifies the builder, strict gates, exact schedule, archive isolation, failure-preserving resume and quota reservations. It does not verify GPU throughput, dependency setup in Kaggle, a GGUF build or the actual runtime session supervisor.
