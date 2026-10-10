# GraphTrust-SWE

A controlled robustness resource for repository graph evidence: compare missing
relationships with false relationships while keeping the source pack identical.

The [implementation preview](https://github.com/stelaconsultingltd-rgb/GraphTrust-SWE/releases/tag/v0.1.0-alpha.1)
provides the Apache-2.0 software, offline fixtures, and reproduction tools.

**Research status:** implementation and synthetic verification are available.
Synthetic outputs are never evidence about Gemma. The primary model study is not
complete and the protocol must pass a real development pilot before it is frozen.
See [the protocol](configs/protocol.json), [research draft](docs/PAPER_DRAFT.md),
and [reproduction instructions](docs/REPRODUCIBILITY.md).
The [resource card](docs/RESOURCE_CARD.md) documents schemas, intended use,
selection, limitations, and artifact boundaries.

## Install and run without a model

Python 3.11+; the core package has no third-party runtime dependencies.

```bash
python -m pip install -e '.[corpus,plots,notebooks]'
python -m unittest discover -s tests -v
python -m graphtrust demo --out runs/demo
python -m graphtrust validate --directory runs/demo
```

The demo uses original synthetic modules and a deliberately synthetic mock. It
creates six matched contexts, failure-preserving run logs, scored JSON/CSV, and
three figures when matplotlib is installed. It works without downloading models,
SWE-bench, GitHub repositories, Docker images, or calling a hosted API.

## Acquire and prepare the real corpus

```bash
python -m graphtrust fetch --out data/swebench-lite --revision 6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2
python -m graphtrust prepare --split dev --workers 3
python -m graphtrust prepare --split test --workers 3
```

The loader fetches immutable Parquet files with checksums. Public case records
contain the issue and base commit. Reference patches, added tests, and gold
production-file labels and raw Parquet (which also contains labels) go only into
`data/swebench-lite/evaluator/`. Snapshot
archives are restricted to Python source and upstream notices, with no Git
history. CPU preparation is resumable and retains errors/exclusions.

The primary corpus has 300 test issues. The model subset targets ten each from
Django, SymPy, Matplotlib, scikit-learn, pytest, and Sphinx, disjoint from the four
development repositories. Selection uses a seeded hash after structural
qualification, never model performance or reference-edit coverage. Shortfalls
are disclosed; missing correct files are retained as misses.

## Pilot, freeze, and evaluate

Install `.[gemma]` on a supported GPU runtime, or `.[gguf]` for a supported
llama.cpp runtime. Prepare exact-tokenizer contexts with a pinned local E2B
checkpoint or tokenizer directory; the default byte counter is only a
conservative development aid and cannot satisfy the freeze gate.

```bash
python -m graphtrust contexts --stage pilot --tokenizer /path/to/pinned/E2B --out runs/pilot
python -m graphtrust infer --contexts runs/pilot/contexts.jsonl --out runs/pilot/records.jsonl --backend transformers --model /path/to/pinned/E2B --seeds 17,42 --max-calls 120
python -m graphtrust freeze --pilot runs/pilot --out runs/protocol-frozen.json
python -m graphtrust contexts --stage holdout --tokenizer /path/to/pinned/E2B --out runs/holdout
python -m graphtrust infer --contexts runs/holdout/contexts.jsonl --out runs/holdout/records.jsonl --backend transformers --model /path/to/pinned/E2B --seeds 17,42
python -m graphtrust report --records runs/holdout/records.jsonl --contexts runs/holdout/contexts.jsonl --gold data/swebench-lite/evaluator/gold.jsonl --out runs/holdout/report
python -m graphtrust contexts --stage replication --primary-manifest runs/holdout/manifest.json --tokenizer-backend gguf --tokenizer /path/to/pinned/E4B.gguf --out runs/replication
python -m graphtrust infer --contexts runs/replication/contexts.jsonl --out runs/replication/records.jsonl --backend gguf --model /path/to/pinned/E4B.gguf --seeds 17
```

The notebook in `notebooks/kaggle_gemma_pilot.ipynb` prepares this process for a
free Kaggle T4. Attach the wheel, prepared contexts or graphs, and official model
as inputs. Never upload evaluator-only labels into the agent's inputs.
`scripts/bundle_kaggle_pilot.py` packages a verified wheel and exact pilot contexts
into a private T4 script, capped at 120 calls and a three-hour session.

Model outputs must be JSON with `files` (up to five relative paths), `source_ids`,
`edge_ids`, and `abstain`. Source or graph citations are optional. The runner
records every attempt, timeout, malformed output and interruption, and resumes
only missing run keys. Changing model/runtime/generation configuration creates a
different experiment. In-process timeouts are measured after generation, not a
hard cancellation guarantee.

## Scientific boundaries

- Source-supported static relationships are partial lexical evidence, not full
  runtime call graphs. Dynamic and ambiguous bindings remain unknown.
- False-edge swaps preserve relation and endpoint kinds and reject supported,
  duplicate and unchanged relations. Achieved severity is recorded. Model
  omission controls match the actual number of rewired edges.
- Relationship selection is common across arms so shorter metadata does not
  admit unrelated extra edges. All prompts retain identical source bytes.
- Shared lexical anchors and supported neighbors define the fixed pack. The
  source-only arm is a shared-pack control, not an independent BM25 system.
- Reference edits are a localization proxy, not proof of root cause. Report
  reference-file recall@5 separately from any-file hit@5 and pack coverage.
- Sampling repeats are averaged within each issue. Models/configurations are
  separated and uncertainty resamples repositories then issues.
- Holdout outcomes never determine exclusions, hyperparameters or retry policy.
  A null result remains a valid resource result.

## License and release

Original package code and synthetic fixtures are Apache-2.0. Dataset/repository
content retains its own licenses; see `NOTICE` and `docs/DATASET_LOCK.json`.
Downloaded corpora, source archives, evaluator labels, model files and run logs
are ignored by Git. Release regeneration code, manifests and audited results;
do not redistribute gated Kaggle competition assets or claim rights over them.

The paper-track deadline is 13 November 2026 at 07:59 Australia/Perth. Internal
submission target: 11 November. A saved draft is not a submitted entry.
