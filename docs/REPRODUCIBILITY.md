# Reproduce GraphTrust-SWE

The CPU demo is a runnable software artifact. Real Gemma experiments require a
separate, measured pilot and protocol freeze. A synthetic mock result never
qualifies as an empirical result or a successful pilot.

## Environment and offline smoke test

Run these commands from the checkout root with Python 3.11 or later:

```text
python -m pip install -e .
python -m unittest discover -s tests -v
python -m graphtrust demo --out runs/demo
python -m graphtrust validate --directory runs/demo
```

`requirements-local.lock.txt` is a normalized inventory of the observed local
CPU/tokenizer environment, with the editable checkout recorded as `-e .`.
It is not a hashed dependency lock or a portable CUDA environment recipe.
Use the package extras below for installation; the Kaggle harness separately
records its actual resolved runtime environment.

The demo uses only bundled synthetic source and the Python standard library.
`runs/demo/report/` contains scored CSV rows, a machine-readable summary, and a
Markdown report. Install the plotting extra to generate the three diagnostic
figures from those rows:

```text
python -m pip install -e ".[plots]"
python -m graphtrust demo --out runs/demo
```

Those figures carry a synthetic watermark. The demo checks six conditions and
source invariance; it does not verify Gemma throughput or localization quality.
Open `notebooks/graphtrust_demo.ipynb` for a top-to-bottom tutorial and a coverage
exercise. It has no hidden state and does not download models or repositories.

## Acquire immutable corpus inputs and prepare CPU artifacts

```text
python -m pip install -e ".[corpus]"
python -m graphtrust fetch --out data/swebench-lite --revision 6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2
python -m graphtrust prepare --data data/swebench-lite --out runs/cpu --split all --workers 3
```

`fetch` resolves the Hugging Face dataset to an immutable commit and records file
hashes in `dataset-lock.json`. Use `--revision` with that recorded commit in an
independent reproduction. Re-running an existing acquisition verifies hashes;
it does not silently refresh the dataset. The prepared source snapshots use each
case's pinned base commit. Preparation records failures, qualification, hashes,
and intervention diagnostics and can be resumed without selecting on performance.

Public case data contains issue text, repository, commit, and split identifiers.
`data/swebench-lite/evaluator/gold.jsonl` contains reference patches, verification
test patches, and reference-edit file labels. Keep that directory on the evaluator
machine. Do not place it in an inference attachment, prompt, or model-facing pack.
Reference coverage is measured after pack construction and never controls case
selection.

After acquisition, verify the released identifier-only dataset manifest without
opening evaluator storage. Run this Python snippet from the checkout root:

```python
import hashlib
from graphtrust.io import digest, read_json, read_jsonl

manifest = read_json("docs/DATASET_MANIFEST.json")
cases = sorted(read_jsonl("data/swebench-lite/cases.jsonl"), key=lambda row: row["case_id"])
rows = []
for case in cases:
    row = {key: case[key] for key in ("case_id", "commit", "dataset_revision", "repo", "split")}
    row["issue_sha256"] = hashlib.sha256(case["issue_text"].encode("utf-8")).hexdigest()
    row["public_case_sha256"] = digest(case)
    rows.append(row)
assert rows == manifest["cases"]
assert digest(rows) == manifest["case_identity_sha256"]
assert len(rows) == manifest["case_count"]
assert manifest["contains_gold"] is False
assert manifest["contains_issue_text"] is False
print("Dataset identifiers and hashes match the released manifest.")
```

Development and holdout selection are deterministic under the versioned protocol.
Record the observed split counts, repository allocations, eligibility reasons,
and shortfalls. Targets of 20 development issues, 300 test issues, and 60 model
holdout issues are not permission to fill gaps using favorable model outcomes.
When qualification falls short, disclose it and narrow the claims.

## Build exact-token contexts and run the pilot

The local Gemma checkpoint must be an immutable, accepted model artifact. Install
the inference extra in a suitable environment and set `GRAPHTRUST_MODEL_DIR` to
its actual directory. In PowerShell, read the existing variable rather than
inventing a model mount path:

```powershell
python -m pip install -e ".[gemma]"
python -m graphtrust contexts --data data/swebench-lite --prepared runs/cpu --out runs/pilot --stage pilot --tokenizer $env:GRAPHTRUST_MODEL_DIR --pack-budget 2400 --input-budget 4000
python -m graphtrust validate --directory runs/pilot
python -m graphtrust infer --contexts runs/pilot/contexts.jsonl --out runs/pilot/records.jsonl --backend transformers --model $env:GRAPHTRUST_MODEL_DIR --seeds 17,42 --max-calls 120
```

The context builder must use the same processor, chat template, thinking setting,
and tokenization rules as generation. The total input target includes framing,
issue text, instructions, shared source, and relationship metadata. CPU
`byte_upper_bound` contexts are construction artifacts; a scientific freeze
requires actual `tokenizer` accounting. The common pack is reused without arm-only
source trimming. If an arm overflows, uniformly reduce all packs and version the
pilot configuration.

The tokenizer source must match the actual attached checkpoint version. The
first Kaggle v8 job loaded the official E2B version-1 weights but rejected the
Hugging Face preflight tokenizer before any localization call. The pinned HF
revision and Kaggle `google/gemma-4/Transformers/gemma-4-e2b-it/1` share the same
`tokenizer.json`, but their `tokenizer_config.json` and `chat_template.jinja`
differ. The existing fingerprint guard correctly rejects that mismatch. Do not
substitute HF's template merely because plain-text chat samples happen to
render identically.

`docs/TOKENIZER_LOCK.json` preserves the prior HF lock and separately records
the actual Kaggle version-1 source, five asset byte hashes, and verified runtime
identity. Obtain the named tokenizer/config/template files from that exact
official Kaggle model version, retain them privately under its original terms,
and compare their bytes with the lock. A tokenizer-only local directory needs
no model weights for context construction. After acquiring those files at the
locked relative directory, the public preflight commands are:

```text
python -m graphtrust contexts --stage pilot --data data/swebench-lite --prepared runs/cpu --out runs/pilot-tokenized-kaggle --tokenizer models/e2b-kaggle-tokenizer
python -m graphtrust validate --directory runs/pilot-tokenized-kaggle
```

Use this output directory wherever the following examples use `runs/pilot`.
The packaged validation command checks the artifact manifest and source invariance;
the inference backend independently recounts every rendered prompt before an
attempt. Historical read-only audits under ignored `runs/` directories document
development checks and are not required release tools.
Transformers 5.19.0 with tokenizers 0.23.1 and 0.23.3 produced the same active
Kaggle tokenizer fingerprint in local checks. All 60 v8 plain-text prompts had
identical rendered chats and token IDs under the two source templates, but this
does not validate AutoProcessor on the GPU or make their whole templates
interchangeable. The actual inference environment must save its backend identity
and reject any mismatch or runtime token-count discrepancy before inference.

For Kaggle execution, use `notebooks/kaggle_gemma_pilot.ipynb`. Attach only:

- The selected GraphTrust-SWE wheel and checksum, protocol JSON, and prebuilt
  exact-tokenizer contexts/manifest.
- The Google Gemma 4 E2B checkpoint. The notebook fingerprints actual weight,
  configuration, tokenizer, and template bytes at runtime; an external file-hash
  manifest can additionally identify the original immutable revision.

The notebook lists explicit environment variables for actual attachment paths.
Its default run skips model generation; `GRAPHTRUST_RUN_REAL=1` enables the
prepared 120-call pilot. The online bootstrap pins Transformers 5.19.0 and Jinja2
3.1.6, retains Kaggle's CUDA-compatible torch, and installs Accelerate 1.10.1 only
when absent. It saves the full resolved package environment before inference.
It does not create a GPU session, publish a dataset, or submit a Writeup, and
requires a user-selected free T4 environment. To run fully offline, additionally
attach compatible wheels and a complete pinned dependency lock with SHA-256
hashes, then set `GRAPHTRUST_BOOTSTRAP=offline`.
The official [Gemma inference documentation](https://ai.google.dev/gemma/docs/capabilities/text/basic)
supports the intended model path; local smoke tests cannot establish GPU fit.

For a private script run instead of an interactive notebook, bundle the same
validated inputs without uploading an evaluator dataset:

```text
python scripts/bundle_kaggle_pilot.py --wheel dist/graphtrust_swe-0.2.0-py3-none-any.whl --contexts runs/pilot/contexts.jsonl --manifest runs/pilot/manifest.json --protocol configs/protocol.json --out runs/kaggle-pilot/graphtrust_pilot.py
```

The bundler generates and compiles the script locally; it does not launch a GPU
session. Its archive contains only the wheel, contexts, context manifest, and
protocol. Attach the official E2B checkpoint separately using Kaggle's model
source field. Runtime discovers a unique E2B attachment or accepts an explicit
`--model-dir` supplied when bundling. The script supervises its notebook worker
for at most three hours, caps calls at 120, preserves interrupted attempts, and
writes runtime status, environment/checkpoint hashes, records, and freeze
diagnostics. A stopped or failed pilot remains incomplete and cannot be described
as a successful freeze.

Inference produces one terminal JSONL record per attempted logical call, including
errors, malformed/invalid outputs, timeouts, and interruptions. Preserve the
companion attempt journal. Recorded failures are terminal and survive resume;
configuration changes are new experiments. Write from one process per log.
Do not selectively retry difficult cases to improve a success rate. Preserve a
truncated log for explicit recovery rather than deleting unexplained failures.

The measured timeout behavior is recorded in each result. An
`elapsed_after_return` classification does not forcibly interrupt model generation;
report this limit when interpreting the quota budget. Archive the checkpoint
hashes, dependency lock, actual GPU, runtime versions, chat-template hash, dtype,
device map, sampling temperature, token caps, and seeds with every real experiment.

## Pilot freeze, holdout, and replication

After downloading the real pilot log to the evaluator machine:

```text
python -m graphtrust report --records runs/pilot/records.jsonl --contexts runs/pilot/contexts.jsonl --gold data/swebench-lite/evaluator/gold.jsonl --out runs/pilot/report
python -m graphtrust freeze --pilot runs/pilot --out runs/protocol-frozen.json
```

Freeze requires complete real records and exact tokenizer source packs, plus the
pilot acceptance gates. A mock run cannot satisfy it. If memory or timeouts affect
at least two development issues in a condition, uniformly reduce budgets and rerun
the versioned pilot. Require at least 95% contract-parseable outputs completed
within the elapsed budget, and review graph
evidence use. An uninformative presentation is corrected on development cases;
the model is still permitted to rely exclusively on source or abstain.

The prospective [response protocol v2](RESPONSE_PROTOCOL_V2.md) uses record schema
`2.0` and contract `files_citations_v2`. Rebuild contexts and record all 120 fresh
attempts with the final implementation hash. Preserve old v1/v9/v10 artifacts;
never relabel, reparse, combine, or reuse them as v2 pilot evidence. V1 reports
retain their original scoring behavior in a separate configuration.

Once frozen, generate the holdout under the accepted protocol. For a budget
revision, first create a new versioned protocol JSON with the accepted values and
pass `--protocol` before the subcommand for every stage, including `freeze`; an
override used only for context construction cannot satisfy the protocol hash
gate. Compare manifests to the frozen protocol before starting inference:

```powershell
python -m graphtrust contexts --data data/swebench-lite --prepared runs/cpu --out runs/holdout --stage holdout --tokenizer $env:GRAPHTRUST_MODEL_DIR
python -m graphtrust validate --directory runs/holdout
python -m graphtrust infer --contexts runs/holdout/contexts.jsonl --out runs/holdout/records.jsonl --backend transformers --model $env:GRAPHTRUST_MODEL_DIR --seeds 17,42 --max-calls 720
python -m graphtrust report --records runs/holdout/records.jsonl --contexts runs/holdout/contexts.jsonl --gold data/swebench-lite/evaluator/gold.jsonl --out runs/holdout/report
```

The primary target is 720 logical calls over 60 issues. Count actual qualified
issues and scheduled calls in the manifests; do not label a partial run complete.
The optional balanced replication targets 30 issues with one seed and all six
conditions, or 180 logical calls. Use `--stage replication`, a separately pinned
E4B GGUF artifact, `--backend gguf`, and `--seeds 17`. Its template and exact token
accounting must match its backend; do not reuse Transformers counts for GGUF
without validation. Generate and report it as a separate runtime/model study.
The official QAT Q4_0 version-2 checkpoints and source-build revisions are
preregistered in [MODEL_LOCK.json](MODEL_LOCK.json); follow
[GGUF_REPLICATION.md](GGUF_REPLICATION.md) for verified metadata, build preparation,
and `--tokenizer-backend gguf` commands. GGUF build/runtime checks remain unexecuted.

Reserve the planned free GPU budget for the complete primary contrast. Drop
optional repair first and then secondary replication if measured throughput
requires it. Repair demonstrations require verified local environments and a
separate protocol because graph navigation changes source exposure.

## Scoring and uncertainty

`evaluate_runs(records, gold, context_metadata)` returns one scored row per
attempt. It validates context hashes, scores file recall@5 and hit@5 separately,
counts unique cited false relationships from evaluator-only metadata, and retains
abstention, invalid outputs, failures, timing, and tokens. Missing/empty gold is
explicit and excluded from localization denominators. The candidate coverage
ceiling accounts for both visible reference files and the five-file output cap.

`summarize(scored)` keeps models and backend/generation configurations separate.
Its default intervals use 2,000 deterministic hierarchical repository/issue
bootstrap samples with seed 20261010. Sampling repeats are averaged within each
issue; paired differences require the same seed sets in both arms. Failure rows
remain zero localization outcomes. If an externally assembled log includes more
than one attempt for the same logical run, all attempts remain in the CSV and
only the last attempt enters the outcome summary; the official runner does not
selectively retry terminal failures.

Report the actual issue and repository denominator for every contrast.
The target 720 calls still represents 60 independent issues. Intervals with few
repository clusters are exploratory; a single-repository generalization interval
is unavailable. Per-repository means are descriptive strata. File edits are
localization proxies rather than definitive root-cause or repair labels.

`write_report(scored, outdir)` writes `results.csv`, `summary.json`, and `REPORT.md`.
With matplotlib installed it generates three figure families: missing/false
relationship effects, source-checking recall and inference latency, and repository
strata. Every plotted value comes from supplied records; empty runs produce no
empirical figures. Checker preprocessing time must be measured separately before
claiming an end-to-end verification cost.

Before publishing empirical results, use the explicit local `graphtrust export`
command described in [PUBLIC_RESULTS_EXPORT.md](PUBLIC_RESULTS_EXPORT.md). It
validates complete current v2 records/journals and accepted identities, retains
failures, redacts unsafe ranked slots with original hashes, and regenerates public
aggregates and optional figures. Raw prompts, source, gold labels, and error text
remain private. The evaluator `results.csv` contributes only joined scalar metrics.

## Licensing and release audit

Original GraphTrust-SWE code and synthetic fixtures are Apache 2.0. Upstream
dataset, repository source, model terms, and third-party dependency licenses remain
applicable. Do not describe derived source packs as relicensed original code.
Retain upstream license/copyright files in source caches and record their locations.
The public release should prefer regeneration identifiers, manifests, original
code, and sanitized evaluation logs over repackaged source or restricted assets.
Paths under `runs/`, `data/`, and `models/` in review documents identify private
development evidence or outputs to regenerate. They are not attached public
assets or prerequisites for the offline demo. Consult [RELEASE_READINESS.md](RELEASE_READINESS.md)
for the implementation-release inventory and remaining scientific release work.

Before tagging or publishing, independently verify:

- A fresh install reproduces synthetic hashes and the demo without network access.
- Corpus and context hashes match the frozen manifests; gold never appears in a
  model-facing prompt or attachment.
- All attempted calls and failure statuses are preserved, paired denominators are
  correct, and each paper table/figure is traceable to evaluation records.
- The public artifact contains the code license, upstream notices, resource card,
  protocol manifest, dependency/model identities, exclusions, and release tag.
- The paper clearly distinguishes empirical results, synthetic checks, planned
  experiments, and omitted optional work.
- Public links work and the Kaggle Writeup is actually submitted. A saved draft,
  notebook execution, or repository tag is not evidence of submission.

Consult the live [competition submission requirements](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/overview/submission-requirements)
before publishing. Preserve implementation handoffs at protocol freeze and
experiment completion, including evidence paths and unresolved limitations.
