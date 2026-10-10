"""Pinned public corpus acquisition; evaluator-only answers never enter case records."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from .io import digest, read_json, read_jsonl, write_json, write_jsonl

DATASET = "princeton-nlp/SWE-bench_Lite"


def _sha_file(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def _safe_artifact(root: Path, relative: str) -> Path:
    """Keep cached artifacts inside their root, including on Windows."""
    parts = PurePosixPath(relative).parts
    if (not parts or PurePosixPath(relative).is_absolute() or "\\" in relative
            or any(part in {"..", ".git"} or ":" in part for part in parts)):
        raise ValueError(f"Unsafe artifact path: {relative}")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError(f"Symlink/junction artifact is not allowed: {current}")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Artifact escapes cache directory: {relative}")
    return current


@contextmanager
def _writer_lock(path: Path, timeout: float = 60):
    """One writer per cache key; leave stale locks for explicit inspection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if time.monotonic() - started >= timeout:
                raise TimeoutError(f"Cache writer lock timed out: {path}; inspect the writer or a stale lock before retrying")
            time.sleep(0.1)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"pid": os.getpid()}))
        yield
    finally:
        path.unlink(missing_ok=True)


def download(url: str, destination: Path) -> str:
    """Retry transient transfers from byte zero with a private atomic staging file.

    Incomplete bytes are never appended to a later response or installed as the
    cached artifact. An existing destination is preserved when all attempts fail.
    """
    destination = Path(destination)
    destination = _safe_artifact(destination.parent.resolve(), destination.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "GraphTrust-SWE/0.1 reproducible research"})
    for attempt in range(3):
        temporary = None
        try:
            checksum, transferred = hashlib.sha256(), 0
            with urllib.request.urlopen(request, timeout=120) as response:
                with tempfile.NamedTemporaryFile(mode="wb", prefix=destination.name + ".", suffix=".part",
                                                 dir=destination.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    while block := response.read(1024 * 1024):
                        stream.write(block)
                        checksum.update(block)
                        transferred += len(block)
                    stream.flush()
                    os.fsync(stream.fileno())
                expected = response.headers.get("Content-Length")
                if expected is not None and transferred != int(expected):
                    raise urllib.error.URLError("Incomplete Content-Length response")
            temporary.replace(destination)
            return checksum.hexdigest()
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (urllib.error.URLError, http.client.IncompleteRead, OSError) as exc:
            if attempt == 2:
                raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        time.sleep(0.5 * (attempt + 1))
    raise AssertionError("Unreachable download attempt state")


def is_test_path(path: str) -> bool:
    parts = PurePosixPath(path.lower()).parts
    return any(p in {"test", "tests", "testing", "conftest.py"} or p.startswith("test_") or p.endswith("_test.py") for p in parts)


def patch_files(patch: str) -> list[str]:
    paths = set()
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].split("\t", 1)[0]
            if not is_test_path(path):
                paths.add(path)
    return sorted(paths)


def fetch_corpus(destination: str | Path, revision: str | None = None) -> dict:
    """Read Parquet at an immutable HF commit, not a mutable datasets-server view."""
    destination = Path(destination).resolve()
    with _writer_lock(_safe_artifact(destination, ".graphtrust-fetch.lock")):
        return _fetch_corpus(destination, revision)


def validate_corpus(destination: str | Path, revision: str | None = None) -> dict:
    """Verify the pinned dataset lock and every artifact before cache reuse."""
    destination = Path(destination).resolve()
    existing = read_json(_safe_artifact(destination, "dataset-lock.json"))
    if existing.get("dataset") != DATASET or not re.fullmatch(r"[0-9a-f]{40}", existing.get("revision", "")):
        raise ValueError("Invalid pinned corpus identity")
    if revision is not None and existing["revision"] != revision:
        raise ValueError("Existing dataset has a different revision; use a separate destination")
    if not {"cases.jsonl", "evaluator/gold.jsonl"} <= set(existing.get("files", {})):
        raise ValueError("Corpus lock is missing case/evaluator artifacts")
    for name, expected in existing["files"].items():
        path = _safe_artifact(destination, name)
        if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
                or not path.is_file() or _sha_file(path) != expected):
            raise ValueError(f"Corpus checksum mismatch: {path}")
    return existing


def _fetch_corpus(destination: Path, revision: str | None) -> dict:

    lock = _safe_artifact(destination, "dataset-lock.json")
    if lock.exists():
        return validate_corpus(destination, revision)
    import pyarrow.parquet as parquet
    api = f"https://huggingface.co/api/datasets/{DATASET}" + (f"/revision/{revision}" if revision else "")
    with urllib.request.urlopen(api, timeout=60) as response:
        info = json.load(response)
    revision = info["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Dataset API did not resolve an immutable revision")
    siblings = [row["rfilename"] for row in info["siblings"]]
    all_cases, all_gold, checksums = [], [], {}
    for split in ("dev", "test"):
        filenames = sorted(name for name in siblings if name.endswith(".parquet") and Path(name).name.startswith(split + "-"))
        if not filenames:
            raise ValueError(f"No {split} Parquet files at dataset revision {revision}")
        for name in filenames:
            local = _safe_artifact(destination, "evaluator/raw/" + name)
            checksums[f"evaluator/raw/{name}"] = download(f"https://huggingface.co/datasets/{DATASET}/resolve/{revision}/{name}", local)
            for row in parquet.read_table(local).to_pylist():
                case = {
                    "case_id": row["instance_id"], "repo": row["repo"],
                    "commit": row["base_commit"], "issue_text": row["problem_statement"],
                    "split": split, "dataset_revision": revision,
                }
                all_cases.append(case)
                all_gold.append({"case_id": case["case_id"], "files": patch_files(row["patch"]),
                                 "patch": row["patch"], "test_patch": row["test_patch"],
                                 "FAIL_TO_PASS": row.get("FAIL_TO_PASS"), "PASS_TO_PASS": row.get("PASS_TO_PASS")})
    all_cases.sort(key=lambda row: row["case_id"])
    all_gold.sort(key=lambda row: row["case_id"])
    if len({c["case_id"] for c in all_cases}) != len(all_cases):
        raise ValueError("Dataset contains duplicate instance IDs")
    write_jsonl(_safe_artifact(destination, "cases.jsonl"), all_cases)
    write_jsonl(_safe_artifact(destination, "evaluator/gold.jsonl"), all_gold)
    for name in ("cases.jsonl", "evaluator/gold.jsonl"):
        checksums[name] = hashlib.sha256((destination / name).read_bytes()).hexdigest()
    result = {"dataset": DATASET, "revision": revision, "files": checksums,
              "counts": dict(Counter(c["split"] for c in all_cases)),
              "repositories": {split: dict(Counter(c["repo"] for c in all_cases if c["split"] == split)) for split in ("dev", "test")},
              "status": "acquired_not_protocol_frozen", "license_note": "Preserve upstream dataset and repository licenses; gold is evaluator-only."}
    write_json(lock, result)
    return result


def _selected_source(path: PurePosixPath) -> bool:
    return path.suffix == ".py" or path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE"))


def _archive_files(archive: Path, output: Path | None = None) -> tuple[dict[str, str], list[str]]:
    """Hash selected archive bytes; extraction is explicit and path checked."""
    files, skipped, total_size = {}, [], 0
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            if PurePosixPath(member.name).is_absolute():
                raise ValueError(f"Unsafe archive member: {member.name}")
            parts = PurePosixPath(member.name).parts
            if len(parts) < 2:
                continue
            relative = PurePosixPath(*parts[1:])
            if relative.is_absolute() or any(p in {"..", ".git"} or ":" in p or "\\" in p for p in relative.parts):
                raise ValueError(f"Unsafe archive member: {member.name}")
            if not member.isfile():
                if member.issym() or member.islnk():
                    skipped.append(str(relative))
                continue
            if not _selected_source(relative):
                continue
            if str(relative) in files:
                raise ValueError(f"Duplicate source archive member: {relative}")
            total_size += member.size
            if total_size > 512 * 1024 * 1024 or member.size > 32 * 1024 * 1024:
                raise ValueError("Source archive exceeds extraction limits")
            source = stream.extractfile(member)
            if source is None:
                raise ValueError("Missing regular archive file")
            with source:
                raw = source.read()
            if len(raw) != member.size:
                raise ValueError(f"Truncated source archive member: {relative}")
            files[str(relative)] = hashlib.sha256(raw).hexdigest()
            if output is not None:
                file = _safe_artifact(output, str(relative))
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(raw)
    return dict(sorted(files.items())), sorted(skipped)


def _verify_snapshot(output: Path, marker: Path, archive: Path, repo: str, commit: str) -> None:
    record = read_json(marker)
    if record.get("repo") != repo or record.get("commit") != commit:
        raise ValueError("Snapshot marker repository/commit mismatch")
    if not archive.is_file() or _sha_file(archive) != record.get("archive_sha256"):
        raise ValueError(f"Snapshot archive checksum mismatch: {archive}; preserve the cache before repair")
    expected = record.get("files")
    upgrade = expected is None
    if upgrade:
        # Legacy markers never recorded extracted-byte evidence. Derive it from
        # their original checksum-verified archive, without rewriting source.
        expected, skipped = _archive_files(archive)
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Snapshot marker lacks a nonempty extracted-file manifest")
    for name, checksum in expected.items():
        file = _safe_artifact(output, name)
        if (not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)
                or not file.is_file() or _sha_file(file) != checksum):
            raise ValueError(f"Snapshot source checksum mismatch: {file}; user files were preserved")
    actual = set()
    for directory, dirs, names in os.walk(output, followlinks=False):
        for name in [*dirs, *names]:
            file = Path(directory, name)
            relative = file.relative_to(output).as_posix()
            _safe_artifact(output, relative)
        for name in names:
            file = Path(directory, name)
            relative = file.relative_to(output).as_posix()
            if _selected_source(PurePosixPath(relative)):
                actual.add(relative)
    if actual != set(expected):
        raise ValueError(f"Snapshot selected-file set mismatch: added={sorted(actual - set(expected))}, missing={sorted(set(expected) - actual)}; user files were preserved")
    if upgrade:
        write_json(marker, {**record, "schema_version": 2, "files": expected,
                            "extracted_files": len(expected), "skipped_links": skipped})


def prepare_snapshot(case: dict, cache: str | Path) -> Path:
    """Extract immutable source with per-key writer locking and byte verification.

    Existing source is never reset or deleted. Legacy markers are upgraded only
    after every selected file matches the checksum-verified original archive.
    """
    cache = Path(cache).resolve()
    repo, commit = case["repo"], case["commit"]
    if (not isinstance(repo, str) or not isinstance(commit, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
            or not re.fullmatch(r"[0-9a-f]{40}", commit)):
        raise ValueError("Invalid repository/commit identifier")
    name = repo.replace("/", "__") + "-" + commit
    output = _safe_artifact(cache, "snapshots/" + name)
    archive = _safe_artifact(cache, "archives/" + name + ".tar.gz")
    marker = _safe_artifact(output, ".graphtrust-snapshot.json")
    with _writer_lock(_safe_artifact(cache, "snapshot-locks/" + name + ".lock")):
        # Recheck after acquiring: another worker may have completed this key.
        if marker.exists():
            _verify_snapshot(output, marker, archive, repo, commit)
            return output
        if output.exists():
            raise ValueError(f"Incomplete snapshot {output}; inspect and repair before retrying")
        archive_hash = (_sha_file(archive) if archive.exists()
                        else download(f"https://codeload.github.com/{repo}/tar.gz/{commit}", archive))
        output.mkdir(parents=True)
        files, skipped = _archive_files(archive, output)
        if not files:
            raise ValueError("Source archive contains no Python or license files")
        write_json(marker, {"schema_version": 2, "repo": repo, "commit": commit,
                            "archive_sha256": archive_hash, "files": files,
                            "extracted_files": len(files), "skipped_links": skipped})
    return output


def select_cases(cases: list[dict], qualified: dict[str, dict], protocol: dict, split: str) -> dict:
    repositories = protocol["development_repositories" if split == "dev" else "holdout_repositories"]
    count = protocol["development_per_repository" if split == "dev" else "holdout_per_repository"]
    selected, exclusions, shortfalls = [], [], {}
    for repo in repositories:
        candidates = [c for c in cases if c["split"] == split and c["repo"] == repo]
        candidates.sort(key=lambda c: digest({"seed": protocol["sampling_seed"], "case_id": c["case_id"]}))
        eligible = []
        for case in candidates:
            status = qualified.get(case["case_id"], {})
            if status.get("eligible"):
                eligible.append(case)
            else:
                exclusions.append({"case_id": case["case_id"], "repo": repo, "reason": status.get("reason", "not_prepared")})
        selected.extend(eligible[:count])
        if len(eligible) < count:
            shortfalls[repo] = {"requested": count, "available": len(eligible)}
    return {"cases": selected, "exclusions": exclusions, "shortfalls": shortfalls,
            "selection_hash": digest([c["case_id"] for c in selected]), "uses_gold": False}
