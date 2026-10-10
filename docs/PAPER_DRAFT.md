# GraphTrust-SWE: Can Gemma verify misleading repository relationships?

**Subtitle:** A fixed-source robustness resource for missing and contradicted code-graph evidence

**Research status:** Methods draft and reporting template. The real Gemma pilot,
holdout experiments, and independent reproduction must supply empirical results
before this document is submitted. Synthetic demonstrations are software checks,
not evidence of model behavior. Intended sample sizes below describe the protocol;
replace them with frozen, verified manifest counts in the final paper.

## Abstract

Coding agents can use repository graphs to connect symbols across files, but a
graph can omit useful relationships or assert relationships that source does not
support. These defects should not be conflated: missing evidence reduces available
information, whereas contradicted evidence may direct an agent toward the wrong
location. We introduce GraphTrust-SWE, a reproducible resource for examining that
distinction while holding repository snapshots, source snippets, and snippet order
identical across experimental conditions. The protocol constructs conservative
Python relationships, applies seeded deletions and compatible endpoint swaps, and
evaluates issue localization with Gemma. A simple source-consistency checker tests
whether marking contradicted relationships helps, with unresolved dynamic bindings
kept explicit. Reference patches remain evaluator-only. Repeated sampling runs
are averaged within an issue, with paired comparisons and repository-aware
uncertainty estimates. The released implementation includes regeneration commands,
synthetic fixtures, provenance manifests, resumable inference logs, and reporting
tools. **Empirical outcome pending:** this draft makes no claim that false
relationships hurt more than missing ones or that checking improves localization.
Both positive and negative results will be reported with candidate coverage,
failed attempts, and limitations.

## Introduction

Repository-scale software tasks demand more than isolated code completion. A
developer must associate a symptom with definitions, imports, helpers, and callers
spread across a codebase. Graph representations offer compact relationship
metadata that can supplement the source an agent receives. The practical question
is whether the agent treats such metadata as a useful hypothesis or as authoritative
evidence when it conflicts with source.

A comparison that changes both graph quality and source exposure cannot identify
which change caused a localization difference. For example, replacing a correct
caller relationship might lead a navigation tool to retrieve different source
files. Worse performance would then reflect both misleading metadata and missing
code. GraphTrust-SWE separates those factors for a bounded diagnostic task: choose
up to five candidate repair files from a fixed issue and fixed source pack. The
graph changes; the source does not.

Our central question is whether contradicted relationships are more harmful than
missing relationships at a matched corruption target. We also ask whether a simple
source-consistency signal changes this sensitivity and whether observed behavior
persists across repository domains and a separately reported model configuration.
These are empirical hypotheses. They do not presume that a model will use graph
evidence, that our graph is exhaustive, or that localization entails successful
repair.

The intended contribution is a reusable diagnostic resource with an auditable
protocol. Repository retrieval, graph extraction, localization, and stale-context
analysis are established directions. Our contribution combines seeded relationship
interventions with invariant source exposure, evaluator isolation, and paired
failure-preserving analysis. A null result remains useful if it identifies a
model that ignores unreliable metadata or a task presentation that fails to elicit
graph use. We will distinguish those interpretations by reporting evidence
citations and the source-only baseline.

## Methods

### Corpus and separation of development from evaluation

The protocol uses [SWE-bench Lite](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite),
which contains public issue statements, repository snapshot identifiers, reference
patches, and verification test patches. The corpus acquisition step resolves an
immutable dataset revision and hashes local inputs. It writes source-facing case
records separately from evaluator-only reference material. The issue, base commit,
and repository identify a case; future repository history and reference patches
are unnecessary for graph construction or retrieval.

The target CPU corpus is the 300-issue test split. Development uses 20 issues,
five each from four repositories distinct from the six holdout repositories. The
planned holdout consists of ten structurally eligible issues from each of Django,
SymPy, Matplotlib, scikit-learn, pytest, and Sphinx. Seeded hashing orders issue
identifiers within each repository. Eligibility is assessed from source and graph
structure before examining model outcomes. An absent reference-edit file in the
source pack never causes exclusion. If fewer eligible issues exist, the resource
records the deficit and narrows the claim instead of replacing failures with
favorable cases.

### Conservative source relationships

The extractor represents Python source nodes and supported relationships with
file, line, and snapshot provenance. It handles deliberately restricted static
bindings rather than claiming a complete runtime call graph. A dynamic attribute,
ambiguous import, rebound name, or other unsupported binding is unresolved; absence
from the supported graph is not proof that execution can never traverse a
relationship.

This restriction matters for false-edge construction. Endpoint substitutions must
be compatible with the chosen relationship type and must change the original
relationship. Duplicates, unchanged edges, and relationships already supported
by the fixed source are rejected. Candidate interventions are classified according
to the extractor's declared resolution rules and audited with representative
source examples. Assertions about falsity must remain within that scope. Cases
where dynamic semantics prevent a justified classification remain unresolved
rather than becoming convenient negative examples.

CPU extraction uses pinned CPython 3.12.14. Each graph and intervention is identified
by its repository commit, source hashes, algorithm version, seed, and achieved
edit count. Requested severity may differ
from achieved severity when too few compatible swaps exist. The resource records
both quantities instead of silently treating every case as equally perturbed.

### Matched source exposure and intervention arms

A lexical retriever uses the issue statement and base source, then enriches its
anchors with clean source-supported graph neighbors to assemble one candidate
pack. The source-only arm is therefore a shared-pack control, not an independent
lexical-retrieval system. Retrieval first seeks file diversity, targeting at least
ten production files when the source and budget permit. Test,
generated, and vendor paths are excluded by the documented policy. Snippets retain
their source IDs and line bounds, and truncation is explicit. Truncated callers
prioritize deterministic clean call-site lines. Metadata retains only supported
relationships whose endpoints are selected and original call-site line is
visible, before constructing any intervention. Structural qualification applies
to this subset. This CPU-development revision preceded all model outcomes.

The pack is built once per issue. Every arm reuses its exact UTF-8 bytes, source
IDs, and ordering. Prompt construction refuses to fit an oversized arm by trimming
only that arm's source. The same issue and instructions accompany the pack, with
the checked conditions adding the specified integrity baseline. A tokenizer-aware
budget must be measured with the actual model's chat template before protocol
freeze. CPU byte counts are conservative construction checks, not measured model
input tokens.

Six conditions are implemented: source only; clean graph; deleted relationships;
rewired relationships; clean graph with checking; and rewired graph with checking.
The clean graph is unperturbed under the extractor, not omniscient. Deletions
remove supported relationships; rewiring preserves node contents while changing
compatible endpoints. Standalone CPU diagnostics apply both mechanisms to full
snapshot graphs at 10%, 30%, and 50% targets under three seeds. Preparation also
checks a byte-bounded pack. Model interventions use a separately tokenized,
visible eligible-edge pack, one frozen seed and a 30% target. Report full-graph
size separately and requested/achieved corruption against each relevant edge
universe; CPU and model severities do not share a denominator.

For model conditions, construct rewiring first and match deletion to its achieved
edit count. Deletion samples supported edges independently; those edges need not
be the originals replaced by rewiring. The contrast therefore compares these two
seeded mechanisms at equal changed-edge counts, with different remaining graph
densities, rather than changing the same individual relationships in both ways.

The checker consults the full snapshot's source-derived graph without access to
intervention labels. Its evidence can exceed the model's truncated source pack.
Manifests record source spans, retained call sites, and definition-line coverage.
Every retained call line must be visible; this does not prove that every required
binding is visible. The
checker labels relationships supported, contradicted, or unresolved within its
limited rules. The prompt permits lexical fallback and tells the model that
unresolved is not evidence of falsity. This is a source-integrity baseline, not
a trained verifier, semantic execution engine, or independent proof of graph
soundness. Computational checking and additional prompt guidance are bundled in
the checked condition; the study cannot isolate their contributions without a
further ablation.

### Inference and output discipline

The primary planned configuration is Gemma 4 E2B with the supported Transformers
path on a free Kaggle T4. It targets 60 issues, six conditions, and two paired
sampling seeds, or 720 logical localization calls. A separate Gemma 4 E4B GGUF
configuration targets a balanced 30-issue subset with all six conditions and one
seed, or 180 calls. Different runtime and quantization configurations are analyzed
separately; this is not a controlled model-size experiment. Exact checkpoint,
runtime versions, device map, chat-template hash, quantization, and generation
settings must accompany the final report.

Before the holdout is frozen, the pilot targets ten development issues, six
conditions, and two seeds. It uses a 4,000-token total input target and at most
256 output tokens, with thinking disabled. Freeze requires at least 95% timely,
typed outputs, zero out-of-memory failures, at most one timed-out issue per
condition, and at least 25% of clean-graph attempts citing a supplied relationship.
Semantic invalid predictions are reported separately. Any memory failure, or
timeouts on at least two issues in a condition, triggers the same reduced budget
for all arms and a complete new versioned pilot. Switching the primary
runtime to E2B GGUF is a protocol change, not a hidden substitution mid-holdout.

The model returns structured JSON with ranked file paths, source IDs, graph edge
IDs, and an abstention flag. It can cite source, graph evidence, both, or abstain.
It is never required to repeat graph relationships. Every attempted call is
written to a durable JSONL log with timing, tokens, hashes, output, and terminal
status. Resume skips existing logical run IDs, including recorded failures. A
timeout reflects the documented enforcement mechanism; elapsed-after-return
classification is not a hard interruption guarantee.

### Metrics and statistical unit

The primary metric is file recall@5: distinct reference-edit files among the first
five predicted slots divided by the number of reference-edit files. Hit@5 is
reported separately. Reference edits are useful localization proxies, not uniquely
correct explanations of an issue. Other valid fixes may edit different files.
Invalid or duplicate slots are not replaced. Under response protocol v2, semantic
or citation errors do not erase otherwise valid literal file predictions.
Whole-output JSON/type decoding failures are separate from invalid predictions.
Invalid paths do not earn credit, and explicit abstentions, contract failures,
timeouts, and errors remain in the localization denominator with zero credit.
Missing or empty evaluator gold is disclosed and excluded rather than fabricated.

The compact v2 response requires files and permits optional citations and
abstention. We accept a complete bare JSON object or one complete JSON-tagged
fence, with no prose or fragment extraction. A fresh complete development pilot
is required for this revision; earlier outputs retain their original contract.

The report includes cited known-false relationships per issue, graph and source
citations, abstention, invalid predictions, parse failures, tokens, latency, and
timeouts. Citation counts measure attributed evidence use, not the model's hidden
reasoning. The candidate coverage ceiling is the maximum recall achievable from
visible reference files under the five-file output limit. We retain low-coverage
cases and show this ceiling alongside results.

Sampling repeats are averaged within each issue before comparison. Paired
differences use cases with the same sampling-seed sets in both arms, including
terminal failures. The primary contrast is rewired minus deleted file recall@5;
negative values support the hypothesized greater harm of contradicted evidence.
Checking contrasts compare each checked arm with its corresponding unchecked arm.
They are secondary contrasts; additional arm comparisons are exploratory and
carry no confirmatory multiple-comparison claim.
Reports provide per-repository summaries and exploratory 95% percentile intervals
from hierarchical repository/issue bootstrap resampling. With only six repository
clusters, broad population generalization is weakly supported; single-repository
intervals are not presented as population uncertainty. Repeated calls are not
independent issues.

## Experiments and results — completion template

**Real model results have not been inserted.** Do not convert the synthetic demo
report into this section. Populate the following only from frozen manifests and
the original evaluation logs:

- Actual eligible CPU/dev/holdout counts, exclusions, and source-pack coverage;
  achieved full-graph and visible intervention severities.
- Pilot model identity, exact-token budgets, parseability, timeouts, memory
  failures, and graph-citation frequency. Document every pre-freeze revision.
- Primary per-condition recall and hit metrics, paired rewired-minus-deleted
  difference, checking differences, uncertainty intervals, and terminal failures.
- Per-repository heterogeneity and balanced-subset replication as separate model
  strata. Disclose missing or incomplete paired arms.
- Audited examples connecting a cited relationship to visible source and the
  prediction. Include non-adoption of false evidence and unsuccessful checking.

**Figure 1:** Missing versus false relationships. Plot primary recall from
recorded rows with repository-aware intervals; caption the issue count, failure
policy, achieved perturbation severity, and candidate ceiling.

**Figure 2:** Source-checking benefits and costs. Show matched recall comparisons
and inference latency. Report checker preprocessing time separately when measured;
inference latency alone is not the full verification cost.

**Figure 3:** Results across repositories. Show per-repository arm means with
actual issue denominators. Separate model configurations; do not collapse E2B
and E4B GGUF into one figure legend implying a controlled size comparison.

An optional repair demonstration is separate from this experiment. Graph-driven
navigation changes exposed source and therefore changes the causal question. If
quota and locally validated environments permit, preselect twelve cases and report
all attempts in three conditions under the specified four-minute allowance. Omit
the demonstration if those prerequisites fail. Localization outcomes never
substitute for executed repair verification.

## Related work

[SWE-bench](https://arxiv.org/abs/2310.06770) supplies real issue and repository
snapshots for evaluating software repair. Our proxy task reuses that provenance
without claiming a repair solve rate. [RepoCoder](https://aclanthology.org/2023.emnlp-main.151/)
combines iterative retrieval with generation for cross-file completion, while
[RepoGraph](https://proceedings.iclr.cc/paper_files/paper/2025/file/4a4a3c197deac042461c677219efd36c-Paper-Conference.pdf)
uses repository graph structure for software engineering agents. These precedents
establish that repository context and relationships are useful research objects;
GraphTrust-SWE does not introduce them.

[LocAgent](https://aclanthology.org/2025.acl-long.426/) studies graph-guided
localization with changing retrieved code. Its Acc@k requires all reference
locations; our fixed-pack recall@5 and any-file hit@5 are different measures.
We make no numerical superiority comparison.

[Weng et al.](https://arxiv.org/abs/2605.14478) investigate temporal staleness of
retrieved helper snippets in code completion. Our distinction is an intervention
on relationship metadata while source snapshots and snippet bytes are invariant.
The public [codegraph-loc resource](https://github.com/danielmantiglia/codegraph-loc)
also supplies graph generation and localization tools for this competition. The
resource claim here must therefore rest on controlled corruption, failure logs,
evaluator isolation, and regeneration rather than generic graph auditing.

## Limitations and reproducibility

Our graph omits dynamic Python behavior and unresolved bindings. Static
contradiction tests cannot prove arbitrary runtime impossibility. Candidate packs
are small and lexically selected; a fixed-source diagnostic does not represent a
complete interactive agent or establish downstream repair effects. Public issue
exposure permits contamination. Endpoint rewiring is an artificial failure family
and need not match production index defects. Matching a target corruption
percentage does not equalize the information value of removed and replaced edges.

The source checker shares extraction assumptions with graph construction and may
be unusually well matched to the intervention family. Citation reporting is
observable behavior, not introspection. A negative result could indicate robust
verification, graph non-use, floor performance, or weak visible perturbation; these
possibilities require coverage, citation, and per-case audits. Small repository
counts limit population inference, and distinct model runtimes preclude an
unconfounded size conclusion.

Original code is released under Apache 2.0 with documented upstream attribution.
Regeneration uses pinned dataset and repository identifiers; upstream licenses and
model terms remain applicable. Evaluator-only patches and verification tests must
never enter inference attachments. The package includes synthetic fixtures that
exercise the complete CPU path without downloading a repository. Real experiment
artifacts must include source and context hashes, exclusions, split manifests,
runtime identities, logs, scored CSV rows, and machine-readable summaries. Every
number and figure in the final submission must be traceable to those records.

## Finalization checklist — remove before submission

- Confirm live official rules and word counting; edit the complete paper to about
  2,700–2,800 words including references and captions, below the stated cap.
- Replace intended counts with measured counts; insert empirical results and
  uncertainty, including negative findings and failures.
- Produce the three figures from the final records and audit their captions.
- Add the tagged repository, immutable artifact hashes, executable notebook, and
  independently verified reproduction instructions.
- Obtain separate scientific-claim and reproduction reviews, then verify the
  Kaggle Writeup is submitted instead of merely saved as a draft.
- Internal submission target: 11 November 2026, Perth. Revalidate the official
  deadline on the competition page before relying on the working schedule.
