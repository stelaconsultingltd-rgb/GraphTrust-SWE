# GraphTrust-SWE resource card

Version: 0.1.0 development. This resource has implemented CPU and synthetic
verification; empirical Gemma robustness results require the real pilot and
frozen holdout. It is intended for research into trust in repository relationship
metadata, not certification of agent safety or general coding ability.

## Question and experimental unit

Given an issue and fixed repository source, does adding omitted or contradicted
static relationships change file localization? The independent experimental
unit is an issue. Sampling seeds are repeated measurements within that issue.
The six arms are source only, clean, deleted, rewired, clean checked, and rewired
checked. Every arm uses the same source bytes and source order.

## Corpus and selection

Regenerate SWE-bench Lite at the immutable revision in DATASET_LOCK.json.
DATASET_MANIFEST.json records every case ID, repository, commit, split, and
public case/issue hash without including issue text or answers. There
are 300 test issues and 23 development issues. The configured development pool
contains 20 issues across sqlfluff, pydicom, astroid, and pvlib. The held-out model
target is ten eligible issues each from Django, SymPy, Matplotlib, scikit-learn,
pytest, and Sphinx. A seeded hash orders cases after structural qualification.
Qualification and retrieval have no access to reference patches or model scores.
Any repository shortfall remains visible in the selection manifest.

## Representations and interventions

Nodes identify modules, classes, and functions using relative paths and qualified
names. Nodes retain source line spans and text hashes. Supported call edges have
source/target node IDs, call-site path, line, expression, and snapshot provenance.
Unresolved dynamic bindings and parse failures are recorded. These relationships
are conservative lexical evidence, not a complete runtime call graph.

Deletion removes supported edges. Rewiring swaps compatible endpoints and rejects
unchanged, duplicate, self-loop, and replacement relationships supported anywhere
in the full source-derived graph, including call sites outside packed metadata.
Requested and achieved severities are both recorded; structural compatibility
can make the achieved count smaller. The model deletion control matches the
actual rewired count. CPU diagnostics use three corruption seeds at three
severities; the model study uses one fixed seed and nominal 30% corruption.

A shared pack uses lexical issue anchors and supported neighbors, independently
of reference edits. It aims to include ten candidate files when the common token
budget permits. Context manifests record actual files and exclusions. Correct
repair files absent from the pack remain misses, with a reported coverage ceiling.
Truncated callers first seek deterministic clean call-site lines. Before any
intervention, retain only supported relationships with selected endpoints and
an original call-site line physically visible in the shared pack. Apply the
minimum-edge and perturbability rules to that subset. This structural rule was
added during CPU-only development, before model outcomes. Source spans and
definition-line coverage remain exposure diagnostics; visible calls do not
establish that all binding evidence is visible. Source only is a shared-pack control; its pack
includes clean graph neighbors. The checker flags source contradictions and
leaves ambiguity unresolved using the full snapshot's source-derived graph, which
can exceed the model's truncated pack. It is an integrity baseline with lexical
fallback, not an independent semantic verifier.

## Artifact boundaries

- Public case records contain issue text, repository, base commit, split, and
  dataset revision. Regenerate upstream content under its original license.
- Graphs and contexts are source-derived artifacts with immutable hashes; retain
  upstream notices when distributing permitted examples.
- Raw Parquet, patches, added verification tests, and localization labels belong
  in evaluator-only storage and never in model prompts or model attachments.
- Every started inference attempt has a fsynced journal and terminal JSONL record
  or an interruption recovered from the journal. Terminal failures are retained.
- Manifests identify code, extractor, tokenizer/checkpoint, protocol, seeds,
  context hashes, exclusions, and selection. Old artifacts are preserved when
  context or freeze identities change.

## Metrics and limits

Reference-edit file recall@5 is the primary localization proxy; any-file hit@5,
false-relationship citations, abstention, invalid predictions, token use, latency,
and failures are separate outcomes. Sampling repeats are averaged per issue
before paired contrasts. Exploratory intervals resample repositories and issues;
repository-specific results and actual denominators are reported. Different
runtime or model configurations form separate strata.

The experiment concerns supplied metadata under a fixed source budget. It does
not establish behavior during unrestricted repository navigation or successful
repair. Quantization and runtime differences prevent a clean model-size claim.
Graph extraction can miss real relationships; checker ambiguity is not falsity.
Reference edits are not definitive root-cause labels. Negative findings remain
publishable, and completed calls never determine cohort membership.

## Reproduction and license

The public [source repository](https://github.com/stelaconsultingltd-rgb/GraphTrust-SWE)
and [v0.1.0-alpha.2 software preview](https://github.com/stelaconsultingltd-rgb/GraphTrust-SWE/releases/tag/v0.1.0-alpha.2)
provide original implementation code and synthetic examples. This preview does
not contain an accepted scientific freeze or empirical Gemma findings.

Use the README and REPRODUCIBILITY.md commands. The installed wheel includes an
original synthetic fixture suite and development protocol; `python -m graphtrust
demo` runs offline without repository or model downloads. Synthetic reports are
watermarked and cannot satisfy the scientific freeze gate.

Original code and fixtures are Apache 2.0. Dataset, upstream repositories, models,
and dependencies retain their own terms. Regeneration instructions and public
identifiers are preferred to repackaging upstream or restricted competition assets.
