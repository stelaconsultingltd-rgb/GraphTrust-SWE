# Execution status — 10 October 2026

The public implementation preview is available at
[GraphTrust-SWE alpha.2](https://github.com/stelaconsultingltd-rgb/GraphTrust-SWE/releases/tag/v0.1.0-alpha.2).
The final scientific study, empirical release and Kaggle submission remain pending.
Software fixtures and synthetic demo outputs are not research evidence.

## Verified development evidence

The pinned SWE-bench Lite corpus contains 300 test and 23 development issues.
Reference patches and added tests remain in evaluator-only storage. Structural
eligibility, contexts and interventions never use those labels.

A real Gemma 4 E2B development pilot completed all 120 scheduled attempts on
10 October: ten development issues, six conditions and two sampling seeds.
An independent audit found 118 timely, typed outputs (98.33%), 83 valid predictions,
35 predictions with semantic validity flags and two parse failures. These status
categories account for all attempts; validity flags overlap. There were no recorded
retries, timeouts or out-of-memory failures. Ten of twenty clean-graph attempts
cited a valid visible relationship. No reference-edit localization scoring or
confidence intervals were produced from this audit.

That pilot belongs to package 0.2.0 and implementation fingerprint
`3a5cd6d5252efc932d50dbb831d3607558363f5035bd3509fd2599629310b792`.
Its exact official Kaggle checkpoint fingerprint is
`8463a7f638c3087f7869b42db1a70578be5bee5f727a7579bc5553b46aea414b`;
its tokenizer fingerprint is
`ca7db376622726274dd8d16d6fa0a7fe86001167152052945d235c3b8b13bbf6`.
All records, attempt starts, environment and source/context identities were
preserved locally. Earlier tokenizer and output-contract failures remain part of
the development history; their responses have not been salvaged or reclassified.

## Prospective package 0.3.0

The original extractor failed on a deeply nested SymPy source AST. The revised
generic traversal retains depth-first order and custom scope handling while
using an explicit stack. Independent extraction of the previously failing full
snapshot succeeded: 1,518 Python files, 36,107 nodes, 145,373 supported relationships,
150,067 unresolved bindings and zero extraction errors. This is CPU validation,
not a model finding. Custom visitors and binding resolution retain documented
depth limits. The revised extractor fingerprint is
`4aa19292fa5120f4bb3971d5ccbd480bb669f9ffeac3cb5778d35620e8c39c5f`.

The prospective public exporter retains every terminal attempt, uses explicit
metadata and outcome allowlists, redacts invalid ranked slots without filling
them, and links exported rows to original canonical record hashes. It excludes
raw prompts, responses, source packs and evaluator labels. Matching source,
snapshot, tokenizer and model identities are checked before publication;
complete scored joins regenerate aggregate reports and figures. The author and
independent combined suites each passed all 212 tests (180.825 and 144.609 seconds,
respectively), with unchanged Python and protocol bytes. A fresh installed wheel
passed the six-condition offline synthetic demo and manifest checks.

These changes alter the study implementation identity. The package 0.2.0 pilot
cannot freeze package 0.3.0. All repository graphs and contexts will be regenerated
in fresh directories, followed by a complete real development pilot against the
final reviewed package. There is no accepted final package 0.3.0 freeze or
holdout model result.

## Compute and remaining work

The earlier CPU preparation attempted all 300 test cases and recorded 299
successful cases plus the diagnosed SymPy recursion error. Legacy continuation
and partial diagnostics retain their original identities. They do not establish
a completed final CPU resource. A separately reviewed one-shot pipeline started
on 10 October to regenerate all 323 cases across 320 unique snapshots. Its startup
audit passed; full source byte verification, preparation and diagnostics are
pending. It preserves source and evaluator bytes and imports no old graph caches.

A CPU-only Kaggle build produced the pinned CUDA Gemma 4 GGUF runtime wheel.
Independent downloads verified its bytes, source pins and CUDA build settings.
The wheel is 269,105,486 bytes, SHA-256
`bf976c8a7bc51a812bb742d99559bfcdba4593103fce6b548e546589dc86e77d`.
Model loading, inference and a replication runtime lock remain untested.

The primary experiment, optional GGUF replication, paired issue-level statistics,
three traceable figures, final paper, empirical release and actual Kaggle Writeup
submission remain to be completed. The optional repair demonstration is deferred
until the primary study finishes and quota permits it. The approved limits remain
free compute, 40 GPU hours, no training or paid APIs, internal submission by
11 November and official deadline 13 November 2026 at 07:59 Perth. Winning is
not guaranteed.
