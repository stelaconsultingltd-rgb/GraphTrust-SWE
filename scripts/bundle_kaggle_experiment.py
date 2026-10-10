"""Build (never launch) frozen, resumable Kaggle experiment batches.

Stdlib builder and supervisor. The generated script embeds this same file and
an allowlisted archive, while model weights and any CUDA GGUF wheel remain
separate Kaggle attachments. It cannot accept an unfinished development pilot.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import time
import zipfile

BUNDLE_BASE64 = None
BUNDLE_METADATA = None
CONDITIONS = ["source_only", "clean", "deleted", "rewired", "clean_checked", "rewired_checked"]
GGUF_COMMIT = "1652066e0af45f2313b339670ef9555e8a54e545"
LLAMA_COMMIT = "0c1e57098bba43ac29e6e3b677cdceebdd22334f"
RESPONSE_CONTRACT_VERSION = "files_citations_v2"
RECORD_SCHEMA_VERSION = "2.0"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf8")).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def read_jsonl(path):
    if not Path(path).exists():
        return []
    raw = Path(path).read_text(encoding="utf8")
    if raw and not raw.endswith("\n"):
        raise ValueError(f"Unterminated JSONL at {path}; preserve and recover explicitly")
    rows = []
    for number, line in enumerate(raw.splitlines(), 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("record is not an object")
            rows.append(row)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid JSONL at {path}:{number}; preserve and recover explicitly") from exc
    return rows


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf8", newline="\n") as handle:
        handle.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def generation(protocol):
    return {"max_output_tokens": protocol["max_output_tokens"],
        "temperature": protocol["temperature"], "thinking": False,
        "timeout_seconds": protocol["timeout_seconds"]}


def schedule(contexts, seeds, model_name, backend, protocol):
    result = {}
    for row in contexts:
        for seed in seeds:
            key = {"context_sha256": row["context_sha256"], "case_id": row["case_id"],
                "condition": row["condition"], "model_name": model_name,
                "backend": backend, "seed": seed, "generation": generation(protocol),
                "response_contract_version": RESPONSE_CONTRACT_VERSION}
            run_id = digest(key)
            if run_id in result:
                raise ValueError("Duplicate scheduled arm/seed")
            result[run_id] = {**key, "repo": row["repo"], "source_sha256": row["source_sha256"],
                "input_tokens": row["input_tokens"], "schema_version": RECORD_SCHEMA_VERSION}
    return result


def validate_history(records, starts, expected):
    """Reject foreign or repeated attempts, including failures; never filter them."""
    indexed = []
    for rows, is_start in ((records, False), (starts, True)):
        seen = {}
        for row in rows:
            run_id = row.get("run_id")
            key = expected.get(run_id)
            if key is None or run_id in seen:
                raise ValueError("Foreign or duplicate run ID in retained history")
            if row.get("synthetic") is not False:
                raise ValueError("Synthetic or unidentified record cannot enter a real experiment")
            for name, value in key.items():
                if row.get(name) != value:
                    raise ValueError(f"Retained {name} differs from the accepted schedule")
            if is_start and row.get("status") != "started":
                raise ValueError("Attempt journal must contain only starts")
            if not is_start and row.get("status") not in {"ok", "invalid_prediction", "parse_error", "error", "timeout", "interrupted"}:
                raise ValueError("Unknown terminal status")
            seen[run_id] = row
        indexed.append(seen)
    terminal, journal = indexed
    if not set(terminal) <= set(journal):
        raise ValueError("Every terminal record requires its original attempt journal")
    return terminal, journal


def finalize_interrupted(records_path, expected):
    journal_path = Path(str(records_path) + ".attempts.jsonl")
    terminal, journal = validate_history(read_jsonl(records_path), read_jsonl(journal_path), expected)
    Path(records_path).parent.mkdir(parents=True, exist_ok=True)
    journal_path.touch(exist_ok=True)
    with Path(records_path).open("a", encoding="utf8", newline="\n") as handle:
        for run_id, start in journal.items():
            if run_id not in terminal:
                row = {**start, "status": "interrupted", "error_kind": "process_interruption",
                    "error": "Worker ended without terminal record; automatic retry is disabled",
                    "latency_seconds": None}
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                terminal[run_id] = row
    return terminal, journal


def declared_primary_counts(manifest, protocol):
    """Current selection API reports requested/available deficits per repository."""
    deficits = manifest.get("shortfalls")
    if not isinstance(deficits, dict) or set(deficits) - set(protocol["holdout_repositories"]):
        raise ValueError("Invalid declared cohort shortfalls")
    counts = {}
    for repo in protocol["holdout_repositories"]:
        count = protocol["holdout_per_repository"]
        if repo in deficits:
            deficit = deficits[repo]
            if (not isinstance(deficit, dict) or deficit.get("requested") != count
                    or type(deficit.get("available")) is not int or not 0 <= deficit["available"] < count):
                raise ValueError("Shortfalls require exact requested/available structural counts")
            count = deficit["available"]
        counts[repo] = count
    return counts


def validate_inputs(contexts, manifest, protocol, frozen, backend, primary_manifest=None, runtime_lock=None):
    if (protocol.get("schema_version") != 2 or protocol.get("response_contract_version") != RESPONSE_CONTRACT_VERSION
            or manifest.get("schema_version") != 2 or manifest.get("response_contract_version") != RESPONSE_CONTRACT_VERSION
            or frozen.get("schema_version") != 2 or frozen.get("response_contract_version") != RESPONSE_CONTRACT_VERSION
            or any(row.get("response_contract_version") != RESPONSE_CONTRACT_VERSION for row in contexts)):
        raise ValueError("Fresh response-contract v2 inputs and accepted pilot freeze are required")
    stage = manifest.get("stage")
    if stage not in {"holdout", "replication"} or manifest.get("token_method") != "tokenizer":
        raise ValueError("Only exact-tokenizer holdout or replication contexts are supported")
    if (frozen.get("status") != "frozen" or frozen.get("protocol") != protocol
            or frozen.get("protocol_sha256") != digest(protocol)
            or not frozen.get("pilot_manifest_sha256") or not frozen.get("pilot_records_sha256")):
        raise ValueError("An accepted scientific freeze from the complete real pilot is required")
    if (frozen.get("parse_rate", 0) < protocol["pilot_minimum_parse_rate"]
            or frozen.get("graph_citation_rate", 0) < protocol["pilot_minimum_graph_citation_rate"]):
        raise ValueError("Accepted freeze does not pass the pilot gates")
    if protocol.get("conditions") != CONDITIONS or protocol.get("sampling_seeds_primary") != [17, 42] or protocol.get("sampling_seeds_replication") != [17]:
        raise ValueError("Expected the preregistered six conditions and two/one sampling seeds")
    if not (0 < protocol["max_input_tokens"] <= 4000 and 0 < protocol["max_output_tokens"] <= 256
            and 0 < protocol["timeout_seconds"] <= 90 and math.isfinite(protocol["temperature"])):
        raise ValueError("Token or elapsed budgets exceed the approved protocol limits")
    if manifest.get("protocol_sha256") != digest(protocol) or manifest.get("contexts_sha256") != digest(contexts):
        raise ValueError("Exact context/protocol checksum mismatch")
    if manifest.get("implementation_sha256") != frozen.get("implementation_sha256") or not frozen.get("implementation_sha256"):
        raise ValueError("Context implementation differs from the accepted freeze")
    if manifest.get("selection_uses_gold") is not False:
        raise ValueError("Gold-independent cohort selection is required")
    for name in ("source_pack_rule", "model_edge_rule"):
        if manifest.get(name) != protocol.get(name):
            raise ValueError(f"Context {name} differs from the accepted protocol")
    if backend.get("name") not in {"transformers", "llama_cpp"} or backend.get("enable_thinking") is not False:
        raise ValueError("An identified real backend with thinking disabled is required")
    if not (backend.get("checkpoint_sha256") or backend.get("model_sha256")):
        raise ValueError("Backend must have an immutable local checkpoint identity")
    if backend.get("tokenizer_sha256") != manifest.get("tokenizer_identity"):
        raise ValueError("Backend and prepared tokenizer identities differ")
    if stage == "holdout" and (digest(backend) != frozen.get("backend_sha256")
            or manifest.get("tokenizer_identity") != frozen.get("tokenizer_identity")):
        raise ValueError("Primary backend must exactly match the accepted development pilot")
    if backend["name"] == "llama_cpp":
        validate_replication_lock(runtime_lock, backend)
    seeds = [17, 42] if stage == "holdout" else [17]
    if protocol.get("holdout_per_repository") != 10 or protocol.get("replication_per_repository") != 5 or len(protocol["holdout_repositories"]) != 6:
        raise ValueError("This tooling implements the approved 720/180 schedule")
    if manifest.get("sampling_seeds") != seeds:
        raise ValueError("Sampling seeds differ from the exact context manifest")
    if stage == "holdout":
        required_counts = declared_primary_counts(manifest, protocol)
        primary_counts = None
    else:
        if (not primary_manifest or primary_manifest.get("stage") != "holdout"
                or primary_manifest.get("protocol_sha256") != digest(protocol)
                or primary_manifest.get("implementation_sha256") != frozen["implementation_sha256"]
                or primary_manifest.get("selection_uses_gold") is not False
                or primary_manifest.get("selection_sha256") != digest(primary_manifest.get("case_ids"))):
            raise ValueError("Replication requires the exact primary holdout selection manifest")
        primary_counts = declared_primary_counts(primary_manifest, protocol)
        primary_ids = primary_manifest.get("case_ids", [])
        if (len(primary_ids) != sum(primary_counts.values()) or len(set(primary_ids)) != len(primary_ids)
                or primary_manifest.get("cases") != len(primary_ids)
                or primary_manifest.get("contexts") != len(primary_ids) * 6
                or primary_manifest.get("sampling_seeds") != [17, 42]
                or primary_manifest.get("token_method") != "tokenizer"):
            raise ValueError("Primary manifest does not describe its complete declared cohort")
        required_counts = {repo: min(5, count) for repo, count in primary_counts.items()}
        # create_contexts currently records qualification-population deficits
        # against ten even for replication. Preserve them, but never confuse
        # that population with the fixed five-or-fewer primary subset.
        available = declared_primary_counts(manifest, protocol)
        if any(available[repo] < required_counts[repo] for repo in required_counts):
            raise ValueError("Replication qualification cannot cover its fixed primary subset")
    issues = sum(required_counts.values())
    if not issues:
        raise ValueError("No qualifying issues: report the empty cohort without launching GPU inference")
    groups = defaultdict(list)
    forbidden = {"patch", "test_patch", "gold", "gold_files", "reference_files", "FAIL_TO_PASS", "PASS_TO_PASS"}
    for row in contexts:
        if forbidden & set(row) or any(marker in row.get("prompt", "") for marker in ("known_false_edge_ids", "test_patch", '"patch":')):
            raise ValueError("Evaluator-only fields or prompt markers detected")
        if (row.get("token_method") != "tokenizer" or type(row.get("input_tokens")) is not int
                or not 0 < row["input_tokens"] <= protocol["max_input_tokens"]):
            raise ValueError("Every prompt requires valid exact tokenizer accounting")
        if hashlib.sha256(row["prompt"].encode()).hexdigest() != row.get("context_sha256"):
            raise ValueError("Prompt checksum mismatch")
        try:
            source = row["prompt"].split("SOURCE PACK\n", 1)[1].split("END SOURCE PACK\n", 1)[0]
        except IndexError as exc:
            raise ValueError("Missing immutable source section") from exc
        if hashlib.sha256(source.encode()).hexdigest() != row.get("source_sha256"):
            raise ValueError("Source checksum mismatch")
        groups[row["case_id"]].append(row)
    counts = Counter()
    for case_id, rows in groups.items():
        if sorted(r["condition"] for r in rows) != sorted(CONDITIONS) or len({r["source_sha256"] for r in rows}) != 1 or len({r["repo"] for r in rows}) != 1:
            raise ValueError(f"Missing arms or changed source/repository for {case_id}")
        counts[rows[0]["repo"]] += 1
    if counts != Counter({repo: count for repo, count in required_counts.items() if count}):
        raise ValueError("Repository cohort differs from its declared structural shortfalls")
    ids = manifest.get("case_ids", [])
    if (len(ids) != issues or len(set(ids)) != issues or set(ids) != set(groups)
            or manifest.get("selection_sha256") != digest(ids)
            or manifest.get("cases") != issues or manifest.get("contexts") != issues * 6 or len(contexts) != issues * 6):
        raise ValueError("Selection manifest differs from the complete contexts")
    ordered_repos = [groups[identity][0]["repo"] for identity in ids]
    if ordered_repos != [repo for repo in protocol["holdout_repositories"] for _ in range(required_counts[repo])]:
        raise ValueError("Selection must preserve the current repository-grouped API order")
    if [row["case_id"] for row in contexts] != [identity for identity in ids for _ in CONDITIONS]:
        raise ValueError("Context order differs from the exact selection manifest")
    if stage == "replication":
        # Primary case_ids are repository-grouped by the current selection API.
        expected_ids, offset = [], 0
        for repo in protocol["holdout_repositories"]:
            expected_ids.extend(primary_ids[offset:offset + required_counts[repo]])
            offset += primary_counts[repo]
        if ids != expected_ids:
            raise ValueError("Replication must retain the fixed first five cases per primary repository")
        if backend["name"] != "llama_cpp":
            raise ValueError("The preregistered replication uses its separately accepted GGUF runtime")
    return seeds


def validate_replication_lock(lock, backend):
    if not lock or lock.get("status") != "development_runtime_accepted" or lock.get("build_and_runtime_tested") is not True:
        raise ValueError("GGUF runtime remains untested; an accepted development smoke lock is required")
    if backend.get("name") != "llama_cpp" or lock.get("backend_sha256") != digest(backend):
        raise ValueError("Replication backend differs from the accepted GGUF development runtime")
    if (lock.get("llama_cpp_python_commit") != GGUF_COMMIT or lock.get("vendored_llama_cpp_commit") != LLAMA_COMMIT
            or lock.get("llama_cpp_python_version") != "0.3.36" or lock.get("cuda_cmake_args") != "-DGGML_CUDA=on"
            or lock.get("jinja2_version") != "3.1.6" or lock.get("model_sha256") != backend.get("model_sha256")):
        raise ValueError("Replication build/checkpoint differs from the documented pinned runtime")
    for name in ("built_wheel_sha256", "development_records_sha256", "build_log_sha256", "environment_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(lock.get(name, ""))):
            raise ValueError(f"Missing real GGUF development evidence: {name}")
    if not str(lock.get("wheel_path", "")).startswith("/kaggle/input/"):
        raise ValueError("Exact prebuilt CUDA wheel must be a separate Kaggle attachment")


def validate_policy(stage, policy):
    max_hours, max_sessions = (24, 8) if stage == "holdout" else (6, 2)
    for name in ("session_seconds", "stage_seconds", "free_quota_seconds", "max_sessions", "batch_max_calls"):
        if type(policy.get(name)) is not int or policy[name] <= 0:
            raise ValueError(f"Explicit positive integer {name} is required")
    if policy.get("free_t4_only") is not True:
        raise ValueError("Only the approved free T4 execution policy is supported")
    if (policy["session_seconds"] > 10800 or policy["stage_seconds"] > max_hours * 3600
            or policy["free_quota_seconds"] > max_hours * 3600 or policy["max_sessions"] > max_sessions
            or policy["batch_max_calls"] > (720 if stage == "holdout" else 180)
            or policy["session_seconds"] > min(policy["stage_seconds"], policy["free_quota_seconds"])):
        raise ValueError("Execution policy exceeds the approved stage/session/quota limits")


def history_bytes(records_path):
    if records_path is None:
        return {"records": b"", "journal": b""}
    records_path = Path(records_path)
    paths = {"records": records_path, "journal": Path(str(records_path) + ".attempts.jsonl")}
    return {name: path.read_bytes() if path.exists() else b"" for name, path in paths.items()}


def history_snapshot(records_path):
    return {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "rows": raw.count(b"\n")}
        for name, raw in history_bytes(records_path).items()}


def validate_ledger_history(ledger, records_path, expected):
    """Every reservation anchors exact history prefixes, including crash resumes."""
    if records_path is None:
        terminal, journal = {}, {}
    else:
        terminal, journal = validate_history(read_jsonl(records_path),
            read_jsonl(Path(str(records_path) + ".attempts.jsonl")), expected)
    raw_history = history_bytes(records_path)
    if not ledger:
        if terminal or journal:
            raise ValueError("Existing history has no verifiable reservation ledger")
        return terminal, journal
    if ledger.get("schema_version") != 2:
        raise ValueError("Legacy ledger lacks pinned history prefixes; preserve artifacts and recover explicitly")
    sessions = ledger.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("Existing ledger has no session history anchors")
    previous = {name: 0 for name in raw_history}
    for index, session in enumerate(sessions):
        if session.get("status") not in {"reserved", "finished", "error", "budget_stop"}:
            raise ValueError("Invalid ledger session status")
        snapshots = [("history_before", session.get("history_before"))]
        if session["status"] != "reserved":
            snapshots.append(("history_after", session.get("history_after")))
        for label, snapshot in snapshots:
            if not isinstance(snapshot, dict) or set(snapshot) != set(raw_history):
                raise ValueError("Session lacks verifiable pinned history prefixes")
            for name, raw in raw_history.items():
                pin = snapshot[name]
                if (not isinstance(pin, dict) or type(pin.get("bytes")) is not int or pin["bytes"] < previous[name]
                        or type(pin.get("rows")) is not int or pin["rows"] < 0
                        or not re.fullmatch(r"[0-9a-f]{64}", str(pin.get("sha256", "")))):
                    raise ValueError("Invalid or nonmonotonic pinned history prefix")
                prefix = raw[:pin["bytes"]]
                if (len(prefix) != pin["bytes"] or hashlib.sha256(prefix).hexdigest() != pin["sha256"]
                        or prefix.count(b"\n") != pin["rows"] or (prefix and not prefix.endswith(b"\n"))):
                    raise ValueError("Retained history differs from a pinned session prefix")
                previous[name] = pin["bytes"]
                if index == len(sessions) - 1 and label == "history_after" and len(raw) != pin["bytes"]:
                    raise ValueError("Finalized history has an unreserved extension")
    last = sessions[-1]
    if last["status"] == "reserved":
        new_starts = len(journal) - last["history_before"]["journal"]["rows"]
        if new_starts < 0 or new_starts > ledger["policy"]["batch_max_calls"]:
            raise ValueError("Crashed session extension exceeds its new-attempt cap")
    elif set(terminal) != set(journal):
        raise ValueError("Finalized session has an uncompleted start; recover explicitly")
    return terminal, journal


def reserve_session(ledger, experiment, policy, records_path=None, expected=None):
    ledger = json.loads(json.dumps(ledger))
    if not ledger:
        ledger = {"schema_version": 2, "experiment_sha256": experiment, "policy": policy, "sessions": []}
    if ledger.get("experiment_sha256") != experiment or ledger.get("policy") != policy:
        raise ValueError("Resume ledger belongs to a different experiment or quota policy")
    sessions = ledger.get("sessions")
    if not isinstance(sessions, list) or any(s.get("reservation_seconds") != policy["session_seconds"] or s.get("session") != i + 1 or s.get("status") not in {"reserved", "finished", "error", "budget_stop"} for i, s in enumerate(sessions)):
        raise ValueError("Invalid prior session reservations")
    if sessions:
        validate_ledger_history(ledger, records_path, expected)
    else:
        validate_ledger_history({}, records_path, expected)
    reserved = sum(s["reservation_seconds"] for s in sessions)
    if len(sessions) >= policy["max_sessions"] or reserved + policy["session_seconds"] > min(policy["stage_seconds"], policy["free_quota_seconds"]):
        raise ValueError("Session or stage/free-quota reservation exhausted")
    sessions.append({"session": len(sessions) + 1, "status": "reserved",
        "reservation_seconds": policy["session_seconds"], "started_at": datetime.now(timezone.utc).isoformat(),
        "history_before": history_snapshot(records_path)})
    return ledger


def recover_history(ledger, records_path, expected):
    """Verify first, finalize orphan starts, then seal a crashed reservation."""
    validate_ledger_history(ledger, records_path, expected)
    terminal, journal = finalize_interrupted(records_path, expected)
    ledger = json.loads(json.dumps(ledger))
    if ledger and ledger["sessions"][-1]["status"] == "reserved":
        ledger["sessions"][-1].update(status="error", recovery_kind="reserved_session_crash",
            history_after=history_snapshot(records_path), records_sha256=file_hash(records_path),
            journal_sha256=file_hash(Path(str(records_path) + ".attempts.jsonl")))
    return ledger, terminal, journal


def wheel_implementation(wheel):
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate package wheel members")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not (name.startswith("graphtrust/") or re.match(r"graphtrust_swe-[^/]+\.dist-info/", name)):
                raise ValueError("Unexpected release wheel content")
            if (set(path.parts) & {"evaluator", "tests", "models"}) or path.suffix.lower() in {".gguf", ".safetensors", ".bin", ".pt", ".pth", ".parquet"}:
                raise ValueError("Evaluator/test/model assets must not enter the release wheel")
        return digest([{"path": name.removeprefix("graphtrust/"), "sha256": hashlib.sha256(archive.read(name)).hexdigest()}
            for name in sorted(names) if name.startswith("graphtrust/") and name.endswith(".py")])


def build_bundle(wheel, contexts, manifest, protocol, freeze, backend_identity, output, policy,
                 primary_manifest=None, runtime_lock=None, resume=None):
    paths = {"contexts/contexts.jsonl": Path(contexts), "contexts/manifest.json": Path(manifest),
        "protocol.json": Path(protocol), "accepted-freeze.json": Path(freeze), "accepted-backend.json": Path(backend_identity)}
    rows, metadata, settings, frozen, backend = read_jsonl(contexts), read_json(manifest), read_json(protocol), read_json(freeze), read_json(backend_identity)
    primary = read_json(primary_manifest) if primary_manifest else None
    lock = read_json(runtime_lock) if runtime_lock else None
    seeds = validate_inputs(rows, metadata, settings, frozen, backend, primary, lock)
    validate_policy(metadata["stage"], policy)
    if wheel_implementation(wheel) != metadata["implementation_sha256"]:
        raise ValueError("Release wheel implementation differs from the frozen contexts")
    if not re.fullmatch(r"graphtrust_swe-[A-Za-z0-9_.-]+\.whl", Path(wheel).name):
        raise ValueError("Supply the exact GraphTrust-SWE release wheel")
    if not str(backend.get("model_path", "")).startswith("/kaggle/input/"):
        raise ValueError("Accepted backend model path must refer to a separate Kaggle attachment")
    model_name = frozen["primary_model"] if metadata["stage"] == "holdout" else "google/gemma-4-E4B-it-QAT-Q4_0@sha256:" + backend["model_sha256"]
    expected = schedule(rows, seeds, model_name, backend, settings)
    experiment = digest({"stage": metadata["stage"], "freeze_sha256": digest(frozen),
        "contexts_sha256": metadata["contexts_sha256"], "backend_sha256": digest(backend),
        "schedule_sha256": digest(sorted(expected))})
    if primary_manifest:
        paths["primary-manifest.json"] = Path(primary_manifest)
    if runtime_lock:
        paths["accepted-replication-runtime.json"] = Path(runtime_lock)
    if resume:
        resume = Path(resume)
        for name in ("records.jsonl", "records.jsonl.attempts.jsonl", "session-ledger.json"):
            if not (resume / name).is_file():
                raise ValueError(f"Resume requires the complete retained {name}")
            paths["resume/" + name] = resume / name
        prior_ledger = read_json(resume / "session-ledger.json")
        reserve_session(prior_ledger, experiment, policy, resume / "records.jsonl", expected)
    else:
        reserve_session({}, experiment, policy)
    wheel_name = "package/" + Path(wheel).name
    paths[wheel_name] = Path(wheel)
    assets = {name: path.read_bytes() for name, path in paths.items()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(assets.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    payload = buffer.getvalue()
    template = Path(__file__).read_text(encoding="utf8")
    bundle_metadata = {"schema_version": 1, "purpose": "frozen_experiment_batch_not_submission",
        "experiment_sha256": experiment, "stage": metadata["stage"], "model_name": model_name,
        "seeds": seeds, "schedule_attempts": len(expected), "nominal_attempts": 720 if metadata["stage"] == "holdout" else 180,
        "actual_issues": metadata["cases"], "declared_shortfalls": metadata["shortfalls"],
        "primary_shortfalls": primary["shortfalls"] if primary else metadata["shortfalls"], "policy": policy,
        "wheel_archive_path": wheel_name, "builder_sha256": hashlib.sha256(template.encode()).hexdigest(),
        "bundle_sha256": hashlib.sha256(payload).hexdigest(), "contains_evaluator_gold": False,
        "files": {name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()} for name, content in sorted(assets.items())}}
    script = template.replace("BUNDLE_BASE64 = None\n", "BUNDLE_BASE64 = " + repr(base64.b64encode(payload).decode("ascii")) + "\n", 1)
    script = script.replace("BUNDLE_METADATA = None\n", "BUNDLE_METADATA = " + repr(bundle_metadata) + "\n", 1)
    compile(script, str(output), "exec")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("Use a new bundle output path; existing scripts are immutable evidence")
    output.write_text(script, encoding="utf8", newline="\n")
    save(output.with_suffix(".manifest.json"), {**bundle_metadata, "script_sha256": hashlib.sha256(script.encode()).hexdigest()})
    return bundle_metadata


def extract_bundle(root):
    payload = base64.b64decode(BUNDLE_BASE64, validate=True)
    if hashlib.sha256(payload).hexdigest() != BUNDLE_METADATA["bundle_sha256"]:
        raise ValueError("Embedded archive checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(BUNDLE_METADATA["files"]):
            raise ValueError("Embedded archive member inventory differs")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Unsafe embedded archive path")
            content = archive.read(name)
            meta = BUNDLE_METADATA["files"][name]
            if len(content) != meta["bytes"] or hashlib.sha256(content).hexdigest() != meta["sha256"]:
                raise ValueError("Embedded asset checksum mismatch")
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != content:
                raise ValueError("Refusing to overwrite changed extracted evidence")
            destination.write_bytes(content)


def load_experiment(root):
    rows, manifest = read_jsonl(root / "contexts/contexts.jsonl"), read_json(root / "contexts/manifest.json")
    protocol, frozen, backend = read_json(root / "protocol.json"), read_json(root / "accepted-freeze.json"), read_json(root / "accepted-backend.json")
    primary = read_json(root / "primary-manifest.json") if (root / "primary-manifest.json").exists() else None
    lock = read_json(root / "accepted-replication-runtime.json") if (root / "accepted-replication-runtime.json").exists() else None
    seeds = validate_inputs(rows, manifest, protocol, frozen, backend, primary, lock)
    return rows, manifest, protocol, frozen, backend, seeds, lock


def check_backend_preflight(backend, rows, manifest, protocol, accepted, output):
    # These files must exist even when the very next identity/count guard fails.
    save(output / "actual-backend.json", backend.identity)
    if backend.identity.get("local_checkpoint"):
        save(output / "actual-checkpoint-manifest.json", backend.identity["local_checkpoint"])
    if digest(backend.identity) != digest(accepted):
        raise ValueError("Actual backend differs from the accepted runtime; no inference permitted")
    if backend.identity.get("tokenizer_sha256") != manifest["tokenizer_identity"]:
        raise ValueError("Actual tokenizer differs from immutable context preparation")
    measured = []
    for row in rows:
        count = backend.count_tokens(row["prompt"])
        measured.append({"case_id": row["case_id"], "condition": row["condition"], "stored": row["input_tokens"], "actual": count})
        if count != row["input_tokens"] or count > protocol["max_input_tokens"]:
            save(output / "token-count-preflight.json", {"status": "mismatch", "counts": measured})
            raise ValueError("Actual exact token counts differ from immutable contexts")
        if hasattr(backend, "validate_context"):
            backend.validate_context(row["prompt"], protocol["max_output_tokens"])
    save(output / "token-count-preflight.json", {"status": "matched", "counts": measured})


def worker_main(root, output, max_calls):
    rows, manifest, protocol, frozen, accepted, seeds, lock = load_experiment(root)
    expected = schedule(rows, seeds, BUNDLE_METADATA["model_name"], accepted, protocol)
    validate_ledger_history(read_json(output / "session-ledger.json"), output / "records.jsonl", expected)
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", str(root / BUNDLE_METADATA["wheel_archive_path"])], check=True)
    if accepted["name"] == "transformers":
        subprocess.run([sys.executable, "-m", "pip", "install", "transformers==5.19.0", "accelerate==1.10.1", "Jinja2==3.1.6"], check=True)
    else:
        runtime_wheel = Path(lock["wheel_path"])
        if file_hash(runtime_wheel) != lock["built_wheel_sha256"]:
            raise ValueError("Separately attached GGUF CUDA wheel checksum mismatch")
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", str(runtime_wheel)], check=True)
        if importlib.metadata.version("llama-cpp-python") != "0.3.36" or importlib.metadata.version("Jinja2") != "3.1.6":
            raise ValueError("GGUF runtime package/template dependency versions differ from the accepted build")
    # Do not use global `pip check`: unrelated preinstalled Kaggle packages may
    # conflict without affecting this runtime. Import/load and exact identity
    # gates below validate the dependencies actually used by the experiment.
    environment = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], capture_output=True, text=True, check=True)
    (output / "environment.txt").write_text(environment.stdout, encoding="utf8")
    hardware = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], capture_output=True, text=True, check=True)
    save(output / "hardware.json", {"nvidia_smi": hardware.stdout, "free_t4_only": True,
        "billing_mode": "externally_verified_free_quota_reservation"})
    names = [line.split(",", 1)[0] for line in hardware.stdout.splitlines() if line.strip()]
    if not names or any("T4" not in name for name in names):
        raise ValueError("Actual hardware must consist exclusively of free-policy T4 devices")
    from graphtrust.provenance import implementation_sha256
    from graphtrust.inference import TransformersBackend, LlamaCppBackend, checkpoint_manifest, run_contexts
    if implementation_sha256() != frozen["implementation_sha256"]:
        raise ValueError("Installed implementation differs from scientific freeze")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    model = Path(accepted["model_path"])
    if not model.exists() or not str(model.resolve()).startswith("/kaggle/input/"):
        raise ValueError("Exact accepted official model attachment is absent")
    if accepted["name"] == "transformers":
        checkpoint = checkpoint_manifest(model)
        save(output / "actual-checkpoint-manifest.json", checkpoint)
        backend = TransformersBackend(str(model), revision=accepted.get("requested_revision"), local_files_only=True)
    else:
        save(output / "actual-checkpoint-manifest.json", {"path": str(model), "bytes": model.stat().st_size, "sha256": file_hash(model)})
        backend = LlamaCppBackend(str(model), n_ctx=accepted["n_ctx"], n_gpu_layers=accepted["n_gpu_layers"], n_threads=accepted["n_threads"])
    check_backend_preflight(backend, rows, manifest, protocol, accepted, output)
    _, starts = validate_ledger_history(read_json(output / "session-ledger.json"), output / "records.jsonl", expected)
    remaining = len(expected) - len(starts)
    result = run_contexts(rows, output / "records.jsonl", backend, seeds, BUNDLE_METADATA["model_name"],
        max_output_tokens=protocol["max_output_tokens"], timeout_seconds=protocol["timeout_seconds"],
        temperature=protocol["temperature"], max_calls=min(max_calls, remaining))
    save(output / "batch-result.json", result)


def stop_worker(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def runtime_main():
    if os.name != "posix" or not Path("/kaggle/working").is_dir():
        raise RuntimeError("Generated experiment script runs only in a Kaggle Linux session")
    started = time.monotonic()
    root = Path("/kaggle/working/graphtrust-bundle")
    output = Path("/kaggle/working/graphtrust-experiment")
    output.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output / ".single-writer.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    process, session_output, expected, ledger = None, None, None, None
    history_validated = False
    status = {"status": "preflight", "experiment_sha256": BUNDLE_METADATA["experiment_sha256"]}
    try:
        extract_bundle(root)
        save(output / "bundle-manifest-used.json", BUNDLE_METADATA)
        rows, manifest, protocol, frozen, backend, seeds, lock = load_experiment(root)
        policy = BUNDLE_METADATA["policy"]
        validate_policy(manifest["stage"], policy)
        expected = schedule(rows, seeds, BUNDLE_METADATA["model_name"], backend, protocol)
        if len(expected) != BUNDLE_METADATA["schedule_attempts"]:
            raise ValueError("Schedule attempt count differs from bundle")
        for name in ("records.jsonl", "records.jsonl.attempts.jsonl", "session-ledger.json"):
            prior = root / "resume" / name
            current = output / name
            if prior.exists():
                if current.exists() and current.read_bytes() != prior.read_bytes():
                    raise ValueError("Existing output differs from explicitly retained resume history")
                current.write_bytes(prior.read_bytes())
        ledger_path = output / "session-ledger.json"
        prior_ledger = read_json(ledger_path) if ledger_path.exists() else {}
        validate_ledger_history(prior_ledger, output / "records.jsonl", expected)
        history_validated = True
        prior_ledger, _, starts = recover_history(prior_ledger, output / "records.jsonl", expected)
        if prior_ledger:
            save(ledger_path, prior_ledger)
        if len(starts) == len(expected):
            status.update(status="complete", attempts=len(starts))
            return
        ledger = reserve_session(prior_ledger, BUNDLE_METADATA["experiment_sha256"], policy,
            output / "records.jsonl", expected)
        save(ledger_path, ledger)  # Full reservation survives crashes and is never silently reclaimed.
        session_output = output / ("session-%03d" % len(ledger["sessions"]))
        session_output.mkdir()
        save(session_output / "session-start.json", {**status, "policy": policy, "prior_attempts": len(starts)})
        # Worker writes identities to this session but uses cumulative single-writer logs.
        max_calls = min(policy["batch_max_calls"], len(expected) - len(starts))
        status.update(status="running", max_new_attempts=max_calls, prior_attempts=len(starts))
        with (session_output / "worker.log").open("w", encoding="utf8") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(root), str(output), str(max_calls)],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                process.wait(timeout=max(0, policy["session_seconds"] - (time.monotonic() - started) - 10))
                status["status"] = "finished" if process.returncode == 0 else "error"
                status["worker_exit_code"] = process.returncode
            except subprocess.TimeoutExpired:
                status["status"] = "budget_stop"
                stop_worker(process)
        terminal, starts = finalize_interrupted(output / "records.jsonl", expected)
        if len(starts) > len(expected) or len(starts) - status["prior_attempts"] > max_calls:
            raise ValueError("Attempt budget exceeded")
        status.update(attempts=len(starts), terminal_records=len(terminal), remaining=len(expected) - len(starts),
            statuses=dict(Counter(row["status"] for row in terminal.values())))
    except BaseException as exc:
        status.update(status="error", error=f"{type(exc).__name__}: {exc}")
        if process:
            stop_worker(process)
        if expected is not None and history_validated:
            try:
                finalize_interrupted(output / "records.jsonl", expected)
            except Exception as recovery:
                status["history_recovery_error"] = str(recovery)
        raise
    finally:
        status["elapsed_seconds"] = time.monotonic() - started
        if ledger is not None:
            ledger["sessions"][-1].update(status=status["status"], elapsed_seconds=status["elapsed_seconds"],
                records_sha256=file_hash(output / "records.jsonl"), journal_sha256=file_hash(output / "records.jsonl.attempts.jsonl") if (output / "records.jsonl.attempts.jsonl").exists() else None)
            ledger["sessions"][-1]["history_after"] = history_snapshot(output / "records.jsonl")
            save(output / "session-ledger.json", ledger)
        # Preserve all per-session runtime diagnostics instead of overwriting the previous identity.
        if session_output:
            for name in ("actual-backend.json", "actual-checkpoint-manifest.json", "environment.txt", "hardware.json", "token-count-preflight.json", "batch-result.json"):
                source = output / name
                if source.exists():
                    source.replace(session_output / name)
            save(session_output / "status.json", status)
        save(output / "latest-status.json", status)
        (output / ".single-writer.lock").unlink(missing_ok=True)


def main():
    if BUNDLE_BASE64 is not None:
        if len(sys.argv) > 1 and sys.argv[1] == "--worker":
            worker_main(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]))
        else:
            runtime_main()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wheel", "contexts", "manifest", "protocol", "freeze", "backend-identity", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("primary-manifest", "runtime-lock", "resume"):
        parser.add_argument("--" + name, type=Path)
    for name in ("session-seconds", "stage-seconds", "free-quota-seconds", "max-sessions", "batch-max-calls"):
        parser.add_argument("--" + name, required=True, type=int)
    args = parser.parse_args()
    policy = {name: getattr(args, name) for name in ("session_seconds", "stage_seconds", "free_quota_seconds", "max_sessions", "batch_max_calls")}
    policy["free_t4_only"] = True
    result = build_bundle(args.wheel, args.contexts, args.manifest, args.protocol, args.freeze,
        args.backend_identity, args.output, policy, args.primary_manifest, args.runtime_lock, args.resume)
    print(json.dumps({"output": str(args.output), "stage": result["stage"], "schedule_attempts": result["schedule_attempts"], "experiment_sha256": result["experiment_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
