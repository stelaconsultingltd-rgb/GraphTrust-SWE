# Independent schema-2 CPU diagnostics review

Reviewed 10 October 2026. No substantive blocker to the parent's bounded
`--workers 3` launch in a fresh v2 output directory was found. This conclusion
concerns the runner and its saved evidence; real all-300 completion remains
unverified.

The reviewed script SHA-256 is
`a7a6fe24e490b1432586cda121b665e0a67487b901f3530f8bf083b132c41129`.
The package, extractor, protocol, and pinned public manifest hashes were verified
before and after this review and are recorded in
`runs/scientific-review/cpu-diagnostics-v2-evidence.json`.

## Evidence and completion gates

Fresh independent execution of `python -B -m unittest discover -s tests -p
test_cpu_graph_diagnostics.py -v` passed all 10 tests in 13.884 seconds, exit 0.
The log is `runs/scientific-review/cpu-diagnostics-v2-tests.log`. Tests exercise
actual Windows spawned processes, deterministic serial/parallel scientific
parity, worker-count-independent resume, failures, alias validation, schema-1
rejection, invalid worker counts, and positive/negative completion gates. Their
temporary 300-record control-flow fixture is software evidence only.

The independent read-only verifier `runs/scientific-review/verify_cpu_v2.py`
passed, exit 0. The two real Astroid/SQLfluff development snapshots contain 36
variants whose scientific fields exactly match preserved v1 serial artifacts.
It checked current result digests, preparation identities, graph byte hashes,
source/node hashes, the full seed/severity grid, and the recorded intervention
invariants. Cached graph-job validation succeeded with regeneration forbidden,
and graph/record/output byte hashes stayed unchanged. The verifier did not
rerun corruption, append to existing execution journals, or use gold/model data.

The actual pinned public manifest has 323 unique case IDs: 300 test and 23 dev.
The completion rule requires exactly its test IDs, exactly 300 successful current
preparation records, no duplicate prepared IDs or failures, no case filter, and
no synthetic watermark. Missing or failed cases cannot become exclusions that
permit completion. Each public issue identity and every shared-graph alias is
validated; deduplication does not add independent observations. Strict incomplete
runs save partial reports and raise. The provenance of the supplied public
manifest remains a trusted input, pinned by its byte hash.

## Execution and scientific limits

The spawn entry point and bounded pending queue are Windows compatible. Workers
load their own graphs; only the parent writes results. Scientific aggregation
uses deterministic input order. Worker count is outside scientific identity;
timing/RSS are outside the scientific digest but protected by complete artifact
hashes. V1 sidecars must stay in their original output directory.

Three workers require monitoring available RAM and later-repository peaks.
Existing small-sample timings establish neither a speedup nor a finish time.
An interrupted invocation may leave validated graph artifacts without a final
report; resume under the unchanged identity and require a successful strict run
before claiming all-300 completion. Preparation records arriving after an
invocation starts enter the next resume.

The 17 pytest preparation failures are infrastructure failures pending recovery,
not scientific exclusions. Preserve their historical errors and require current
successful records. CPU deletion/rewiring share requested severities; achieved
severity shortfalls must remain reported. Checker agreement is consistency with
the same lexical extractor, not independent semantic verification or runtime
truth. These diagnostics do not establish model robustness, an accepted pilot,
or protocol freeze. No source/config/current-pilot files were edited, and no full
CPU run or GPU call was launched by this reviewer.
