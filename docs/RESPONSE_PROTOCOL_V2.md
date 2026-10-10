# Prospective response protocol v2

This is an implemented development revision, not a frozen protocol or a model
result. Its effect on Gemma remains unmeasured. Package version `0.2.0`, protocol
schema `2`, context contract `files_citations_v2`, and record schema `2.0` identify
the revision. Every new run key includes the response contract version.

## Complete response contract

```json
{"files":["pkg/example.py"],"citations":[]}
```

`files` is required and must be an array of strings. `citations` is an optional
array of strings, defaulting to `[]`. `abstain` is an optional JSON boolean,
defaulting to `false`. Accept either one whole JSON object or one whole
`json`-tagged fenced object (case-insensitive language tag), surrounded only by
ASCII whitespace. Untagged fences, prose, multiple objects, truncation, missing
files, duplicate JSON keys at any depth, invalid types, nonfinite numbers
(including exponent overflow), and unpaired Unicode surrogates fail decoding.
The parser never extracts a fragment, repairs a path, or guesses an identifier.

Decoded extra fields are retained and flagged. The required types determine
`contract_parseable`; semantic checks determine `invalid_prediction`. Semantic
violations include unknown/malformed file paths or citations, repeated array
entries, more than five files, more than two citations, extra fields, empty files
without abstention, or abstention with file predictions. Raw output, decoded
values, literal order, and the individual flags remain in the terminal record.

Valid citations must match exactly one visible namespace: a SOURCE ID, a
relationship `id`, or a candidate FILE path. Headers and inferred names are not
identifiers. Ambiguous matches are invalid. The validator sees no reference edits
or corruption labels. A supplied false relationship ID is a valid visible
citation; evaluator-only labels later count its use as a false citation.

## Localization and diagnostics

Score distinct reference-edit files in the literal first five predicted slots.
Unknown, malformed, or duplicated slots consume their ranks and are never
replaced. Citation errors and other semantic flags do not erase valid file
matches. Explicit abstention earns zero localization credit. Contract failures,
timeouts, backend errors, and interruptions also earn zero. Missing or empty gold
always yields null localization, including on abstentions.

`contract_parseable` records observed complete decoding. An elapsed timeout can
retain a parsed output and `completed_status` for diagnostics, but contributes
zero to `within_budget_contract_parseable` and localization. Observed semantic
flags and valid/false/invalid citation counts include late parsed outputs.
Rates use all attempts, with zero indicators/counts when no output was parsed;
sampling repeats are averaged within issue before paired statistics. Freeze
summaries distinguish observed and within-budget contract parse rates.

`invalid_citations` is the v2 invalid-reference count. Legacy columns
`invalid_source_ids` and `invalid_edge_ids` remain available for v1 reports;
they are zero in v2 because valid citations are resolved before assigning a
namespace. `source_citations` includes exact SOURCE IDs and candidate FILE
citations, with `file_citations` also reported separately. These diagnostics
measure attributed evidence, not hidden reasoning or semantic success.

The evaluator and freezer independently verify stored classifications against
the entire retained raw output and matching context version. Missing raw output
is rejected; it is never manufactured from decoded fields. Backend failures
retain an explicit null raw output. JSONL journals/records escape Unicode to
preserve malformed backend text safely. V2 per-record content SHA-256 uses sorted,
compact, ASCII-escaped JSON with nonfinite values forbidden. The physical JSONL
file SHA-256 is recorded separately. The freeze's `pilot_records_sha256` applies
the same encoding to the decoded ordered record array, identified by
`pilot_records_digest_rule: sorted_compact_ascii_json_v2`; run-key hashing retains its existing UTF-8
encoding and adds the new version field.

## Prospective evidence boundary

Old v1 records remain immutable and retain their original parser/scoring
semantics when reported. Only absent schema versions and explicit `1.0` records
enter the legacy reporting branch; unknown versions are rejected. Legacy and v2
records form separate model configuration strata and cannot supersede each
other. Old pilot outputs cannot be relabeled or resumed into a v2 log.

Rebuild the development contexts using the final implementation, protocol,
checkpoint, and exact tokenizer identities. Run all ten preregistered development
issues, six matched conditions, and seeds 17/42: 120 fresh attempts. At least
114 must be contract-parseable within budget. Require no memory failure, no more
than one timeout issue per condition, and at least 25% clean-arm calls citing an
actually supplied relationship. Semantic invalid rates are reported separately;
they are not substituted for this parsing gate. If any gate fails, retain the
complete pilot and revise only on development data before another full pilot.

The revision preserves source retrieval, fixed source bytes/order across all six
arms, issue/cohort selection, graph interventions, model sampling, the absolute
4,000-input/256-output budgets, and the 90-second elapsed allowance. It adds a
compact output instruction at the end of each prompt. No old outputs establish
that the revision improves the model, and no holdout outcomes select it.

## Independent cache publication correction

Graph extraction remains outside a short per-key publication lock. A fresh
builder now tracks whether it loaded a cache, then reloads and verifies any graph
published by a sibling before its own publication. Identical current artifacts
are reused. Stale fingerprints, different commits, and conflicting graph content
are refused without overwriting the sibling. This infrastructure correction
does not change graph extraction or relationship semantics. Deterministic
barrier tests cover the original publication interleave and preservation cases;
synthetic checks are software verification, not experimental evidence.
