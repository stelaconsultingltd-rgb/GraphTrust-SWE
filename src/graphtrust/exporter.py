"""Explicit, local, allowlisted empirical exports without evaluator content.

Private records remain authoritative. Public rows use a separate schema and
retain original canonical hashes; redacted invalid slots are never repaired.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

from .io import digest
from .metrics import CONDITIONS, METRICS, _figures, evaluate_runs, summarize
from .prediction import (RECORD_DIGEST_RULE, RECORD_SCHEMA_VERSION,
    RESPONSE_CONTRACT_VERSION, canonical_record, exact_file_path, record_digest,
    validate_record_prediction)
from .provenance import implementation_sha256

PUBLIC_SCHEMA = "graphtrust_public_results_v1"
CONTEXT_FIELDS = set("case_id repo condition response_contract_version prompt source_sha256 context_sha256 input_tokens token_method visible_files visible_source_ids visible_edge_ids known_false_edge_ids visible_source_spans visible_callsite_edge_ids visible_definition_node_ids snapshot_sha256 protocol_sha256 source_pack_rule model_edge_rule".split())
MANIFEST_FIELDS = set("schema_version response_contract_version stage status implementation_sha256 protocol_sha256 tokenizer_identity source_pack_rule model_edge_rule token_method case_ids cases contexts selection_sha256 contexts_sha256 shortfalls exclusions sampling_seeds selection_uses_gold".split())
FREEZE_FIELDS = set("schema_version response_contract_version status protocol implementation_sha256 protocol_sha256 pilot_manifest_sha256 pilot_records_sha256 pilot_records_digest_rule pilot_records_file_sha256 primary_model parse_rate contract_parse_rate graph_citation_rate within_budget_contract_parse_rate observed_contract_parse_rate invalid_prediction_rate tokenizer_identity backend_sha256".split())
RUNTIME_FIELDS = set("status build_and_runtime_tested backend_sha256 llama_cpp_python_commit vendored_llama_cpp_commit llama_cpp_python_version cuda_cmake_args jinja2_version model_sha256 built_wheel_sha256 wheel_path development_records_sha256 build_log_sha256 environment_sha256".split())
HASH = re.compile(r"[a-f0-9]{64}\Z")
CREDENTIAL = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,})")


class ExportBoundaryError(ValueError):
    """Unsafe, incomplete or incompatible input; never echo private values."""


def require(ok, location):
    if not ok:
        raise ExportBoundaryError("Public export boundary failed at " + location)


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "JSON duplicate key")
        result[key] = value
    return result


def _float(text):
    value = float(text)
    require(math.isfinite(value), "JSON finite number")
    return value


def _decode(text):
    def constant(_):
        raise ExportBoundaryError("Public export boundary failed at JSON finite constant")
    return json.loads(text, object_pairs_hook=_object, parse_float=_float, parse_constant=constant)


def _read(path, jsonl=False):
    data = Path(path).read_bytes()
    if not jsonl:
        return _decode(data.decode("utf-8"))
    lines = data.decode("utf-8").splitlines()
    require(data.endswith(b"\n") and lines and all(line.strip() for line in lines), "complete JSONL")
    return [_decode(line) for line in lines]


def _safe(text, location):
    require(isinstance(text, str) and bool(text) and text == text.strip()
            and not any(ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF for ch in text)
            and not any(marker in text for marker in ("://", "?", "&", "=", "%", "\\"))
            and CREDENTIAL.search(text) is None, location)
    return text


def _hash(value, location):
    require(isinstance(value, str) and HASH.fullmatch(value), location)
    return value


def _allowed(value, fields, location):
    require(isinstance(value, dict) and not set(value) - fields, location + " fields")


def _number(value, location, maximum=None):
    require(value is None or (type(value) in {int, float} and math.isfinite(value)
            and value >= 0 and (maximum is None or value <= maximum)), location)
    return value


def _typed(value, expected):
    require(type(value) is type(expected), "stored validation types")
    if isinstance(expected, dict):
        require(value.keys() == expected.keys(), "stored validation fields")
        for key in expected:
            _typed(value[key], expected[key])
    elif isinstance(expected, list):
        require(len(value) == len(expected), "stored validation arrays")
        for a, b in zip(value, expected):
            _typed(a, b)


def _slots(items, visible, location):
    result = []
    for rank, item in enumerate(items, 1):
        if item in visible:
            _safe(item, location)
            result.append({"rank": rank, "reference": item, "redacted": False})
        else:
            result.append({"rank": rank, "reference": None, "redacted": True,
                           "original_value_sha256": record_digest(item)})
    return result


def _load_scored(path, values):
    if path is None:
        return None
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    require(len(rows) == len(values), "scored CSV completeness")
    indexed = {}
    for row in rows:
        key = row.get("run_id")
        require(key not in indexed, "scored CSV duplicate run")
        indexed[key] = row
    require(set(indexed) == {row["run_id"] for row in values}, "scored CSV schedule")
    return indexed


def _primary_counts(manifest, protocol):
    repos, requested = protocol["holdout_repositories"], protocol["holdout_per_repository"]
    shortfalls = manifest.get("shortfalls")
    require(isinstance(shortfalls, dict) and not set(shortfalls) - set(repos), "primary shortfall repositories")
    counts = dict.fromkeys(repos, requested)
    for repo, item in shortfalls.items():
        _allowed(item, {"requested", "available"}, "primary shortfall")
        require(type(item.get("requested")) is int and item["requested"] == requested
                and type(item.get("available")) is int and 0 <= item["available"] < requested, "primary shortfall counts")
        counts[repo] = item["available"]
    return counts


def _runtime_lock(path, backend):
    require(path is not None, "accepted replication runtime")
    lock = _read(path)
    _allowed(lock, RUNTIME_FIELDS, "runtime lock")
    require(lock.get("status") == "development_runtime_accepted" and lock.get("build_and_runtime_tested") is True
            and backend.get("name") == "llama_cpp" and lock.get("backend_sha256") == digest(backend), "accepted replication runtime identity")
    pins = {"llama_cpp_python_commit": "1652066e0af45f2313b339670ef9555e8a54e545",
            "vendored_llama_cpp_commit": "0c1e57098bba43ac29e6e3b677cdceebdd22334f",
            "llama_cpp_python_version": "0.3.36", "cuda_cmake_args": "-DGGML_CUDA=on", "jinja2_version": "3.1.6"}
    require(all(lock.get(name) == value for name, value in pins.items())
            and lock.get("model_sha256") == backend.get("model_sha256"), "replication runtime pins")
    for name in ("backend_sha256", "model_sha256", "built_wheel_sha256", "development_records_sha256", "build_log_sha256", "environment_sha256"):
        _hash(lock.get(name), "replication evidence hash")
    require(isinstance(lock.get("wheel_path"), str) and lock["wheel_path"].startswith("/kaggle/input/"), "separate replication wheel attachment")



def export_public_results(records, contexts, manifest, frozen, output, *,
                          journal=None, scored=None, figures=False, primary_manifest=None, runtime_lock=None):
    """Validate then atomically create a fresh local public artifact directory.

    No gold input is accepted. Optional evaluator CSV contributes only numeric
    localization outcomes joined by original record SHA. Figures are regenerated
    from the new allowlisted aggregate; arbitrary report/image files are not copied.
    """
    try:
        return _export(records, contexts, manifest, frozen, output, journal=journal, scored=scored,
                       figures=figures, primary_manifest=primary_manifest, runtime_lock=runtime_lock)
    except ExportBoundaryError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError):
        raise ExportBoundaryError("Public export boundary failed at input structure/encoding") from None


def _export(records, contexts, manifest, frozen, output, *, journal, scored, figures, primary_manifest, runtime_lock):
    paths = {"records": Path(records), "contexts": Path(contexts), "manifest": Path(manifest), "freeze": Path(frozen),
             "journal": Path(journal) if journal else Path(str(records) + ".attempts.jsonl")}
    values, context_rows = _read(paths["records"], True), _read(paths["contexts"], True)
    starts, cohort, freeze = _read(paths["journal"], True), _read(paths["manifest"]), _read(paths["freeze"])
    _allowed(cohort, MANIFEST_FIELDS, "manifest")
    _allowed(freeze, FREEZE_FIELDS, "freeze")
    protocol = freeze.get("protocol", {})
    require(freeze.get("status") == "frozen" and type(freeze.get("schema_version")) is type(cohort.get("schema_version")) is int
            and freeze.get("schema_version") == cohort.get("schema_version") == 2
            and freeze.get("response_contract_version") == cohort.get("response_contract_version") == RESPONSE_CONTRACT_VERSION,
            "accepted current freeze")
    require(freeze.get("implementation_sha256") == cohort.get("implementation_sha256") == implementation_sha256(), "implementation identity")
    require(freeze.get("protocol_sha256") == cohort.get("protocol_sha256") == digest(protocol), "protocol identity")
    require(freeze.get("pilot_records_digest_rule") == RECORD_DIGEST_RULE
            and freeze.get("parse_rate", 0) >= protocol["pilot_minimum_parse_rate"]
            and freeze.get("graph_citation_rate", 0) >= protocol["pilot_minimum_graph_citation_rate"], "pilot gates")
    for name in FREEZE_FIELDS:
        if name.endswith("sha256") or name == "tokenizer_identity":
            _hash(freeze[name], "freeze identity")
        elif name.endswith("rate"):
            require(freeze[name] is not None, "freeze rate")
            _number(freeze[name], "freeze rate", 1)
    require(cohort.get("stage") in {"pilot", "holdout", "replication"} and cohort.get("selection_uses_gold") is False
            and cohort.get("token_method") == "tokenizer", "scientific cohort")
    require(cohort.get("contexts_sha256") == digest(context_rows) and cohort.get("selection_sha256") == digest(cohort["case_ids"]), "context/selection identity")
    _hash(cohort.get("tokenizer_identity"), "cohort tokenizer identity")
    if cohort["stage"] != "replication":
        require(cohort["tokenizer_identity"] == freeze["tokenizer_identity"], "accepted primary tokenizer")
    require(all(cohort.get(name) == protocol.get(name) for name in ("source_pack_rule", "model_edge_rule")), "cohort construction rules")
    require(protocol.get("conditions") == list(CONDITIONS) and protocol.get("response_contract_version") == RESPONSE_CONTRACT_VERSION
            and protocol.get("sampling_seeds_primary") == [17, 42] and protocol.get("sampling_seeds_replication") == [17], "protocol schedule")
    seeds = protocol["sampling_seeds_replication" if cohort["stage"] == "replication" else "sampling_seeds_primary"]
    require(cohort.get("sampling_seeds") == seeds and len(seeds) == len(set(seeds)) and all(type(seed) is int for seed in seeds), "sampling seeds")
    require(isinstance(cohort.get("case_ids"), list) and all(isinstance(case_id, str) for case_id in cohort["case_ids"]), "selected identifier list")
    require(type(cohort.get("cases")) is type(cohort.get("contexts")) is int and cohort["cases"] > 0
            and len(context_rows) == cohort["contexts"] == cohort["cases"] * 6
            and len(cohort["case_ids"]) == len(set(cohort["case_ids"])) == cohort["cases"], "cohort counts")
    if cohort["stage"] == "pilot":
        require(cohort["cases"] == protocol["pilot_issues"] and freeze["pilot_manifest_sha256"] == digest(cohort)
                and freeze["pilot_records_sha256"] == record_digest(values)
                and freeze["pilot_records_file_sha256"] == hashlib.sha256(paths["records"].read_bytes()).hexdigest(), "accepted pilot evidence identity")
    repos = protocol["development_repositories" if cohort["stage"] == "pilot" else "holdout_repositories"]
    by_arm, by_case, public_contexts = {}, {}, []
    for row in context_rows:
        _allowed(row, CONTEXT_FIELDS, "context")
        key = (row["case_id"], row["condition"])
        require(key not in by_arm and row["condition"] in CONDITIONS and row["repo"] in repos, "context arm/repository")
        require(row.get("response_contract_version") == RESPONSE_CONTRACT_VERSION and row.get("token_method") == "tokenizer", "context version")
        require(hashlib.sha256(row["prompt"].encode("utf-8")).hexdigest() == row["context_sha256"], "prompt identity")
        try:
            source = row["prompt"].split("\nSOURCE PACK\n", 1)[1].split("END SOURCE PACK\n", 1)[0]
        except (IndexError, AttributeError):
            raise ExportBoundaryError("Public export boundary failed at source section") from None
        require(hashlib.sha256(source.encode("utf-8")).hexdigest() == row["source_sha256"], "source bytes identity")
        require(row.get("protocol_sha256") == cohort["protocol_sha256"], "context protocol")
        require(type(row["input_tokens"]) is int and 0 < row["input_tokens"] <= protocol["max_input_tokens"] <= 4000, "input budget")
        for name in ("case_id", "repo", "source_pack_rule", "model_edge_rule"):
            _safe(row[name], "context " + name)
        require(all(row[name] == protocol[name] for name in ("source_pack_rule", "model_edge_rule")), "context construction rules")
        for name in ("source_sha256", "context_sha256", "snapshot_sha256"):
            _hash(row[name], "context " + name)
        for path in row["visible_files"]:
            require(exact_file_path(path), "context candidate file")
            _safe(path, "context candidate file")
        for name in ("visible_source_ids", "visible_edge_ids"):
            for identifier in row[name]:
                _safe(identifier, "context visible identifier")
        require(all(isinstance(row[name], list) and len(row[name]) == len(set(row[name]))
                    for name in ("visible_files", "visible_source_ids", "visible_edge_ids")), "unique visible metadata arrays")
        by_arm[key] = row
        by_case.setdefault(row["case_id"], []).append(row)
        public_contexts.append({name: row[name] for name in ("case_id", "repo", "condition", "response_contract_version", "source_sha256", "context_sha256", "snapshot_sha256", "input_tokens", "token_method", "visible_files", "visible_source_ids", "visible_edge_ids")})
    require(set(by_case) == set(cohort["case_ids"]), "selected case IDs")
    require([(row["case_id"], row["condition"]) for row in context_rows]
            == [(case_id, condition) for case_id in cohort["case_ids"] for condition in CONDITIONS], "manifest context order")
    for arms in by_case.values():
        require(sorted(row["condition"] for row in arms) == sorted(CONDITIONS)
                and len({row["source_sha256"] for row in arms}) == len({row["snapshot_sha256"] for row in arms})
                == len({row["repo"] for row in arms}) == 1, "matched source/snapshot arms")
        require(all(row["visible_files"] == arms[0]["visible_files"] and row["visible_source_ids"] == arms[0]["visible_source_ids"]
                    for row in arms), "matched source metadata order")
    counts = Counter(arms[0]["repo"] for arms in by_case.values())
    require(isinstance(cohort["shortfalls"], dict) and not set(cohort["shortfalls"]) - set(repos), "shortfall repositories")
    shortfalls = {}
    for repo, shortfall in cohort["shortfalls"].items():
        _allowed(shortfall, {"requested", "available"}, "shortfall")
        require(type(shortfall.get("requested")) is int and shortfall.get("requested") == protocol["development_per_repository" if cohort["stage"] == "pilot" else "holdout_per_repository"]
                and type(shortfall.get("available")) is int and 0 <= shortfall["available"] < shortfall["requested"], "shortfall counts")
        shortfalls[repo] = dict(shortfall)
    if cohort["stage"] == "holdout":
        require(all(counts[repo] == shortfalls.get(repo, {"available": protocol["holdout_per_repository"]})["available"] for repo in repos), "declared primary shortfalls")
        require([by_case[case_id][0]["repo"] for case_id in cohort["case_ids"]]
                == [repo for repo in repos for _ in range(counts[repo])], "primary repository selection order")
    if cohort["stage"] == "replication":
        require(primary_manifest is not None, "fixed primary replication manifest")
        primary = _read(primary_manifest)
        _allowed(primary, MANIFEST_FIELDS, "primary manifest")
        require(primary.get("stage") == "holdout" and primary.get("selection_uses_gold") is False
                and primary.get("schema_version") == 2 and primary.get("response_contract_version") == RESPONSE_CONTRACT_VERSION
                and primary.get("protocol_sha256") == cohort["protocol_sha256"]
                and primary.get("implementation_sha256") == cohort["implementation_sha256"]
                and primary.get("selection_sha256") == digest(primary["case_ids"]), "primary selection identity")
        primary_counts = _primary_counts(primary, protocol)
        require(isinstance(primary.get("case_ids"), list) and all(isinstance(case_id, str) for case_id in primary["case_ids"])
                and len(primary["case_ids"]) == sum(primary_counts.values()) == primary.get("cases")
                and len(set(primary["case_ids"])) == len(primary["case_ids"])
                and primary.get("contexts") == len(primary["case_ids"]) * 6
                and primary.get("sampling_seeds") == [17, 42] and primary.get("token_method") == "tokenizer", "complete primary selection")
        expected_ids, offset = [], 0
        for repo in repos:
            count = primary_counts[repo]
            require(counts[repo] == min(protocol["replication_per_repository"], count)
                    and shortfalls.get(repo, {"available": protocol["holdout_per_repository"]})["available"] >= counts[repo], "paired replication shortfalls")
            expected_ids.extend(primary["case_ids"][offset:offset + min(protocol["replication_per_repository"], count)])
            offset += count
        require(cohort["case_ids"] == expected_ids, "fixed replication subset")
        require([by_case[case_id][0]["repo"] for case_id in cohort["case_ids"]]
                == [repo for repo in repos for _ in range(counts[repo])], "replication repository selection order")
        paths["primary_manifest"] = Path(primary_manifest)
    expected = {(case_id, condition, seed) for case_id, condition in by_arm for seed in seeds}
    require(len(values) == len(starts) == len(expected) and len({row["run_id"] for row in values}) == len(values), "complete unique attempts")
    require([(row["case_id"], row["condition"], row["seed"]) for row in values]
            and {(row["case_id"], row["condition"], row["seed"]) for row in values} == expected, "attempt schedule")
    require([row["run_id"] for row in starts] == [row["run_id"] for row in values], "attempt journal/no recorded retry")
    generation = {"max_output_tokens": protocol["max_output_tokens"], "temperature": protocol["temperature"], "thinking": False, "timeout_seconds": protocol["timeout_seconds"]}
    require(0 < generation["max_output_tokens"] <= 256 and 0 < generation["timeout_seconds"] <= 90, "generation budgets")
    public_records, public_starts = [], []
    backends = set()
    for value, start in zip(values, starts):
        context = by_arm[(value["case_id"], value["condition"])]
        require(value.get("synthetic") is False and value.get("schema_version") == RECORD_SCHEMA_VERSION, "real current record")
        require(type(value.get("seed")) is int, "record seed type")
        require(value.get("repo") == context["repo"] and value.get("source_sha256") == context["source_sha256"]
                and value.get("context_sha256") == context["context_sha256"], "record source/context")
        backend = value.get("backend", {})
        require(backend.get("name") in {"transformers", "llama_cpp"} and backend.get("enable_thinking") is False
                and backend.get("tokenizer_sha256") == cohort["tokenizer_identity"]
                and (backend.get("checkpoint_sha256") or backend.get("model_sha256")), "real immutable backend")
        for name in ("checkpoint_sha256", "model_sha256"):
            if backend.get(name) is not None:
                _hash(backend[name], "immutable model hash")
        fingerprint = digest(backend)
        configuration_sha = record_digest({"backend": backend, "generation": generation,
                                           "response_contract_version": RESPONSE_CONTRACT_VERSION})
        backends.add(fingerprint)
        if cohort["stage"] != "replication":
            require(fingerprint == freeze["backend_sha256"] and value.get("model_name") == freeze["primary_model"], "accepted primary runtime")
        require(value.get("generation") == generation and value["generation"].get("thinking") is False, "record generation")
        run_key = {"context_sha256": context["context_sha256"], "case_id": context["case_id"], "condition": context["condition"],
                   "model_name": value["model_name"], "backend": backend, "seed": value["seed"],
                   "generation": generation, "response_contract_version": RESPONSE_CONTRACT_VERSION}
        require(value["run_id"] == digest(run_key), "runtime run identity")
        for name in ("visible_files", "visible_source_ids", "visible_edge_ids"):
            require(value.get(name) == context[name], "record visible metadata")
        require(type(value.get("input_tokens")) is int and value["input_tokens"] == context["input_tokens"], "runtime input count")
        require(value.get("output_tokens") is None or type(value["output_tokens"]) is int, "output token type")
        _number(value.get("output_tokens"), "output budget", generation["max_output_tokens"])
        try:
            prediction, checked = validate_record_prediction(value, context)
        except (ValueError, TypeError, KeyError):
            raise ExportBoundaryError("Public export boundary failed at raw record classification") from None
        for name, item in checked.items():
            _typed(value[name], item)
        for name in ("run_id", "source_sha256", "context_sha256"):
            _hash(value[name], "record " + name)
        require(start.get("status") == "started" and start.get("raw_output") is None
                and start.get("synthetic") is False and start.get("response") is None and start.get("prediction") is None
                and start.get("contract_parseable") is False and start.get("invalid_prediction") is False
                and start.get("output_tokens") is None and start.get("input_token_method") == "tokenizer"
                and start.get("input_tokens") == context["input_tokens"], "original attempt start")
        for name in ("case_id", "repo", "condition", "seed", "backend", "generation", "model_name", "context_sha256", "source_sha256", "started_at", "schema_version", "response_contract_version"):
            require(start.get(name) == value.get(name), "journal identity")
        visible_files = set(context["visible_files"])
        valid_citations = set(checked.get("valid_graph_citations", []) + checked.get("valid_source_id_citations", []) + checked.get("valid_file_citations", []))
        flags = checked.get("prediction_flags", {})
        row = {name: value[name] for name in ("run_id", "case_id", "repo", "condition", "seed", "status", "contract_parseable", "invalid_prediction", "input_tokens", "output_tokens", "latency_seconds", "source_sha256", "context_sha256")}
        row.update(public_schema=PUBLIC_SCHEMA, original_record_sha256=record_digest(value),
                   original_record_digest_rule=RECORD_DIGEST_RULE, model_configuration_sha256=configuration_sha,
                   within_budget_contract_parseable=value["contract_parseable"] and value["status"] in {"ok", "invalid_prediction"},
                   abstain=prediction.get("abstain", False) if prediction else False,
                   files=_slots(prediction["files"], visible_files, "public file") if prediction else [],
                   citations=_slots(prediction["citations"], valid_citations, "public citation") if prediction else [],
                   prediction_diagnostics={name: bool(flags.get(name)) for name in ("duplicate_files", "duplicate_citations", "too_many_files", "too_many_citations", "abstain_with_files", "empty_without_abstain")},
                   extra_field_count=len(flags.get("extra_fields", [])), invalid_file_count=len(checked.get("invalid_files", [])),
                   invalid_citation_count=len(checked.get("invalid_citations", [])))
        row["out_of_memory"] = value.get("error_kind") == "out_of_memory" or "out of memory" in str(value.get("error", "")).lower()
        if "completed_status" in value:
            row["completed_status"] = value["completed_status"]
        public_records.append(row)
        public_starts.append({"public_schema": PUBLIC_SCHEMA, "run_id": value["run_id"], "case_id": value["case_id"],
            "condition": value["condition"], "seed": value["seed"], "status": "started",
            "original_start_sha256": record_digest(start), "original_start_digest_rule": RECORD_DIGEST_RULE})
    require(len(backends) == 1, "one model runtime")
    if cohort["stage"] == "replication":
        _runtime_lock(runtime_lock, values[0]["backend"])
        paths["runtime_lock"] = Path(runtime_lock)
    model_alias = "model_" + public_records[0]["model_configuration_sha256"][:12]
    scored_index = _load_scored(scored, values)
    require(not figures or scored_index is not None, "figures require scored outcomes")
    scored_rows = evaluate_runs(values, {}, context_rows)
    labels_by_case = {}
    for value, row, public in zip(values, scored_rows, public_records):
        row["model_name"] = model_alias
        if scored_index is not None:
            source = scored_index[value["run_id"]]
            require(source.get("record_sha256") == record_digest(value), "scored original record hash")
            for field in ("case_id", "repo", "condition", "status"):
                require(source.get(field) == row[field], "scored identity")
            require(source.get("gold_present") in {"True", "False"}, "scored label availability")
            row["gold_present"] = source["gold_present"] == "True"
            for field in ("file_recall_at5", "hit_at5", "coverage_ceiling"):
                try:
                    number = float(source[field]) if source.get(field) not in {None, ""} else None
                except (ValueError, TypeError):
                    raise ExportBoundaryError("Public export boundary failed at scored numeric outcome") from None
                row[field] = _number(number, "scored numeric outcome", 1)
                require((number is not None) == row["gold_present"], "scored missing-label policy")
            if row["gold_present"] and (row["status"] not in {"ok", "invalid_prediction"} or row["abstain"]):
                require(row["file_recall_at5"] == row["hit_at5"] == 0, "failure localization policy")
            if row["gold_present"]:
                require(row["file_recall_at5"] <= row["coverage_ceiling"] and row["hit_at5"] in {0., 1.}
                        and (row["hit_at5"] == 1.) == (row["file_recall_at5"] > 0.), "scored localization consistency")
            labels = (row["gold_present"], row["coverage_ceiling"])
            require(labels == labels_by_case.setdefault(row["case_id"], labels), "issue-level label availability/ceiling")
        public["metrics"] = {name: row[name] for name in METRICS}
    summary = summarize(scored_rows)
    # summarize creates fresh aggregate objects; it never copies reference_files,
    # predicted_files, source paths, raw responses or arbitrary input dictionaries.
    payloads = {"records.jsonl": public_records, "attempts.jsonl": public_starts,
                "contexts.jsonl": public_contexts, "summary.json": summary,
                "freeze.json": {name: freeze[name] for name in FREEZE_FIELDS - {"protocol", "primary_model"}},
                "manifest.json": {"public_schema": PUBLIC_SCHEMA, "status": "validated_public_export", "stage": cohort["stage"],
                    "implementation_sha256": cohort["implementation_sha256"], "protocol_sha256": cohort["protocol_sha256"],
                    "selection_sha256": cohort["selection_sha256"], "contexts_sha256": cohort["contexts_sha256"],
                    "case_ids": cohort["case_ids"], "cases": cohort["cases"], "contexts": cohort["contexts"],
                    "sampling_seeds": seeds, "attempts": len(values), "shortfalls": shortfalls,
                    "exclusions_count": len(cohort["exclusions"]), "exclusions_sha256": record_digest(cohort["exclusions"]),
                    "model_alias": model_alias, "backend_sha256": next(iter(backends)),
                    "model_configuration_sha256": public_records[0]["model_configuration_sha256"],
                    "model_identity": {"backend": values[0]["backend"]["name"],
                        "checkpoint_sha256": values[0]["backend"].get("checkpoint_sha256"),
                        "model_sha256": values[0]["backend"].get("model_sha256"),
                        "tokenizer_sha256": cohort["tokenizer_identity"], "thinking": False},
                    "original_input_file_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()},
                    "scored_file_sha256": hashlib.sha256(Path(scored).read_bytes()).hexdigest() if scored else None,
                    "original_record_digest_rule": RECORD_DIGEST_RULE,
                    "regeneration": "Regenerate evaluator-only gold/source with the pinned dataset/protocol; public rows preserve valid first-five ranks and failures. Raw responses remain private."}}
    output = Path(output)
    require(not output.exists(), "fresh output directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + output.name + ".", dir=output.parent))
    try:
        if figures:
            names = _figures(summary, staging)
            require(bool(names), "plotting dependency/figures")
            payloads["manifest.json"]["figures"] = names
        else:
            payloads["manifest.json"]["figures"] = []
        for name, content in payloads.items():
            text = "\n".join(canonical_record(row) for row in content) if name.endswith(".jsonl") else canonical_record(content)
            (staging / name).write_text(text + "\n", encoding="utf-8", newline="\n")
        payloads["manifest.json"]["public_files_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(staging.iterdir()) if path.name != "manifest.json"}
        (staging / "manifest.json").write_text(canonical_record(payloads["manifest.json"]) + "\n", encoding="utf-8")
        os.replace(staging, output)
    finally:
        if staging.exists():
            require(staging.resolve().parent == output.parent.resolve() and staging.name.startswith("." + output.name + "."), "owned staging cleanup")
            shutil.rmtree(staging)
    return {"status": "validated_public_export", "stage": cohort["stage"], "issues": cohort["cases"],
            "attempts": len(values), "files": sorted(path.name for path in output.iterdir())}
