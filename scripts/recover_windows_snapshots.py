"""Verify partial cached snapshots and add only archive-identical missing files.

Standalone infrastructure repair; does not change extraction/scientific code.
Default is a locked, read-only plan. --apply never overwrites existing source.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import tarfile

from graphtrust.corpus import _archive_files, _safe_artifact, _sha_file, _verify_snapshot, _writer_lock
from graphtrust.io import digest, read_json, read_jsonl, write_json
from graphtrust.provenance import implementation_sha256


def extended(path: str | Path) -> Path:
    path = str(Path(path).resolve())
    if os.name == "nt" and not path.startswith("\\\\?\\"):
        path = "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path
    return Path(path)


def inspect_existing(output: Path, expected: dict[str, str]) -> tuple[list[str], list[str]]:
    allowed_dirs = {str(parent) for name in expected for parent in PurePosixPath(name).parents if str(parent) != "."}
    existing = []
    if output.exists():
        for directory, dirs, names in os.walk(output, followlinks=False):
            for name in dirs:
                relative = Path(directory, name).relative_to(output).as_posix()
                _safe_artifact(output, relative)
                if relative not in allowed_dirs:
                    raise ValueError(f"Unexpected directory preserved: {relative}")
            for name in names:
                relative = Path(directory, name).relative_to(output).as_posix()
                file = _safe_artifact(output, relative)
                if relative not in expected:
                    raise ValueError(f"Unexpected file preserved: {relative}")
                if not file.is_file() or _sha_file(file) != expected[relative]:
                    raise ValueError(f"Mismatched existing source preserved: {relative}")
                existing.append(relative)
    return sorted(existing), sorted(set(expected) - set(existing))


def recover(case: dict, cache: Path, apply: bool = False) -> dict:
    repo, commit = case["repo"], case["commit"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid repository or commit")
    name = repo.replace("/", "__") + "-" + commit
    output = _safe_artifact(cache, "snapshots/" + name)
    archive = _safe_artifact(cache, "archives/" + name + ".tar.gz")
    marker = _safe_artifact(output, ".graphtrust-snapshot.json")
    with _writer_lock(_safe_artifact(cache, "snapshot-locks/" + name + ".lock"), timeout=1):
        archive_sha = _sha_file(archive)
        if marker.exists():
            _verify_snapshot(output, marker, archive, repo, commit)
            return {"case_id": case["case_id"], "status": "already_verified", "archive_sha256": archive_sha}
        expected, skipped = _archive_files(archive)
        if not expected:
            raise ValueError("Archive has no selected source/license files")
        existing, missing = inspect_existing(output, expected)
        if _sha_file(archive) != archive_sha:
            raise ValueError("Archive changed during verification")
        result = {"case_id": case["case_id"], "repo": repo, "commit": commit,
                  "snapshot": str(output), "archive_sha256": archive_sha,
                  "existing_files_verified": len(existing), "expected_files": len(expected),
                  "missing_files": missing, "maximum_unprefixed_path_length": max(len(str(output / p).removeprefix("\\\\?\\")) for p in expected),
                  "source_manifest_sha256": digest(expected),
                  "status": "verified_plan", "source_files_overwritten": 0}
        if not apply:
            return result
        output.mkdir(parents=True, exist_ok=True)
        needed = set(missing)
        added = []
        with tarfile.open(archive, "r:gz") as stream:
            for member in stream:
                parts = PurePosixPath(member.name).parts
                if len(parts) < 2:
                    continue
                relative = PurePosixPath(*parts[1:]).as_posix()
                if relative not in needed:
                    continue
                source = stream.extractfile(member)
                if source is None:
                    raise ValueError("Expected regular source member unavailable")
                with source:
                    raw = source.read()
                if len(raw) != member.size or hashlib.sha256(raw).hexdigest() != expected[relative]:
                    raise ValueError("Archive source differs from verified plan")
                file = _safe_artifact(output, relative)
                file.parent.mkdir(parents=True, exist_ok=True)
                with file.open("xb") as destination:
                    destination.write(raw)
                added.append(relative)
        if set(added) != needed or _sha_file(archive) != archive_sha:
            raise ValueError("Archive changed or expected files were not added; original source preserved")
        complete, still_missing = inspect_existing(output, expected)
        if still_missing or len(complete) != len(expected):
            raise ValueError("Recovered snapshot remains incomplete")
        # This is new metadata, not an existing source file. Refuse replacement.
        if marker.exists():
            raise ValueError("Marker appeared unexpectedly; source preserved")
        write_json(marker, {"schema_version": 2, "repo": repo, "commit": commit,
                            "archive_sha256": archive_sha, "files": expected,
                            "extracted_files": len(expected), "skipped_links": skipped})
        _verify_snapshot(output, marker, archive, repo, commit)
        return {**result, "status": "recovered_and_verified", "added_files": added,
                "marker_sha256": _sha_file(marker)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--failed-records", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    evidence = Path(args.evidence)
    if evidence.exists():
        raise ValueError("Use a new evidence directory; prior plans/results are immutable")
    evidence.mkdir(parents=True)
    records = [read_json(p) for p in sorted(Path(args.failed_records).glob("*.json"))]
    selected = {r["case_id"] for r in records if r.get("status") == "error" and r.get("repo") == "pytest-dev/pytest"
                and "FileNotFoundError" in r.get("reason", "")}
    cases = [case for case in read_jsonl(Path(args.data) / "cases.jsonl") if case["case_id"] in selected]
    if len(cases) != len(selected) or not cases:
        raise ValueError("Failed record IDs do not match the canonical corpus")
    cache = extended(Path(args.data) / "cache")
    results = []
    for case in cases:
        try:
            result = recover(case, cache, apply=args.apply)
        except Exception as exc:
            result = {"case_id": case["case_id"], "status": "refused_or_failed", "error": f"{type(exc).__name__}: {exc}"}
        results.append(result)
        write_json(evidence / (case["case_id"] + ".json"), result)
        print(case["case_id"], result["status"], flush=True)
    summary = {"apply": args.apply, "cases": len(cases), "failures": sum(r["status"] == "refused_or_failed" for r in results),
               "implementation_sha256": implementation_sha256(), "script_sha256": _sha_file(Path(__file__)),
               "source_files_overwritten": 0, "results": results}
    write_json(evidence / "SUMMARY.json", summary)
    if summary["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
