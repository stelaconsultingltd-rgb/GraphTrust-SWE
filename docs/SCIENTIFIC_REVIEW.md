# Independent scientific review

Reviewed 10 October 2026. This review covers `PAPER_DRAFT.md`, `RESOURCE_CARD.md`,
`RELATED_WORK.md`, README, the protocol, and the relevant selection, intervention,
context, freeze, and scoring code. It is a review of the research foundation,
not an empirical review of Gemma behavior or a completed external reproduction.

Reviewed implementation fingerprint:
`5573a4a77b8487d5a20401a82707a0090ceec0d8e94fe2138b996e2fcca83613`.
Extractor fingerprint:
`7051e09a5c729ed75ee1baa7d84db320fa961c7c10de89efe46473c346bcc4c4`.
Subsequent changes require checking the affected findings again.

## Assessment

The foundation supports the proposed resource: issue-independent structural
selection, invariant source exposure, evaluator isolation, failure-preserving
logs, and issue-level paired analysis form a useful controlled diagnostic.
The paper correctly identifies its contribution as a relationship-metadata
protocol rather than the invention of graph retrieval. It explicitly presents
false-edge harm and checker benefit as hypotheses. It does not manufacture
model results from synthetic demonstrations.

**There is no reviewed real Gemma evidence establishing efficacy, GPU fit,
throughput, a successful pilot, or a frozen holdout.** The current paper is a
methods draft and reporting template. Neither the intended 60 issues nor 720
calls is an achieved experimental denominator. A resource release can precede
empirical completion if this status remains explicit; a results paper cannot.

One concrete intervention claim needs correction or implementation hardening
before scientific freeze. The additional empirical and reporting gates below
remain necessary.

The assessment and finding above record the initial review. The dated addendum
at the end verifies subsequent resolution while retaining that audit history.

## Finding requiring resolution before freeze

`perturb_graph` rejects replacement `(source, target, type)` relationships present
in the graph supplied to it. However, `materialize_case` supplies a packed graph
and removes edges to fit the common metadata budget. A replacement relationship
may therefore already be supported elsewhere in the full source graph, while
passing rejection against the reduced graph.

A synthetic counterexample was executed during this review: the full graph had
`a -> x` at line 1, `b -> y` at line 2, and `a -> y` at line 3. Supplying only the
first two edges to rewiring produced `a -> y` and `b -> x`; the former already
existed in the full graph. Both replacements were classified contradicted at
their retained original call sites. This distinguishes two definitions:

- A wrong target **at a particular resolved call site** can still be a true
  function-level relationship at another call site.
- The stronger documented rule rejects relationships supported anywhere between
  those endpoints. The current packed-graph path does not establish that rule.

Preserving the approved stronger rule requires using the full graph's supported
relationship set when rejecting candidates, plus a test for an omitted but valid
full-graph relationship. Otherwise revise the protocol, resource card, and paper
to a strictly call-site definition before any holdout outcomes are examined.
The existing whole-graph rejection test alone does not cover packing/pruning.
Evidence is recorded in `runs/scientific-review-counterexample.json`.

## Necessary empirical and interpretation gates

1. **Demonstrate visible evidence, not just visible endpoints.** Packing can
   truncate a function around a lexical match. Including both node IDs does not
   guarantee the asserted call-site line, import, or binding is in the supplied
   source. Audit and report visible call-site/binding coverage for the selected
   relationships, especially false ones. A model cannot verify source that it
   has not received. This is an exposure diagnostic, not permission to select
   cases using gold recall or model outcomes.

2. **Describe checker access precisely.** The implementation compares supplied
   metadata with the full snapshot's source-derived graph. This is legitimate
   non-gold information, but it can extend beyond the model's truncated source
   pack. State this explicitly. Do not claim that the baseline independently
   reasons over exactly the same snippets as the model. The checker shares the
   extractor and is intentionally well matched to endpoint swaps; successful
   checking is not evidence of arbitrary semantic verification. Checked arms
   also add instructions and status tokens, so benefit applies to that bundle.
   Measure preprocessing separately before claiming total verification cost.

3. **Keep source-only interpretation narrow.** The common source pack uses lexical
   anchors and clean supported graph neighbors. This is valid for the fixed-pack
   contrast, but source only is a shared-pack control, not an independent lexical
   retrieval baseline. README states this well; the paper's phrase “a lexical
   retriever” should also identify clean-graph neighbor enrichment.

4. **Report achieved corruption.** Model omission matches the actual number of
   rewired edges; this is better controlled than matching requested percentages.
   Show achieved counts and severities for the final visible edge set, including
   pair/parity/search shortfalls. A nominal 30% target may become much smaller
   with few edges. Matched edge counts do not match information value, topology,
   prompt length, or issue relevance. A result supports this deletion/rewiring
   family, not a general ranking of all missing versus false evidence.

5. **Pass a complete real development pilot.** Require ten development issues,
   all six arms and both seeds, exact runtime/template token counts, immutable
   checkpoint and environment fingerprints, acceptable parseability/time behavior,
   and manually inspected graph use. Freeze rejects synthetic, stale, incomplete,
   mixed-runtime, or mismatched-tokenizer records. The 25% clean-edge citation gate
   is a task-presentation diagnostic; citations alone cannot prove causal reliance
   or hidden reasoning. Explain that it was set before holdout evaluation.

6. **Freeze without outcome selection.** Selection code hashes issue IDs after
   structural eligibility; reference patches and retrieval recall are not inputs.
   This supports independence from gold outcomes. It still conditions inference
   on supported, perturbable Python relationships, so generalization is to that
   qualified corpus. Publish every exclusion and repository shortfall. Retain
   missing reference locations and report the coverage ceiling. Replica selection
   must remain a predeclared primary subset when a second tokenizer cannot pack
   a case; do not replace it with a favorable alternative.

7. **Use the correct statistical hierarchy.** Repeats average within an issue;
   720 calls remain at most 60 issues, clustered in six repositories. The
   repository/issue bootstrap is an exploratory uncertainty estimate, not proof
   of broad repository-population generalization. Present descriptive repository
   strata and actual paired denominators. Name rewired-minus-deleted recall as
   the primary contrast and checking contrasts as secondary before freeze. The
   reporter computes all 15 arm pairs; these additional comparisons should be
   exploratory unless a multiple-comparison policy is preregistered. Missing or
   incomplete runs must not disappear from reported completion status.

8. **Interpret failure and labels honestly.** Recall@5 is reference-edit file
   recall, not definitive root-cause accuracy or repair solve rate. Invalid slots,
   abstentions, timeouts, errors, and schema failures do not earn localization
   credit. Empty/missing gold remains explicitly excluded, with denominators
   disclosed. Original attempt logs, not an edited summary, must establish that
   terminal failures were not selectively retried.

9. **Separate model configurations.** E2B Transformers and E4B GGUF differ in
   checkpoint, tokenizer/template, quantization, runtime, and potentially dtype
   and exposed snippet packing. Report robustness within each configuration.
   Differences cannot identify an effect of model size. Verify actual Gemma
   inference and quota use; documentation and CPU smoke tests do not measure them.

## Claims and release readiness

The draft's limitations are appropriately cautious about static versus runtime
truth, contamination, artificial corruption, candidate floors, citation evidence,
and the absence of repair conclusions. Use “source-contradicted under the declared
lexical resolver” where “false” might be read as runtime impossibility. A null
effect can reflect metadata non-use, insufficient evidence, floor performance,
or robust source checking; citations and coverage diagnose these possibilities
but do not uniquely distinguish them.

The related-work notes already avoid a first-ever claim. Complete the promised
full-method review, pin the codegraph-loc comparator commit, and refresh primary
literature before submission. Existing links and high-level distinctions are
not a completed novelty audit.

Independent reproduction still requires a fresh installation from the release
artifact and regeneration using published immutable identifiers. The evaluator
boundary should be audited on the actual Kaggle bundle, not inferred only from
directory names. A release needs a tag, public working links, complete measured
manifests and original records. Administrative publication and actual Writeup
submission remain separate completion checks.

During this review, 68 targeted tests from `test_pipeline`, `test_interventions`,
`test_metrics`, and `test_corpus` passed in Python 3.12. These establish software
contracts and the tested synthetic scenarios; they do not resolve the packed
false-edge counterexample above or substitute for the empirical gates.

## Resolution addendum — 10 October 2026

Fresh review of implementation
`defd3dc1dc2d30cf05cedbdce1e887fe29712bcd1313db4a71b9e5b1bfb47789`
confirms that the packed-graph rejection defect is resolved in the CPU and model
materialization paths. `perturb_graph(..., source_graph=full_graph)` checks exact
snapshot identity and forbids replacements supported anywhere in that full
source-derived graph. Both pipeline callers now supply the full graph. The
earlier counterexample remains recorded as historical evidence, not a claim
about this corrected implementation.

Fresh verification: all 39 intervention and pipeline tests passed; the log is
`runs/scientific-review-resolution-tests.log`. The new rejection test reproduces
the old unguarded case and rejects it with the full-source guard over 20 seeds.
An independent review script also checked the original four-node counterexample
over 20 seeds, obtaining zero accepted replacement edges for every seed. It
verified six-arm span diagnostics on the synthetic fixture. Results are saved in
`runs/scientific-review-resolution-check.json`. These are software checks,
explicitly synthetic, not Gemma findings.

Materialization now records exact supplied source spans, visible relationship
call-site IDs, and nodes whose definition start line is visible. Qualification
reports clean and false visible-call-site counts. These are diagnostic only and
do not introduce gold/model-performance selection. They address missing exposure
accounting; a visible line or definition start still does not establish complete
import/binding visibility. The final study must report these diagnostics and
audit representative partial-source cases.

The protocol now explicitly identifies full-snapshot checker access, the primary
rewired-minus-deleted recall contrast, two secondary checking contrasts, and the
exploratory status of other comparisons. The paper and resource card have been
clarified to describe clean-neighbor pack enrichment, checker access beyond the
truncated source pack, and the limited interpretation of coverage diagnostics.

One small metadata discrepancy remains at this review point: the protocol's
primary metric identifier is `file_recall_at_5`, while scored records use
`file_recall_at5`. Align the identifier before freezing so machine-readable
claims reference an existing result column. It does not change the intended
estimand or the checked scoring logic.

The scientific gates remain open: a complete accepted real ten-issue pilot,
measured GPU/runtime feasibility, immutable empirical manifests, complete primary
paired runs, evaluator-only bundle audit, final achieved-corruption and exposure
reports, and independent release reproduction. No reviewed model results support
the hypothesis yet. The corrected foundation supports proceeding to that pilot;
it does not establish a completed experiment or submission.

## CPU exposure review and bounded revision — 10 October 2026

The exact-token pilot v6 audit, before any model calls, found only six visible
call-site lines among seventy-one clean relationships and two among twenty false
relationships. Eight of ten issues had no visible false callsite. Source bytes
were correctly matched, so the metadata contrast remained controlled, but direct
source-verification claims would be poorly supported. The review recommended one
bounded development revision before using GPU quota.

Implementation `bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`
now prioritizes deterministic clean call lines in caller snippets, preserving
lexical node ranking, file diversity, neighbor limits, and token budgets. It
filters metadata to selected endpoints with a physically visible original
call-site line before corruption. Existing minimum-edge and perturbability
qualification applies to that subset. The rule uses neither gold nor model
performance. Versioned rule names appear in manifests and the protocol. All six
arms still share identical source; binding visibility remains diagnostic and
full-snapshot checker access remains disclosed.

The root independently ran all 127 tests successfully in
`runs/tests-stable-v8-root.log`. Tests include call-site anchoring, removal of
invisible clean edges before intervention, shared-source integrity, and visible
call lines in all model arms. This is software evidence; fresh exact-token v8
qualification and a manual binding audit are pending. Publish resulting
shortfalls rather than changing structural rules to fill quotas.

The metric identifier was corrected to `file_recall_at5`. No real model evidence,
protocol freeze, or submitted paper exists at this checkpoint.
