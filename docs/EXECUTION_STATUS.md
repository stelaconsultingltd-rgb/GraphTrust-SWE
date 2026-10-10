# Execution status — 10 October 2026

The resource implementation is available. The empirical study and competition
submission are pending; no Gemma findings or winning claims are reported.

## Verified locally

- Pinned SWE-bench Lite: 300 test and 23 development issues. Twenty development
  issues belong to the four protocol repositories. Raw labeled Parquet and gold
  are isolated under evaluator storage; checksums validate.
- Conservative graph extraction, deterministic interventions, matched actual
  corruption counts, fixed source contexts, checker, resumable inference journals,
  metrics, paired uncertainty, and three report figures are implemented.
- The latest integrated suite passed 154 tests with zero failures in 25.227
  seconds: `runs/tests-current-integration-v2.log`. This supersedes concurrent
  earlier test evidence. Historical CPU-runner and wheel/notebook reviews passed
  131 and 127 tests respectively before the experiment-bundler tests were added.
- A fresh wheel install outside the checkout completed the six-arm, twelve-call
  offline synthetic demo and manifest validation: `runs/wheel-check/output/`.
- Both notebooks executed in their default modes. The Kaggle notebook's default
  mode performs no model inference. Evidence: `runs/notebook-check-final-v2/`.
- Current executable source fingerprint:
  `bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`.
  Canonical protocol fingerprint:
  `f12e3788aff29530923d70b2af732ed8d63a43125aa171168579bc6bd5166dff`.
  The matching wheel SHA-256 is
  `c492f95f679792c81e9063d73825179dcab686e5bfadb1a63f05b8e256c77b71`.
  The current independently validated v9 pilot script is 175,175 bytes, SHA-256
  `998af06694c8a8b59d7b0a1b41fd1df2629bcd4ce1d6a2eff4a642a8e322f227`.
  The 175,063-byte script documented in earlier reviews is historical v8.

## Running and remaining work

The full 300-issue CPU preparation runs to `runs/cpu-test/`, with progress and
failures in `runs/prepare-test-v8.log`. Earlier interrupted workers left three
writer locks with dead process IDs; their original records were preserved in
`runs/stale-lock-evidence/`. Those cases must be retried before final CPU counts.
Seventeen pytest snapshot failures are confirmed Windows long-path acquisition
errors, with `LongPathsEnabled=0`; recovery is in progress. They are not structural
eligibility exclusions or evidence about graph quality.

Development preparation in `runs/dev-cpu-v8/` completed 23 cases with zero
errors. Its conservative byte bound gives no provisional qualifiers; this does
not exclude those cases from exact model-token qualification. Exact E2B
tokenization evaluates every successful development case in
`runs/pilot-tokenized-v8/`, now complete: 16 of 20 structural qualifiers, ten
selected issues, sixty contexts, 2,749–3,928 input tokens, and 11–15 files per
issue. All 73 clean and 20 false relationship callsites are visible. Prompt,
source, token and manifest checks pass. These are structural CPU diagnostics,
not model results. The final manual audit still finds missing target definitions
and an omitted import; full binding evidence is not guaranteed by callsite visibility.

The context audit found sparse visible callsites: six of seventy-one clean
relationships and two of twenty false relationships in the historical v6 pack.
Scientific review prompted one bounded development revision before model calls:
caller excerpts prioritize deterministic clean call lines, and metadata retains
only relationships with visible original callsites before intervention. Existing
edge/perturbability qualification applies to that subset, with shortfalls
disclosed. The checker uses the full snapshot; binding-visibility limits and this
access difference remain explicit.

The literature comparison and pinned comparator sources are documented in
`RELATED_WORK.md` and `LITERATURE_LOCK.json`. Official requirements are verified
in `COMPETITION_REQUIREMENTS.md`. Official E4B QAT Q4_0 GGUF checkpoint/file
identifiers and a pinned source build are in `MODEL_LOCK.json` and
`GGUF_REPLICATION.md`; their actual runtime remains untested.

The private E2B v8 development pilot started on 10 October at approximately
13:18 Perth, version 2 of `steve1136/graphtrust-swe-e2b-development-pilot`.
The live metadata confirms T4, internet enabled, private visibility and official
`google/gemma-4/Transformers/gemma-4-e2b-it/1` attached. The connector's initial
QuickSave silently dropped model attachments; the editor attachment and saved
run corrected this. The supervisor permits at most 120 calls and three hours.
Launch metadata and screenshot are in `runs/kaggle-pilot-v8/`. Version 2 stopped
before any localization calls: its checkpoint tokenizer identity differed from
the local Hugging Face tokenizer. Official per-file downloads confirm identical
vocabulary/processor/config bytes but different tokenizer configuration and chat
template bytes. The original failure and environment logs are preserved under
`version-2-output/`; about 199 seconds of GPU quota were used. All contexts must be
regenerated against the actual Kaggle version-1 tokenizer before another run.
No mismatch guard is relaxed. Fresh v9 materialization and independent inspection
confirm byte-identical contexts and selection; only the manifest now pins the
actual Kaggle tokenizer `ca7db376622726274dd8d16d6fa0a7fe86001167152052945d235c3b8b13bbf6`.
The v9 script's SHA-256 is
`998af06694c8a8b59d7b0a1b41fd1df2629bcd4ce1d6a2eff4a642a8e322f227`.
An editor Quick Save verified exact saved-source bytes and the retained official
model attachment without consuming GPU quota. The corrected pilot started as
Kaggle version 4 at approximately 13:41 Perth. It is running; actual processor
checks, output quality and acceptance remain pending. V8 failure evidence is
retained. Checkpoint/backend diagnostics are now saved before preflight guards.
Preserve actual environment/checkpoint fingerprints, outputs, and gate failures.
Freeze only if the complete real pilot passes; revise presentation/budgets only
on development cases if it fails. The holdout requires the accepted frozen code,
protocol, tokenizer, and backend. Replication must remain a balanced subset of
that primary cohort, even if the second runtime fails.

The primary study, GGUF replication, optional repair demonstration, empirical
paper results, public release tag/links, and actual Kaggle Writeup submission
have not been completed. The methods draft is explicitly labeled accordingly.
The optional repair demonstration depends on completed primary evidence, quota,
and locally validated environments; the local Docker engine is currently stopped.

The schedule and compute limits remain those in the approved plan: free compute,
40 GPU quota hours total, no training or paid APIs, internal submission by
11 November and official deadline 13 November at 07:59 Perth.
