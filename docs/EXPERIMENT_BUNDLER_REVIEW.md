# Independent experiment-bundler review

Reviewed 10 October 2026 against builder SHA-256
`609fe94c98482add4d30aca46ebaee7d582c887159185749d4e363ca431dee68`.
Scope: `bundle_kaggle_experiment.py`, its 14 focused tests, and
`KAGGLE_EXPERIMENT_BATCHES.md`. No package, protocol, or current pilot was changed;
no GPU session was launched by this review.

**Decision: resolve the reserved-session history-integrity gap before primary or
replication execution.** The rest of the reviewed contracts are appropriate for
later use, subject to a genuine accepted pilot and runtime validation.

This is the initial finding, retained as audit history. The resolution addendum
below confirms the subsequent fix; it is no longer an open software blocker.

## Substantive blocker: finalized history can disappear after a crash

`build_bundle` checks cumulative record/journal hashes only when the **last**
ledger session is finalized. If the last session is `reserved`, the checks are
skipped. The reservation does not record an immutable pre-session history prefix.
Consequently, a crash in session 2 permits dropping terminal failures and their
starts from already-finalized session 1 while the resume bundle still validates.
The dropped calls become eligible to run again.

This was reproduced independently using explicitly synthetic tooling fixtures:

1. Session 1 had a terminal `parse_error` and its original start. Its hashes were
   saved in a finalized ledger entry.
2. Session 2 was reserved, representing a crash before ledger finalization.
3. Both cumulative JSONL files were emptied, leaving the ledger intact.
4. The resume builder accepted the altered history and reconstructed the full
   720-call schedule, including the lost failed run.

Evidence: `runs/scientific-review/experiment-reserved-history-counterexample.json`.
This is a tooling defect reproduction, not model evidence.

The smallest repair is to pin cumulative history **before** each reservation:
record hashes plus exact byte lengths (and preferably start/terminal counts),
then require those prefixes to remain identical on every reserved-session resume.
New appended starts/terminal records can still be recovered as interrupted.
Existing finalized history must remain protected through later crashes. Reject
reserved legacy ledgers without verifiable baseline evidence, or require an
explicit documented recovery using the preserved prior finalized artifacts.
Add a regression covering this exact failure-plus-crash sequence.

## Contracts confirmed by inspection and fresh tests

- Inputs require exact protocol/context/source hashes, implementation identity,
  tokenizer accounting, six matched arms, and the declared sampling-seed sets.
  The primary backend must match the accepted pilot fingerprint exactly; runtime
  preflight saves actual identities before rejecting mismatches.
- Declared repository shortfalls reduce the actual schedule without substituting
  cohort members. Replication follows the primary's fixed first-five-or-fewer
  subset and fails instead of replacing cases. The archive records actual and
  nominal denominators separately.
- Within preserved history, duplicate/foreign IDs, missing original starts,
  changed identities, synthetic records, and malformed/truncated JSONL are
  rejected. Valid orphan starts become terminal interruptions; ordinary terminal
  failures are not retried. The blocker above concerns lost history after a
  reserved-session crash, rather than this ordinary resume path.
- Session reservations conservatively charge their full requested duration,
  including crashes, and enforce stage/session limits. Process-group shutdown
  and interruption finalization are implemented. Their actual Kaggle timing and
  output persistence remain runtime checks, not established by these unit tests.
- The embedded archive uses a narrow input allowlist. Wheel inventory rejects
  evaluator/test folders and recognized weight/Parquet binaries. Model weights
  and the GGUF CUDA wheel remain separate attachments.

All 14 existing focused tests passed independently; log:
`runs/scientific-review/experiment-bundler-tests.log`. Those tests do not cover
the reserved-after-finalized-history counterexample.

## Completion and acceptance boundaries

A session marked `finished` is a completed **batch**, not a completed study.
Before reporting study completion, require the full declared logical schedule to
have terminal records and report status counts and actual paired denominators.
All-terminal-failure schedules establish attempted coverage, not useful efficacy.
Complete declared shortfall cohorts must not be mislabeled 60/720 or 30/180.

The bundler accepts freeze/runtime-lock contracts; hash-shaped fields alone do
not independently prove a genuine pilot or GGUF development smoke. Retain and
verify their underlying records. No accepted pilot freeze exists at this review
point. GGUF build, model loading, memory fit, and generation remain untested.
T4 device names cannot establish account billing mode or account-wide available
free quota; externally verified session settings and quota remain required.

## Resolution addendum — 10 October 2026

Fresh independent review of corrected builder SHA-256
`08e2b87662cd5f396d55bf56660f3dda1a25e4baf2e664724799db96e31429e8`
confirms that the reserved-after-finalized history-loss counterexample is now
rejected. **The identified software blocker is resolved.** No additional
substantive blocker was found in this review of the correction.

Ledger schema 2 pins exact cumulative record/journal byte lengths, SHA-256
prefix hashes, and row counts before each reservation. Builder, supervisor, and
worker paths validate preserved prefixes before accepting append-only crash
extensions. Recovery verifies history first, retains existing terminal failures,
adds interruptions for orphan starts, and seals the crashed reservation's
post-recovery boundary. Unanchored legacy ledgers fail rather than inheriting a
claim of history integrity.

Fresh independent verification reproduced the earlier removal sequence: clearing
session 1's failure and start while session 2 remained reserved now raised
`Retained history differs from a pinned session prefix`. A legitimate appended
extension was accepted. Recovery preserved the original `parse_error`, retained
the new `timeout`, and converted the unmatched third start to `interrupted`.
All three original starts remained present, recovery was idempotent, and the
next reservation pinned all three terminal rows. Three reservations still charged
10,800 seconds without reclaiming the crashed allocation. The full 720 logical
schedule was unchanged, leaving 717 unattempted runs after those three terminal
outcomes. These are explicitly synthetic tooling checks, not a completed cohort
or actual inference results.

Evidence is saved in
`runs/scientific-review/experiment-history-prefix-v2-resolution.json`.
All 17 focused tests passed in a fresh independent run, including the new
loss-regression, valid crash-extension, and legacy-ledger cases. Log:
`runs/scientific-review/experiment-bundler-prefix-v2-tests.log`.
The original counterexample and initial test log remain preserved.

Scientific and operational launch prerequisites remain unchanged: use a genuine
accepted freeze and immutable cohort, preserve the complete downloaded journal,
records and ledger, verify free account/session settings, and test actual Kaggle
shutdown/persistence and any GGUF runtime before relying on them. A completed
batch is still not a completed study, and synthetic tooling acceptance cannot
satisfy the real pilot gates. This review changed only documentation/evidence;
it did not modify the package, protocol, or live pilot and launched no GPU work.
