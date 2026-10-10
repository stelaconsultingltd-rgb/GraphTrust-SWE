# Windows snapshot recovery

The 17 pytest CPU preparation errors preserved in
`runs/windows-path-recovery-v1/before/cases` are infrastructure failures. This
machine has `LongPathsEnabled=0`; selected upstream fixture paths reach 262
characters beneath the normal cache root. An ordinary long-path write fails
with `FileNotFoundError`, while the same path using `\\?\` succeeds.
`Path.resolve()` preserves that prefix. See the byte-level probe in
`runs/windows-path-recovery-v1/path-probe.json`.

The interrupted extractions have no snapshot marker. Merely changing the next
CLI invocation to an extended path cannot complete them: `prepare_snapshot`
correctly refuses incomplete existing directories. The standalone
`scripts/recover_windows_snapshots.py` verifies the original archive and every
existing selected source byte, refuses unexpected files/directories, symlinks,
junctions or mismatches, and adds only missing archive-identical files using
exclusive creation. It writes a new schema2 marker only after complete
verification, then invokes the package's snapshot verifier. Existing source
files are never overwritten or deleted. The script holds the existing
per-snapshot writer lock; a busy key is refused after one second.

The locked read-only audit completed all 17 partial snapshots without errors:
2237 existing files verified and 1474 missing files identified. Evidence is in
`runs/windows-path-recovery-v1/shared-dry-run/SUMMARY.json`. Three safety tests
pass: missing-only repair, refusal of mismatched source, and refusal of an
unexpected file. A separate fresh-cache preparation of pytest11143 using an
extended path completed successfully, producing schema2 preparation with 6117
nodes and 2279 edges. Its evidence is
`runs/windows-path-recovery-v1/one-case-smoke.json`. These are CPU checks; they
do not establish structural qualification under an exact model tokenizer or
any model finding.

The recovery helper's three tests live beside the standalone script and are
separate from `unittest discover -s tests`. From the checkout root:

```text
python scripts/test_recover_windows_snapshots.py -v
```

The paths above identify private development evidence, not required release
attachments. For independently regenerated preparation failures, first stop the
preparation workers and use a new evidence directory for a read-only plan:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python scripts/recover_windows_snapshots.py --data data/swebench-lite --failed-records runs/cpu-test/cases --evidence runs/windows-recovery-plan
```

The helper selects pytest `FileNotFoundError` records; it is relevant only when
those failures exist. Review the plan and require `failures=0`. Before applying
it, archive the original error records and logs, then rerun with `--apply` and a
different evidence directory. No shared recovery was applied by this audit.
After recovery succeeds and the preparation workers have stopped, this invocation
resumes successful cases and retries errors through extended paths:

```powershell
$graphTrustDataPath = (Resolve-Path -LiteralPath (Join-Path (Get-Location) 'data/swebench-lite')).ProviderPath
$extendedData = '\\?\' + $graphTrustDataPath
if ($graphTrustDataPath.StartsWith('\\')) { $extendedData = '\\?\UNC\' + $graphTrustDataPath.Substring(2) }
.\.venv\Scripts\python.exe -m graphtrust prepare --data $extendedData --out runs/cpu-test --split test --workers 3
```

There is no `--retry-errors` switch: the implementation only reuses matching
successful records. That resumed command replaces the current error JSON
records, whose original bytes are already saved under `before/cases`. To keep
the original output directory entirely untouched, instead use a new output
such as `runs/cpu-test-recovery-v1`; that performs preparation for all 300 test
cases. Neither approach should be started against the current output while
its preparation workers are active. Do not treat path errors as structural
benchmark exclusions.

No Python package source, protocol, tokenizer configuration, wheel, original
archive, existing source file or live root process was changed by this audit.
The package implementation fingerprint remains
`bc084db6c4922dda6c05ed69e8709103e3db659526352596d8db28538d0697ae`.
