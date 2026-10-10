# Full-snapshot CPU diagnostics

The standalone `scripts/cpu_graph_diagnostics.py` evaluates the full source graph
for every prepared issue. It does not construct model contexts, read evaluator
answers, or call a model. Its three corruption seeds and 10%, 30%, and 50%
requested severities remain the registered CPU grid. Endpoint swaps reject every
relationship already supported anywhere in the full graph, including other call
sites, and preserve node contents and source provenance.

Schema 2 adds an optional process count. A cautious laptop launch while corpus
preparation is still running is:

```powershell
python scripts/cpu_graph_diagnostics.py --prepared runs/cpu-test --out runs/cpu-fullgraph-test-v2 --workers 3 --allow-partial
```

The default is `--workers 1`. Each worker loads one graph from its pinned artifact;
parsed graphs are not sent between processes. The queue contains at most the
requested worker count. Graph-file hashes deduplicate repeated snapshots, while
every issue retains its own validated public identity and graph mapping. Only
the parent writes graph records and final reports. Aggregation follows the
deterministic input order rather than process completion order.

Preparation may add records after an invocation starts. Resume the same output
directory with the same script, package, protocol, dataset manifest, and filters
to validate saved records and process the enlarged inventory. Worker count can
change on resume without changing scientific identity. Run final verification
without `--allow-partial` or a case filter after all 300 cases are prepared:

```powershell
python scripts/cpu_graph_diagnostics.py --prepared runs/cpu-test --out runs/cpu-fullgraph-test-v2 --workers 3
```

`complete_cpu_resource` requires all 300 test IDs from the pinned public manifest,
300 successful records, no duplicate issue IDs, no failures, and no synthetic
watermark or case filter. A strict incomplete run saves a partial report and
raises an error. Inspect `MANIFEST.json`, `SUMMARY.json`, and every exclusion;
the completion gate does not establish a completed model pilot or protocol freeze.

## Record integrity and migration

Every graph job validates preparation schema, script/package/extractor/protocol
identities, graph byte hashes, repository commit, and source snapshot identity.
It checks these identities before and after computation. Every issue alias is
validated even when its graph was already diagnosed. Cached records require the
matching schema and identities plus their full record and scientific hashes.
Failures remain visible and prevent final completion.

Preserve v1 evidence under its original identity. Use a fresh v2 output directory
after upgrading the script. Do not copy or relabel v1 per-graph records as v2;
their schema and script fingerprints differ. Original package source and the
model protocol are unchanged by this runner update.

## Scientific parity and execution measurements

For the same schema-2 script and inputs, serial and parallel modes produce exact
matching scientific fields: interventions, counts, requested and achieved
severities, exclusions, source/node hashes, selected anchors, topology metrics,
and checker classifications. Each graph record's `scientific_sha256` identifies
this canonical content. `result_sha256` and manifest file hashes protect the
complete records, including execution measurements, and therefore can differ
between fresh serial and parallel runs. Saved records remain byte-identical when
reused.

Durations and `process_lifetime_peak_rss_bytes` depend on execution. RSS is the
worker process's lifetime high-water mark; a reused process may have handled a
larger graph earlier. It is not independent per-graph memory, and summing such
peaks does not estimate the simultaneous pool peak. Timing in each graph record
measures diagnostic computation; `EXECUTIONS.jsonl` records worker count,
validation process IDs, cache reuse, and parent wall time for each invocation.
Cached graphs retain their original durations, so summed diagnostic time is not
the current resume's wall time. Null RSS means measurement unavailable.

Use measured available memory and actual later-repository peaks before raising
worker count. A multi-process speedup or one-hour CPU300 finish cannot be inferred
from a small synthetic test. The focused tests compare scientific parity,
cross-worker resumption, failures, aliases, schema migration, and the completion
gate. Their temporary 300-record fixture is explicitly a control-flow test and
does not count as real corpus completion.

These metrics describe the declared lexical graph and artificial corruption
family. Source-consistency checking shares the extractor and does not establish
runtime truth or independent semantic verification. CPU deletion and rewiring
share requested severities; achieved counts can differ because target swaps are
paired and constrained. The model experiment's matched achieved counts are a
separate design.
