# Independent Windows snapshot recovery review

Reviewed 10 October 2026. No substantive blocker to applying the existing
17-case plan was found. The reviewed standalone script SHA-256 is
`450552ff9273c4e0dd9d93f5752f0d1cf38c363c24d726e29806bb58bad41679`.
The reviewer applied no repair and acquired no shared cache locks.

Fresh registry inspection found `LongPathsEnabled=0`. Preserved evidence shows
an ordinary 295-character path failing and the extended Windows path succeeding
while retaining its prefix. This supports an infrastructure remedy without
changing extraction, source-packing, protocol, or scientific eligibility rules.

## Independent verification

`python -B -m unittest discover -s scripts -p test_recover_windows_snapshots.py
-v` passed all three safety tests in 0.107 seconds, exit 0. They establish
missing-only creation, preservation of an existing file's timestamp and bytes,
complete-marker acceptance by the ordinary verifier, and refusal before writes
when existing bytes or extra files disagree with the archive.

The read-only `runs/scientific-review/verify_windows_recovery.py` independently
rehashed all 17 archives and their partial snapshots. It exactly reproduced the
saved plan: 2,237 existing matching files, 1,474 missing files, zero discrepancies,
and no completion markers. All original error records match the preserved probe
hashes. The real isolated pytest-11143 smoke has a valid complete source manifest
and archive hash, with its saved graph containing 6,117 nodes and 2,279 edges.
Package, extractor, protocol, recovery-script, and live CPU-script identities
were unchanged before/after verification. Evidence is in
`runs/scientific-review/windows-recovery-evidence.json` and the accompanying
verification/test logs. No evaluator answers or model data were read.

## Guards and remaining operational limits

Recovery validates repository/commit identifiers and confines archives,
snapshots, files, and locks through the existing path guard, which rejects
traversal, symlinks, and junctions. Archive inspection rejects duplicate selected
members, unsafe paths, selected files above 32 MiB, and selected totals above
512 MiB. Existing files and directories must belong to the expected manifest;
existing source bytes must match before any apply write.

The repair takes the same per-snapshot writer lock as ordinary preparation.
Only missing archive-identical files are opened with exclusive `xb` creation;
existing source is never overwritten. Archive hashes are checked across planning
and extraction, added bytes are checked against the expected hashes, and a
complete second source verification precedes the new marker. The ordinary
snapshot verifier then checks marker identity and every selected file.

The script does not overwrite preparation error records or read gold. Preserve
`runs/windows-path-recovery-v1/before` and use a new evidence directory for apply.
The root owns shared mutation and should retry the 17 preparations through the
extended data prefix after its active preparation process finishes. All 300
current successful records and strict CPU completion remain required; platform
failures are not structural exclusions. If a crash leaves a partially written
new file, subsequent recovery refuses its mismatched bytes for explicit
inspection rather than silently replacing it. Do not claim all-300 recovery or
CPU completion from this review or the one-case smoke.
