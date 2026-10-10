"""CPU qualification, six-arm materialization, and pre-registered selection."""
from __future__ import annotations

import gzip
import hashlib
import re
import os
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .corpus import _writer_lock, prepare_snapshot, select_cases
from .context import MODEL_EDGE_RULE, SOURCE_PACK_RULE
from .io import canonical, digest, read_json, read_jsonl, write_json, write_jsonl
from .provenance import extractor_sha256, implementation_sha256
from .prediction import (RECORD_DIGEST_RULE, RECORD_SCHEMA_VERSION, RESPONSE_CONTRACT_VERSION,
                         record_digest, validate_record_prediction)

_LOADED_IMPLEMENTATION = implementation_sha256()


def _assert_unchanged_implementation() -> None:
    if implementation_sha256() != _LOADED_IMPLEMENTATION:
        raise RuntimeError("Executable files changed during this process; restart before producing scientific artifacts")


def _packed_source_graph(graph: dict, pack: dict) -> tuple[dict, list[dict], int]:
    """Retain clean metadata only when its original call line is visible."""
    spans = [{"node_id": match[1], "path": match[2], "start_line": int(match[3]), "end_line": int(match[4])}
             for match in re.finditer(r"^SOURCE (.+) FILE (.+) LINES (\d+)-(\d+) TRUNCATED (?:true|false)$",
                                      pack["source_text"], re.MULTILINE)]
    ids = set(pack["node_ids"])
    induced = [e for e in graph["edges"] if e["source"] in ids and e["target"] in ids
               and e.get("resolution", "supported") == "supported"]
    visible = [e for e in induced if any(s["path"] == e["path"] and s["start_line"] <= e["line"] <= s["end_line"]
                                        for s in spans)]
    packed = {**graph, "nodes": [n for n in graph["nodes"] if n["id"] in ids], "unknown": [],
              "edges": sorted(visible, key=lambda e: e["id"])}
    return packed, spans, len(induced)


def load_graph(path: str | Path) -> dict:
    import json
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def save_graph(path: Path, graph: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        # Each worker owns its staging file. mtime=0 and filename="" keep the
        # final gzip bytes reproducible despite the private temporary filename.
        with tempfile.NamedTemporaryFile(mode="wb", prefix=path.name + ".", suffix=".tmp",
                                         dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as stream:
                stream.write(canonical(graph).encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        # Windows can briefly deny a replacement while another worker replaces
        # or reads the same completed cache file. Keep the atomic staging bytes
        # intact and retry that transient race instead of rebuilding the graph.
        for attempt in range(6):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_case(case: dict, data: str, output: str, protocol: dict) -> dict:
    from .context import build_source_pack
    from .graph import build_graph
    from .interventions import perturb_graph

    _assert_unchanged_implementation()
    out = Path(output)
    record_path = out / "cases" / (case["case_id"] + ".json")
    if record_path.exists():
        existing = read_json(record_path)
        graph_file = out / existing.get("graph_path", "missing")
        if (existing.get("protocol_sha256") == digest(protocol) and existing.get("status") == "ok"
                and existing.get("implementation_sha256") == _LOADED_IMPLEMENTATION
                and existing.get("preparation_schema_version") == 2
                and existing.get("case_sha256") == digest(case) and graph_file.is_file()
                and existing.get("graph_file_sha256") == hashlib.sha256(graph_file.read_bytes()).hexdigest()):
            prepare_snapshot(case, Path(data) / "cache")
            return existing
    try:
        snapshot = prepare_snapshot(case, Path(data) / "cache")
        graph_key = digest({"repo": case["repo"], "commit": case["commit"], "extractor_sha256": extractor_sha256()})
        graph_path = out / "graphs" / (graph_key + ".json.gz")
        loaded_from_cache = graph_path.exists()
        graph = load_graph(graph_path) if loaded_from_cache else build_graph(snapshot, commit=case["commit"])
        if graph["snapshot"]["commit"] != case["commit"]:
            raise ValueError("Cached graph commit does not match the requested case")
        if loaded_from_cache and graph.get("extractor_sha256") != extractor_sha256():
            raise ValueError("Cached graph has no matching extractor fingerprint")
        if not loaded_from_cache:
            graph["extractor_sha256"] = extractor_sha256()
            # Extraction stays outside this short per-key publication lock.
            # A sibling artifact must be validated and reused, never overwritten.
            with _writer_lock(graph_path.with_suffix(graph_path.suffix + ".lock")):
                if graph_path.exists():
                    published = load_graph(graph_path)
                    if published["snapshot"]["commit"] != case["commit"]:
                        raise ValueError("Cached graph commit does not match the requested case")
                    if published.get("extractor_sha256") != extractor_sha256():
                        raise ValueError("Cached graph has no matching extractor fingerprint")
                    if digest(published) != digest(graph):
                        raise ValueError("Concurrent graph publication differs from the fresh graph")
                    graph = published
                else:
                    save_graph(graph_path, graph)
        pack = build_source_pack(graph, case["issue_text"], max_source_tokens=protocol["max_source_tokens"],
                                 min_files=protocol["minimum_candidate_files"])
        packed, _, induced_edges = _packed_source_graph(graph, pack)
        variants = []
        for seed in protocol["corruption_seeds_cpu"]:
            for severity in protocol["severity_cpu"]:
                for kind in ("delete", "rewire"):
                    _, sidecar = perturb_graph(packed, kind, severity, seed, source_graph=graph)
                    variants.append(sidecar)
        # Byte-budget qualification is provisional; exact tokenizer qualification happens before freeze.
        eligible = len(packed["edges"]) >= protocol["minimum_eligible_edges"]
        reason = "eligible_provisional_byte_budget" if eligible else "fewer_than_minimum_packed_supported_edges"
        _assert_unchanged_implementation()
        record = {"preparation_schema_version": 2, "case_id": case["case_id"], "repo": case["repo"], "split": case["split"], "status": "ok",
                  "commit": case["commit"], "graph_path": str(graph_path.relative_to(out)).replace("\\", "/"),
                  "snapshot_sha256": graph["snapshot"]["source_sha256"],
                  "graph_nodes": len(graph["nodes"]), "graph_edges": len(graph["edges"]),
                  "unknown_bindings": len(graph.get("unknown", [])), "parse_errors": graph.get("errors", []),
                  "packed_edges": len(packed["edges"]), "candidate_files": len(pack["files"]),
                  "induced_endpoint_edges": induced_edges, "source_pack_rule": SOURCE_PACK_RULE, "model_edge_rule": MODEL_EDGE_RULE,
                  "eligible": eligible, "reason": reason, "source_sha256": pack["source_sha256"],
                  "token_method": pack["token_method"], "variants": variants, "protocol_sha256": digest(protocol),
                  "case_sha256": digest(case), "graph_file_sha256": hashlib.sha256(graph_path.read_bytes()).hexdigest(),
                  "implementation_sha256": _LOADED_IMPLEMENTATION}
    except Exception as exc:
        record = {"case_id": case["case_id"], "repo": case["repo"], "split": case["split"], "status": "error",
                  "eligible": False, "reason": f"{type(exc).__name__}: {exc}", "protocol_sha256": digest(protocol)}
    write_json(record_path, record)
    return record


def prepare_cases(cases: list[dict], data: str | Path, output: str | Path, protocol: dict, workers: int = 3) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    if workers <= 1:
        for case in cases:
            row = prepare_case(case, str(data), str(output), protocol)
            rows.append(row)
            print(f"[{len(rows)}/{len(cases)}] {row['case_id']}: {row['reason']}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(prepare_case, case, str(data), str(output), protocol): case for case in cases}
            for future in as_completed(pending):
                row = future.result()
                rows.append(row)
                print(f"[{len(rows)}/{len(cases)}] {row['case_id']}: {row['reason']}", flush=True)
    rows.sort(key=lambda row: row["case_id"])
    write_jsonl(output / "audit.jsonl", rows)
    summary = {"attempted": len(rows), "ok": sum(r["status"] == "ok" for r in rows),
               "errors": sum(r["status"] == "error" for r in rows), "provisional_eligible": sum(r["eligible"] for r in rows),
               "source_pack_rule": SOURCE_PACK_RULE, "model_edge_rule": MODEL_EDGE_RULE,
               "protocol_sha256": digest(protocol), "research_status": "cpu_diagnostics_only_no_model_findings"}
    write_json(output / "CPU_SUMMARY.json", summary)
    return summary


def materialize_case(case: dict, graph: dict, protocol: dict, token_counter=None) -> tuple[list[dict], dict]:
    from .context import ContextBudgetError, build_context, build_source_pack
    from .interventions import check_edges, perturb_graph

    # Uniform reductions across ALL arms are allowed in development, never arm-specific.
    budget = protocol["max_source_tokens"]
    while budget >= 256:
        pack = build_source_pack(graph, case["issue_text"], token_counter=token_counter, max_source_tokens=budget,
                                 min_files=protocol["minimum_candidate_files"])
        packed_graph, spans, induced_edges = _packed_source_graph(graph, pack)
        def line_visible(path, line):
            return any(s["path"] == path and s["start_line"] <= line <= s["end_line"] for s in spans)
        try:
            while True:
                rewired, rewire_sidecar = perturb_graph(packed_graph, "rewire", protocol["severity_model"], protocol["corruption_seed_model"], source_graph=graph)
                # Pair omission and misinformation at their ACTUAL changed edge count.
                matched_severity = rewire_sidecar["achieved_edge_count"] / len(packed_graph["edges"]) if packed_graph["edges"] else 0
                deleted, deletion_sidecar = perturb_graph(packed_graph, "delete", matched_severity, protocol["corruption_seed_model"])
                arms = {"source_only": packed_graph, "clean": packed_graph, "deleted": deleted, "rewired": rewired,
                        "clean_checked": packed_graph, "rewired_checked": rewired}
                rows, fully_visible = [], True
                for condition in protocol["conditions"]:
                    observed = arms[condition]
                    checked = check_edges(observed, graph) if condition.endswith("_checked") else None
                    row = build_context(case, pack, observed, condition, checker_statuses=checked, token_counter=token_counter,
                                        max_input_tokens=protocol["max_input_tokens"], max_relation_tokens=protocol["max_relation_tokens"])
                    if condition != "source_only" and set(row["visible_edge_ids"]) != {e["id"] for e in observed["edges"]}:
                        fully_visible = False
                    false_ids = rewire_sidecar.get("false_edge_ids", []) if condition.startswith("rewired") else []
                    row["known_false_edge_ids"] = sorted(set(false_ids) & set(row["visible_edge_ids"]))
                    row["visible_source_spans"] = spans
                    row["visible_callsite_edge_ids"] = sorted(e["id"] for e in observed["edges"]
                            if e["id"] in row["visible_edge_ids"] and line_visible(e["path"], e["line"]))
                    row["visible_definition_node_ids"] = sorted(n["id"] for n in packed_graph["nodes"]
                            if line_visible(n["path"], n["start_line"]))
                    row["snapshot_sha256"] = graph["snapshot"]["source_sha256"]
                    row["protocol_sha256"] = digest(protocol)
                    row["source_pack_rule"] = SOURCE_PACK_RULE
                    row["model_edge_rule"] = MODEL_EDGE_RULE
                    rows.append(row)
                if fully_visible:
                    break
                # Freeze a common edge subset that fits even checked arms; no arm
                # gets unrelated extra edges because its metadata happened to be shorter.
                packed_graph["edges"] = packed_graph["edges"][:-1]
            break
        except ContextBudgetError:
            budget = int(budget * 0.8)
    else:
        raise ValueError("Issue/instructions do not fit the common input budget even with minimum source")
    hashes = {row["source_sha256"] for row in rows}
    if len(hashes) != 1:
        raise AssertionError("Source changed between arms")
    clean = next(row for row in rows if row["condition"] == "clean")
    false = next(row for row in rows if row["condition"] == "rewired")
    eligible = (len(clean["visible_edge_ids"]) >= protocol["minimum_eligible_edges"]
                and bool(false["known_false_edge_ids"]))
    qualification = {"case_id": case["case_id"], "eligible": eligible,
                     "reason": "eligible" if eligible else "insufficient_visible_or_false_edges",
                     "candidate_files": len(pack["files"]), "visible_edges": len(clean["visible_edge_ids"]),
                     "visible_false_edges": len(false["known_false_edge_ids"]), "source_sha256": pack["source_sha256"],
                     "visible_clean_callsites": len(clean["visible_callsite_edge_ids"]),
                     "visible_false_callsites": len(set(false["visible_callsite_edge_ids"]) & set(false["known_false_edge_ids"])),
                     "callsite_visibility_required_for_edges": True, "coverage_counts_not_model_outcomes": True,
                     "induced_endpoint_edges": induced_edges, "source_pack_rule": SOURCE_PACK_RULE, "model_edge_rule": MODEL_EDGE_RULE,
                     "token_method": pack["token_method"], "source_budget": budget, "nominal_severity": protocol["severity_model"],
                     "deletion": deletion_sidecar, "rewiring": rewire_sidecar}
    return rows, qualification


def create_contexts(cases: list[dict], prepared: str | Path, output: str | Path, protocol: dict,
                    stage: str, token_counter=None, token_identity: str | None = None,
                    primary_manifest: dict | None = None) -> dict:
    prepared, output = Path(prepared), Path(output)
    _assert_unchanged_implementation()
    output.mkdir(parents=True, exist_ok=True)
    qualifications, all_rows = {}, {}
    allowed_split = "dev" if stage == "pilot" else "test"
    allowed_repos = protocol["development_repositories" if stage == "pilot" else "holdout_repositories"]
    if stage == "replication" and primary_manifest is None:
        raise ValueError("Replication requires the primary holdout manifest; never reselect under a second tokenizer")
    if stage == "replication":
        if (primary_manifest.get("stage") != "holdout" or primary_manifest.get("protocol_sha256") != digest(protocol)
                or primary_manifest.get("selection_sha256") != digest(primary_manifest.get("case_ids"))
                or len(primary_manifest["case_ids"]) != len(set(primary_manifest["case_ids"]))):
            raise ValueError("Replication primary manifest has invalid stage, protocol, or selection identity")
    for case in cases:
        if case["split"] != allowed_split or case["repo"] not in allowed_repos:
            continue
        record_path = prepared / "cases" / (case["case_id"] + ".json")
        if not record_path.exists():
            continue
        record = read_json(record_path)
        if record["status"] != "ok":
            qualifications[case["case_id"]] = {"eligible": False, "reason": record["reason"]}
            continue
        try:
            graph = load_graph(prepared / record["graph_path"])
            if graph["snapshot"]["commit"] != case["commit"] or record.get("commit") != case["commit"]:
                raise ValueError("Case commit does not match cached graph")
            if record.get("case_sha256") != digest(case):
                raise ValueError("Case metadata changed after preparation")
            if graph.get("extractor_sha256") != extractor_sha256():
                raise ValueError("Preparation uses a different or unversioned extractor")
            if record.get("implementation_sha256") != implementation_sha256():
                raise ValueError("Implementation changed since CPU preparation; resume prepare first")
            if record.get("preparation_schema_version") != 2:
                raise ValueError("Preparation predates process-stable provenance; resume prepare first")
            if record.get("graph_file_sha256") != hashlib.sha256((prepared / record["graph_path"]).read_bytes()).hexdigest():
                raise ValueError("Cached graph checksum changed")
            rows, qualification = materialize_case(case, graph, protocol, token_counter)
            all_rows[case["case_id"]] = rows
            qualifications[case["case_id"]] = qualification
        except Exception as exc:
            qualifications[case["case_id"]] = {"eligible": False, "reason": f"{type(exc).__name__}: {exc}"}
    selection = select_cases(cases, qualifications, protocol, allowed_split)
    selected = selection["cases"]
    if stage == "pilot":
        # Round-robin across repositories keeps the 10-case pilot diverse.
        by_repo = {repo: [c for c in selected if c["repo"] == repo] for repo in allowed_repos}
        ordered = [group[i] for i in range(protocol["development_per_repository"]) for group in by_repo.values() if i < len(group)]
        selected = ordered[:protocol["pilot_issues"]]
    elif stage == "replication":
        by_id = {c["case_id"]: c for c in cases}
        primary = [by_id[identity] for identity in primary_manifest["case_ids"]]
        selected = [c for repo in allowed_repos for c in [v for v in primary if v["repo"] == repo][:protocol["replication_per_repository"]]]
        # Eligibility changes in a second runtime become disclosed failures, not replacement issues.
        missing = [c["case_id"] for c in selected if c["case_id"] not in all_rows or not qualifications[c["case_id"]]["eligible"]]
        if missing:
            raise ValueError(f"Replication cannot materialize the preregistered primary subset: {missing}")
    rows = [row for case in selected for row in all_rows[case["case_id"]]]
    _assert_unchanged_implementation()
    manifest = {"schema_version": 2, "response_contract_version": RESPONSE_CONTRACT_VERSION,
                "stage": stage, "status": "prepared_not_frozen",
                "implementation_sha256": _LOADED_IMPLEMENTATION,
                "protocol_sha256": digest(protocol), "tokenizer_identity": token_identity,
                "source_pack_rule": SOURCE_PACK_RULE, "model_edge_rule": MODEL_EDGE_RULE,
                "token_method": "tokenizer" if token_counter else "byte_upper_bound",
                "case_ids": [c["case_id"] for c in selected], "cases": len(selected), "contexts": len(rows),
                "selection_sha256": digest([c["case_id"] for c in selected]), "contexts_sha256": digest(rows),
                "shortfalls": selection["shortfalls"], "exclusions": selection["exclusions"],
                "sampling_seeds": protocol["sampling_seeds_replication" if stage == "replication" else "sampling_seeds_primary"],
                "selection_uses_gold": False}
    prior = output / "contexts.jsonl"
    if prior.exists() and digest(read_jsonl(prior)) != digest(rows):
        raise ValueError("Refusing to overwrite different existing contexts; use a versioned output directory")
    write_jsonl(output / "contexts.jsonl", rows)
    write_json(output / "manifest.json", manifest)
    write_json(output / "qualification.json", qualifications)
    return manifest


def freeze_protocol(protocol: dict, pilot_directory: str | Path, output: str | Path) -> dict:
    """Refuse to bless a mock pilot, incomplete arms, or approximate counts as a freeze."""
    pilot = Path(pilot_directory)
    manifest = read_json(pilot / "manifest.json")
    contexts = read_jsonl(pilot / "contexts.jsonl")
    records = read_jsonl(pilot / "records.jsonl")
    if (protocol.get("schema_version") != 2 or protocol.get("response_contract_version") != RESPONSE_CONTRACT_VERSION
            or manifest.get("schema_version") != 2 or manifest.get("response_contract_version") != RESPONSE_CONTRACT_VERSION
            or any(c.get("response_contract_version") != RESPONSE_CONTRACT_VERSION for c in contexts)):
        raise ValueError("Freeze requires fresh contexts and protocol for response contract v2")
    if manifest["stage"] != "pilot" or manifest["token_method"] != "tokenizer":
        raise ValueError("Freeze requires a pilot with exact model-tokenizer counts")
    if manifest["protocol_sha256"] != digest(protocol) or manifest["contexts_sha256"] != digest(contexts):
        raise ValueError("Pilot contexts or protocol changed")
    if manifest.get("implementation_sha256") != implementation_sha256():
        raise ValueError("Implementation changed since pilot context preparation")
    actual_cases = sorted({c["case_id"] for c in contexts})
    if (len(actual_cases) != protocol["pilot_issues"] or manifest["cases"] != len(actual_cases)
            or manifest["contexts"] != len(contexts) or sorted(manifest["case_ids"]) != actual_cases
            or manifest["selection_sha256"] != digest(manifest["case_ids"])):
        raise ValueError("Pilot cohort manifest differs from actual required development cases")
    for identity in actual_cases:
        arms = [c for c in contexts if c["case_id"] == identity]
        if (sorted(c["condition"] for c in arms) != sorted(protocol["conditions"])
                or len({c["source_sha256"] for c in arms}) != 1
                or any(c["repo"] not in protocol["development_repositories"] for c in arms)):
            raise ValueError("Pilot requires all six matched arms from development repositories")
    if not records or any(r.get("synthetic") or r.get("backend") == "mock" for r in records):
        raise ValueError("Synthetic/mock outputs cannot satisfy the scientific freeze gate")
    expected = {(c["case_id"], c["condition"], seed) for c in contexts for seed in protocol["sampling_seeds_primary"]}
    context_by_arm = {(c["case_id"], c["condition"]): c for c in contexts}
    if len(context_by_arm) != len(contexts):
        raise ValueError("Duplicate pilot contexts")
    backend_fingerprints, generation_fingerprints = set(), set()
    required_generation = {"max_output_tokens": protocol["max_output_tokens"], "temperature": protocol["temperature"],
                           "thinking": False, "timeout_seconds": protocol["timeout_seconds"]}
    for record in records:
        if record.get("schema_version") != RECORD_SCHEMA_VERSION or record.get("response_contract_version") != RESPONSE_CONTRACT_VERSION:
            raise ValueError("Freeze requires fresh response-contract v2 records; legacy pilot outputs cannot be reused")
        arm = context_by_arm.get((record["case_id"], record["condition"]))
        if arm is None or record.get("context_sha256") != arm["context_sha256"] or record.get("source_sha256") != arm["source_sha256"]:
            raise ValueError("Stale or foreign pilot record: context/source hashes do not match")
        validate_record_prediction(record, arm)
        if hashlib.sha256(arm["prompt"].encode("utf-8")).hexdigest() != arm["context_sha256"]:
            raise ValueError("Pilot prompt hash mismatch")
        backend = record.get("backend", {})
        if backend.get("name") not in {"transformers", "llama_cpp"}:
            raise ValueError("Pilot needs an identified real local inference backend")
        if not (backend.get("resolved_revision") or backend.get("checkpoint_sha256") or backend.get("model_sha256")):
            raise ValueError("Pilot backend has no immutable checkpoint fingerprint")
        if not manifest.get("tokenizer_identity") or backend.get("tokenizer_sha256") != manifest["tokenizer_identity"]:
            raise ValueError("Pilot tokenizer identity differs from context preparation")
        backend_fingerprints.add(digest(backend))
        generation_fingerprints.add(digest(record.get("generation")))
        if record.get("generation") != required_generation:
            raise ValueError("Pilot generation configuration differs from the protocol")
        measured = record.get("input_tokens")
        if type(measured) is not int or measured != arm["input_tokens"] or measured > protocol["max_input_tokens"]:
            raise ValueError("Pilot runtime token count differs from frozen context or exceeds budget")
        output_tokens = record.get("output_tokens")
        if output_tokens is not None and (type(output_tokens) is not int or output_tokens > protocol["max_output_tokens"]):
            raise ValueError("Pilot output token budget exceeded")
        if (record.get("error_kind") == "out_of_memory"
                or "out of memory" in str(record.get("error", "")).lower()):
            raise ValueError("Pilot memory fitting failed")
    if len(backend_fingerprints) != 1 or len(generation_fingerprints) != 1:
        raise ValueError("Pilot contains mixed runtime or generation fingerprints")
    latest = {(r["case_id"], r["condition"], r["seed"]): r for r in records}
    if len(latest) != len(records) or set(latest) != expected:
        raise ValueError("Pilot is incomplete; every arm and sampling seed is required")
    attempted = [latest[key] for key in sorted(expected)]
    parse_rate = sum(r["status"] in {"ok", "invalid_prediction"} and r.get("contract_parseable") is True for r in attempted) / len(attempted)
    if parse_rate < protocol["pilot_minimum_parse_rate"]:
        raise ValueError(f"Parse success {parse_rate:.1%} is below pilot threshold")
    for condition in protocol["conditions"]:
        failures = {r["case_id"] for r in attempted if r["condition"] == condition and r["status"] == "timeout"}
        if len(failures) > protocol["pilot_maximum_timeout_issues_per_condition"]:
            raise ValueError(f"Timeout gate failed for {condition}: {len(failures)} issues")
    clean = [r for r in attempted if r["condition"] == "clean"]
    citation_rate = sum(r["status"] in {"ok", "invalid_prediction"} and bool(r.get("valid_graph_citations")) for r in clean) / len(clean)
    if citation_rate < protocol["pilot_minimum_graph_citation_rate"]:
        raise ValueError("Graph evidence rarely used; revise development task presentation before freezing")
    models = {r["model_name"] for r in attempted}
    if len(models) != 1:
        raise ValueError("Freeze requires one consistent primary model")
    frozen = {"schema_version": 2, "response_contract_version": RESPONSE_CONTRACT_VERSION,
              "status": "frozen", "protocol": protocol,
              "implementation_sha256": implementation_sha256(),
              "protocol_sha256": digest(protocol), "pilot_manifest_sha256": digest(manifest),
              "pilot_records_sha256": record_digest(records), "pilot_records_digest_rule": RECORD_DIGEST_RULE,
              "pilot_records_file_sha256": hashlib.sha256((pilot / "records.jsonl").read_bytes()).hexdigest(),
              "primary_model": next(iter(models)),
              "parse_rate": parse_rate, "contract_parse_rate": parse_rate, "graph_citation_rate": citation_rate,
              "within_budget_contract_parse_rate": parse_rate,
              "observed_contract_parse_rate": sum(r["contract_parseable"] for r in attempted) / len(attempted),
              "invalid_prediction_rate": sum(r.get("invalid_prediction", False) for r in attempted) / len(attempted),
              "tokenizer_identity": manifest["tokenizer_identity"], "backend_sha256": next(iter(backend_fingerprints))}
    output = Path(output)
    if output.exists() and read_json(output) != frozen:
        raise ValueError("Refusing to overwrite an existing different freeze; create a new protocol version")
    write_json(output, frozen)
    return frozen
