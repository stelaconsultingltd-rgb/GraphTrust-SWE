# Full-snapshot CPU graph diagnostics

The model-facing preparation diagnostics apply interventions to a bounded source
pack. These can contain very few visible call relationships and are exposure
checks, not a repository-scale corruption benchmark. The standalone runner below
adds full-snapshot diagnostics without changing package code, model contexts,
selection, or the development/frozen model protocol.

```text
python scripts/cpu_graph_diagnostics.py --prepared runs/dev-cpu-v8 --out runs/cpu-fullgraph-dev-v1 --allow-partial --case-ids pylint-dev__astroid-1866,sqlfluff__sqlfluff-2419
python scripts/cpu_graph_diagnostics.py --prepared runs/cpu-test --out runs/cpu-fullgraph-test-v1
```

Wait for all 300 test preparations to finish before the final command. An
explicit `--allow-partial` preserves an incomplete audit while preparation is
still running. A final resource requires exactly the 300 official test IDs from
the answer-free `docs/DATASET_MANIFEST.json`, with no failures. Development or
synthetic diagnostics can never count as a completed resource. Use `--synthetic`
only for clearly watermarked software verification.

Each unique source graph receives deletion and compatible-target rewiring at
10%, 30%, and 50%, using seeds 1729, 2718, and 3141: 18 variants. Nodes, node text,
snapshot/source hashes and source provenance remain unchanged. Full-source
supported relationships cannot be inserted as supposedly false replacements.
Rewiring preserves edge count and incoming/outgoing degree sequences. Zero-change
variants, odd-pair shortfalls and bounded-search shortfalls remain in the results.

The runner records requested/achieved edits, before/after graph hashes, exclusion
counts, checker statuses, invariant checks, timing and peak resident memory. A
fixed, hash-ordered sample of at most 64 callers measures two-hop reachable-set
Jaccard and recall under corruption. Queries use the same source anchors in
every variant. These are controlled topology diagnostics, not localization or
repair outcomes. The checker uses the same lexical extractor as provenance; it
is not an independent semantic verifier. Memory is a process-lifetime high-water
mark, not per-variant allocated memory.

`IDENTITY.json` binds the script, package, extractor, public dataset manifest,
protocol and diagnostic definition. Preparation records must match current code,
protocol, commits, source and compressed graph checksums. Sidecars are content
hashed; resume reuses verified completed graphs. Different identities require
a new versioned output directory. The full 300-case pass maps issues to unique
graphs and computes each graph once. Repeated snapshots/seeds are not independent
observations; summary grids aggregate unique graphs without significance claims.
Immutable reports under `reports/` preserve earlier partial/failing inventories.

No gold files, reference patches/tests, tokenizer, model or GPU are used.

## First bounded verification, 10 October 2026

Four focused integration tests passed, covering invariants, parity/zero-change
variants, duplicate-snapshot reuse, cache tampering, stale implementation/graph
rejection, public case identity and incomplete-resource gating. Synthetic tests
are software verification only; their outputs are not research findings. The
log is `runs/tests-cpu-fullgraph-v1.log`.

The two real development snapshots above completed all 18 variants each:

| Snapshot | Nodes | Supported edges | Diagnostics time | Process-lifetime peak RSS |
| --- | ---: | ---: | ---: | ---: |
| astroid-1866 | 3,486 | 2,743 | 8.26 s | 84.2 MiB |
| sqlfluff-2419 | 2,422 | 10,467 | 24.06 s | 141.8 MiB |

All source/node invariants and replacement guards passed. At nominal 50%
rewiring, SQLFluff requested 5,234 changes but achieved 3,264–3,284 across the
three seeds; this illustrates why achieved severity is retained. These are
development diagnostics, not representative corpus results or Gemma outcomes.
Timing occurred alongside other CPU work; memory is cumulative across this
process. No full-corpus performance estimate follows from these two cases.

The content-hashed evidence is `runs/cpu-fullgraph-dev-v1/MANIFEST.json` and its
per-graph sidecars; raw output is `runs/cpu-fullgraph-dev-v1.log`. A repeat resumed
the verified sidecars in 1.38 seconds without regenerating interventions; its
output is `runs/cpu-fullgraph-dev-v1-resume.log`. The implementation fingerprint
remained `bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`.
