# Independent review of the final v8 development contexts

Reviewed 10 October 2026. Scope: `runs/pilot-tokenized-v8`, current source-packing
and edge-filtering code, the protocol, and the three-case audit in
`MANUAL_AUDIT.md`. This review performed no model calls and read no evaluator
patches, verification tests, or reference-edit labels.

**Decision: no scientific construction blocker remains to running this pilot.**
The bounded revision addresses the earlier absence of inspectable call lines.
Further feature growth is not required before measuring real model feasibility.
The contexts remain development artifacts, not a frozen or completed experiment.

## Fresh verification

The reviewed implementation is
`bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`;
context identity is
`65ba6eabb2a8c3f66fdbb8f95ca6af7282b336dd70ff5d64725a0abd5bbf58d6`;
protocol identity is
`f12e3788aff29530923d70b2af732ed8d63a43125aa171168579bc6bd5166dff`.
These were independently recomputed and matched the manifest.

Read-only checks independently confirmed:

- Ten development cases and all 60 conditions; literal source-pack bytes match
  across each case's six arms and supplied snippets match graph source slices.
- All 73 clean and 20 false retained call sites are physically visible. Every
  false endpoint relationship is absent from the full source-derived graph.
- Matched actual deletion/rewiring counts, with two changed edges per issue.
  Achieved severity ranges from 25% to 40%; “30%” remains a nominal target.
- The local pinned tokenizer reproduces all recorded input counts, with a
  maximum of 3,928 tokens. Every selected case has at least ten candidate files.
  Actual loaded-model token agreement must still pass the runtime preflight.
- Seeded structural selection and its exclusions/shortfalls reproduce from
  public cases, qualification records, and the protocol, without opening gold.

Evidence and the verification script are under `runs/scientific-review/`:
`v8-evidence.json`, `verify_v8.py`, and `v8-verification.log`. An initial error in
the review script's multiline snippet parser was corrected; its diagnostic log
is preserved separately. It was not a resource-code failure.

## Selection and intervention independence

Call-site anchoring uses clean source relationships and deterministic priorities
before corruption. The same pack is then reused across arms. Filtering retains
only relationships with visible original call lines before applying the existing
minimum-edge and perturbability rules. Neither gold success, known-false labels,
nor model outcomes determine the pack or eligibility.

The revision can change cohort membership through declared structural eligibility;
that is acceptable before model evaluation. The manifest exposes the resulting
shortfalls. Sixteen of the twenty development cases qualify; the ten-case pilot
is distinct from a claim that all twenty cases are eligible. Do not later replace
poor-performing cases or reinterpret the revision as outcome selection.

## Scientific interpretation

The clean/missing/false comparison supports a fixed-excerpt metadata-effect
estimand. The new call lines provide inspectable lexical evidence, but do not
provide a complete proof of bindings. The manual audit explicitly finds missing
definition lines in its three examples and a missing import in the astroid
example. A wrong target name can be suspicious without establishing arbitrary
runtime impossibility from the excerpt alone.

The checker consults the full same-commit source-derived graph and can access
evidence beyond the localization model's excerpts. Its benefit therefore measures
the effect of supplied integrity annotations plus guidance and additional source
access through the checker. It does **not** establish autonomous agent verification
from identical excerpts, an independent semantic verifier, or runtime soundness.
All model source excerpts remain fixed; checker evidence access is the disclosed
asymmetry. Current paper/resource wording acknowledges this adequately.

Retain the exploratory cluster uncertainty, reference-edit proxy, citation limits,
and separate-runtime replication interpretation from the earlier review. A real
complete pilot must establish parsing, graph citation, memory/time behavior, and
runtime identity before freeze. The present checks establish constructed context
integrity only. No reviewed empirical model result supports the central hypothesis
or checker efficacy yet.
