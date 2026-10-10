# Public empirical results export

`graphtrust export` creates a new local directory from a complete current response
protocol v2 cohort. It does not publish, freeze, run a model, or convert historical
v1 attempts. The underlying private records remain authoritative. A software test
fixture cannot establish that a real model run or an accepted pilot occurred.

Use the exporter after independent review of the actual pilot, accepted freeze,
runtime identity, complete attempt journals, and evaluator results. A prospective
implementation or extractor change requires fresh preparation and a fresh full
real pilot before a new freeze. This command rejects a mismatched implementation.

```powershell
graphtrust report --records runs/primary/records.jsonl `
  --contexts runs/holdout/contexts.jsonl --gold data/evaluator/gold.json `
  --out runs/primary/report

graphtrust export --records runs/primary/records.jsonl `
  --contexts runs/holdout/contexts.jsonl --manifest runs/holdout/manifest.json `
  --freeze runs/protocol-freeze.json --scored runs/primary/report/results.csv `
  --figures --out runs/public-primary-v1
```

The default journal is `<records>.attempts.jsonl`; specify `--journal` for another
location. The output directory must not exist. `--figures` requires the `plots`
extra and an evaluator `results.csv`. Figures are regenerated from allowlisted
aggregates, with model names replaced by configuration hash aliases. Arbitrary
report files and images are never copied. Every exported file is inventoried with
its physical SHA-256 in the public manifest. Export is atomic after validation;
an existing export is never overwritten.

For replication, also provide `--primary-manifest runs/holdout/manifest.json` and
`--runtime-lock <accepted-runtime.json>`. The primary manifest must describe its
complete declared cohort. Replication retains the fixed first five or fewer
primary IDs per repository, without replacement, and preserves structural
shortfalls. The separate GGUF runtime must match the pinned, tested development
lock described in [KAGGLE_EXPERIMENT_BATCHES.md](KAGGLE_EXPERIMENT_BATCHES.md).

## Allowlisted public schema

The public schema is `graphtrust_public_results_v1`, distinct from private model
record schema `2.0`. Public rows cannot be supplied to `evaluate_runs` as raw
model outputs. Never relabel an old failed pilot with this schema or with v2.

| File | Contents |
|---|---|
| `records.jsonl` | One row for every terminal attempt, identity hashes, seed, status, token/latency diagnostics, contract/semantic flags, abstention, literal ranked reference slots, scalar metrics, and original record hash |
| `attempts.jsonl` | One row for every original start, run/case/condition/seed identity, and original start hash |
| `contexts.jsonl` | Case/repository/condition metadata, source/context/snapshot hashes, token count, visible candidate paths and source/relationship IDs |
| `freeze.json` | Numeric pilot gate diagnostics and freeze/protocol/implementation/evidence hashes; no raw protocol or model path |
| `summary.json` | Regenerated issue-level aggregates and paired intervals, including repository strata and failure denominators |
| `manifest.json` | Cohort/seed/shortfall identity, model kind/checkpoint/tokenizer hashes, original input file hashes, exclusion count/hash, export inventory, and regeneration note |
| Optional `figure_*.png` | Three figure families regenerated from the exported aggregate |

The export omits raw prompts, issue text, source packs, source spans, gold/reference
file labels, patches, evaluator tests, false-edge sidecars, raw response text,
extra response fields, error messages, backend paths, credential values, and
signed URLs. Unknown fields in context, cohort, freeze, primary-manifest, or
runtime-lock inputs refuse the entire export. Unsafe visible metadata also refuses
the export. Exclusion details and original backend dictionaries are represented
by hashes, without copying their strings.

Files and citations preserve all literal output slots and their original ranks.
A validated visible reference is retained. An invalid or unsafe slot becomes
`reference: null`, `redacted: true`, and `original_value_sha256`. No slot is
removed, repaired, or filled from a later rank. Duplicate valid references remain
duplicates. Extra-field names/values are omitted, with their count retained. Parse
errors, invalid predictions, timeouts, execution errors, and interruptions remain
in the denominator. Late parseable outputs remain timeout outcomes; observed
contract diagnostics and within-budget contract diagnostics remain separate.
Citation errors do not erase otherwise valid ranked-file localization credit.

`original_record_sha256` and `original_start_sha256` use the named rule
`sorted_compact_ascii_json_v2`: sorted compact JSON, ASCII escaping, finite
numbers only, then SHA-256 over UTF-8 bytes. This safely preserves hashes for
rejected raw text containing lone surrogates. Private context, protocol, and run-ID
hashes retain their existing UTF-8 canonicalization rules. Public-file hashes refer
to the exported bytes, not to the private original record serialization.
`model_configuration_sha256` hashes the full backend, generation settings, and
response-contract version with the evaluator's ASCII canonical rule;
`backend_sha256` separately identifies the backend dictionary used by the freeze.

## Scoring and traceability

Without `--scored`, localization metrics remain null; diagnostics are calculated
from the validated records and private context metadata. With `--scored`, the
complete evaluator CSV is joined by run ID and the original canonical record
hash. Only numeric file recall@5, hit@5, and coverage ceiling are imported. Missing
gold remains null. Failures and abstentions retain zero localization credit when
labels exist. Reference filenames and arbitrary CSV strings are never copied.
Gold availability and coverage ceiling must be constant across each issue's arms
and seeds; inconsistent evaluator joins refuse the entire export.
The CSV file hash records the exact evaluator input used; the exporter cannot
independently establish the correctness of labels that it never receives.

Private false-edge sidecars calculate aggregate cited-false-relationship counts;
the public context does not reveal those labels. Publish the identifier-only
dataset manifest and model/dependency lock alongside this directory. Independent
reviewers regenerate source, contexts, interventions, and evaluator-only gold from
the pinned dataset/repository recipes, then join their results to the original
record hashes. Keep the original private ledger and supporting acquisition/runtime
evidence. Hash lineage complements independent reproduction; it is not proof of
an unrecorded action or of model-output authenticity.

Intervals average repeated sampling seeds within each issue before comparisons.
An export of 720 primary calls still contains 60 independent issues, or the
explicitly disclosed smaller structural cohort. Do not combine development
outputs with holdout inference or treat the separate GGUF runtime as a clean
model-size comparison. Review public bytes and scientific claims before publishing
any positive or negative result.
