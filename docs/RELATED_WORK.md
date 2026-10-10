# Related work and claim boundaries

Research notes checked on 10 October 2026. These sources inform the protocol;
their reported results are not results from GraphTrust-SWE.

| Primary source | What it establishes | What GraphTrust-SWE adds or must distinguish |
|---|---|---|
| [Jimenez et al., SWE-bench, ICLR 2024](https://arxiv.org/abs/2310.06770) and [SWE-bench Lite dataset](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite) | Repository snapshots, issue statements, reference patches, and execution-based repair evaluation. Lite supplies a smaller corpus. | Localization against reference-edit files is a proxy task. It is not a SWE-bench repair solve rate. Public benchmark exposure permits training contamination; no claim of unseen issues is justified. |
| [Zhang et al., RepoCoder, EMNLP 2023](https://aclanthology.org/2023.emnlp-main.151/) | Iterative retrieval and generation use cross-file context for repository-level code completion. | Our matched arms manipulate relationship metadata after fixing source snippets. We do not introduce repository retrieval or iterative completion. |
| [Ouyang et al., RepoGraph, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/file/4a4a3c197deac042461c677219efd36c-Paper-Conference.pdf) | A repository graph can support modern software engineering agents. | A fixed-source corruption diagnostic measures sensitivity to metadata reliability. It is not a superiority comparison with RepoGraph, and our conservative Python graph is not a full program graph. |
| [Weng et al., When Retrieval Hurts Code Completion, arXiv:2605.14478](https://arxiv.org/abs/2605.14478) | A controlled study varies temporal freshness of retrieved helper snippets. It reports code completion effects for stale source context. | Source snapshots and snippet bytes remain identical here. Missing and contradicted relationships are distinct metadata interventions, not stale source or a temporal-validity benchmark. |
| [Mantiglia, codegraph-loc, pinned snapshot](https://github.com/danielmantiglia/codegraph-loc/tree/24fc2779a1c838b28f64252a959beddde8dc64a5) | A public competition resource includes graph audits, function localization, candidate reranking, and a graph-navigating Gemma agent. Its repository reports are author-provided evidence, not an independently reproduced comparison. | Controlled missing-versus-contradicted metadata with identical source remains the distinction; neither graph auditing nor agent localization is new. |
| [Google, Gemma basic text inference](https://ai.google.dev/gemma/docs/capabilities/text/basic) | The official documentation describes Gemma 4 inference with Transformers and a T4 example. | Documentation supports feasibility, not measured throughput on our pilot or a promise that the entire quota budget is sufficient. Record actual checkpoint, software versions, chat template, quantization, and device map. |

## Full-method comparison completed on 10 October 2026

The review used the complete papers, including their methods and limitations,
and the comparator's pinned source and experiment registrations. Versions,
source URLs and SHA-256 values are in [LITERATURE_LOCK.json](LITERATURE_LOCK.json).
Raw primary-source copies, extracted PDF text and retrieval timestamps are kept
locally under `runs/literature/2026-10-10/`; that directory is ignored by Git.
No comparator experiment was rerun during this review.

**Stale repository context.** [Weng et al., version 1, sections 3 and 6-7](https://arxiv.org/html/2605.14478v1#S3)
uses helper-signature changes: 31 mined candidates became 19 curated samples,
then 17 after a Qwen current-context success gate. Five oracle-selected evidence
conditions supply current snippets, stale snippets, no snippets, or both orders
of the mixed pair. Qwen2.5-Coder-7B-Instruct and GPT-4.1-mini each complete a
local wrapper; static call-pattern checks and paired sample comparisons score
outputs, rather than executable repairs. Declared limits include model-based
selection, one-parent signature drift, regex misses, five Python repositories,
and incomplete backend sampling identity. This already distinguishes misleading
from absent evidence. GraphTrust-SWE changes relationships while holding source
bytes fixed; it cannot claim the general harmful-versus-missing distinction as
new, and it does not measure temporal freshness.

**RepoGraph.** [Ouyang et al., conference paper, sections 3-5 and appendix E](https://proceedings.iclr.cc/paper_files/paper/2025/file/4a4a3c197deac042461c677219efd36c-Paper-Conference.pdf)
constructs definition/reference code-line nodes with containment/invocation
relations using Tree-sitter and dependency filtering. Search retrieves ego-graphs
for procedural localization/editing or an agent-selected tool action. Its
one/two-hop and flattened/summarized variants change exposed content and length.
The main unit is a SWE-bench Lite issue, evaluated through patch application,
executed repair tests, and inference cost with GPT-4/GPT-4o; an additional
Python CrossCodeEval study uses completion units. Appendix E limits the main
evidence to proprietary models, Lite and Python. This is a system-utility
comparison, not a relationship-corruption study with identical source contexts.
GraphTrust-SWE's fixed-context localization proxy therefore cannot establish
superiority over RepoGraph or inherit its repair evidence.

**codegraph-loc.** Reviewed commit
`24fc2779a1c838b28f64252a959beddde8dc64a5`, dated 9 October 2026 at
20:13:46 UTC (10 October, 04:13:46 Perth). The
[reranking generator](https://github.com/danielmantiglia/codegraph-loc/blob/24fc2779a1c838b28f64252a959beddde8dc64a5/scripts/10_build_llm_prompts.py)
selects BM25's top 25 plus up to 15 call neighbors independently for each graph;
signatures/docstrings and candidate coverage consequently differ across arms.
The [agent registration](https://github.com/danielmantiglia/codegraph-loc/blob/24fc2779a1c838b28f64252a959beddde8dc64a5/docs/preregistration_agent.md)
compares fuller versus released/emulated graph views on 1,359 issues
(2,718 episodes), using Gemma 4 31B, search/neighbors/read/submit, 20 tool calls
and 30 turns. It scores edited-node Hit@5 with paired issue bootstrap intervals;
it neither edits nor tests code. Disclosed limits include schema emulation,
custom tools, API-error retries, incomplete-pair exclusions and sparse neighbor
use. These are coverage/navigation comparisons, whereas our primary diagnostic
keeps nodes, excerpts and ordering identical and intervenes on relationships.
Our resource should distinguish that control, not claim a new localization
benchmark category.

## Positioning to retain in the submission

Use: “GraphTrust-SWE provides a reproducible, fixed-source protocol for testing
whether missing and contradicted repository relationships affect Gemma localization,
with a simple source-consistency baseline.”

Avoid: “the first graph benchmark,” “sound call graph,” “root-cause accuracy,”
“agent repair performance,” “E4B is better because it is larger,” or “graphs make
agents hallucinate.” Those claims require evidence the current protocol does not
provide. A harmful false-relationship effect is a preregistered hypothesis, not an
established finding.

## Literature review completion checklist

- [x] Read the full methods and limitations of the two closest papers and the public comparator's methods/source (10 October 2026).
- [x] Pin codegraph-loc and record paper versions/source hashes in `docs/LITERATURE_LOCK.json`.
- [x] Record the intervention family, source-control design, models and evaluation unit for the close comparators above.
- [ ] Include `docs/LITERATURE_LOCK.json` in the final release manifest.
- [ ] Search primary literature again before submission for closely related metadata corruption studies; this dated comparison is not a priority claim.
- [x] Treat these works as related research, not experimentally reproduced baselines.
- [ ] Keep the final paper's references concise and retain this fuller review trail.

The Kaggle [evaluation page](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/overview/evaluation)
and [submission requirements](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/overview/submission-requirements)
are administrative sources. Their complete content and competition metadata
were retrieved through the official Kaggle API on 10 October 2026 and preserved
in `runs/official/competition-pages.json` and `competition-metadata.json`.
They confirm the 3,000-word maximum, five equally weighted judging criteria,
required paper sections, and the need to save then submit the Writeup.
The submission deadline is 12 November 2026 at 23:59 UTC
(13 November at 07:59 Perth). See
[COMPETITION_REQUIREMENTS.md](COMPETITION_REQUIREMENTS.md) for the administrative
record; recheck for organizer updates before final submission.
