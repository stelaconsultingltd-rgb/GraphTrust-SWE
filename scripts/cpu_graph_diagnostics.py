"""Standalone full-snapshot CPU diagnostics; never constructs model contexts.

Uses the existing extractor/intervention/checker APIs without changing their
implementation or the model protocol. Run after preparation, or explicitly
request a partial audit. No reference patches, labels or models are loaded.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time

from graphtrust.interventions import check_edges, perturb_graph
from graphtrust.io import digest, read_json, write_json
from graphtrust.pipeline import load_graph
from graphtrust.provenance import extractor_sha256, implementation_sha256

SCRIPT = Path(__file__).resolve()
SCHEMA = 2


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def peak_rss_bytes() -> int | None:
    """Process-lifetime high-water mark, not independent per-variant memory."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ("peak", "working", "peak_paged",
                    "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            get_process = ctypes.windll.kernel32.GetCurrentProcess
            get_process.restype = wintypes.HANDLE
            get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
            get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if get_memory(get_process(), ctypes.byref(counters), counters.cb):
                return int(counters.peak)
            return None
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)
    except (ImportError, OSError, AttributeError):
        return None


def adjacency(graph: dict) -> dict[str, set[str]]:
    result = defaultdict(set)
    for edge in graph["edges"]:
        result[edge["source"]].add(edge["target"])
    return result


def reach(adjacency_map: dict, source: str) -> set[str]:
    targets = set(adjacency_map.get(source, ()))
    for target in tuple(targets):
        targets.update(adjacency_map.get(target, ()))
    targets.discard(source)
    return targets


def topology_metrics(original: dict, observed: dict, anchors: list[str]) -> dict:
    reference, changed = adjacency(original), adjacency(observed)
    results = []
    for source in anchors:
        a, b = reach(reference, source), reach(changed, source)
        results.append({"anchor": source, "reference_reachable": len(a),
                        "observed_reachable": len(b), "intersection": len(a & b),
                        "union": len(a | b), "two_hop_jaccard": len(a & b) / len(a | b) if a | b else 1.0,
                        "two_hop_recall": len(a & b) / len(a) if a else 1.0})
    return {"anchor_count": len(anchors), "queries": results,
            "mean_two_hop_jaccard": sum(r["two_hop_jaccard"] for r in results) / len(results) if results else None,
            "mean_two_hop_recall": sum(r["two_hop_recall"] for r in results) / len(results) if results else None}


def diagnose_graph(graph: dict, protocol: dict) -> dict:
    started = time.perf_counter()
    original_hash = digest(graph)
    source_hash = digest({"snapshot": graph["snapshot"], "nodes": graph["nodes"]})
    source_degrees = Counter(e["source"] for e in graph["edges"])
    target_degrees = Counter(e["target"] for e in graph["edges"])
    supported = {(e["source"], e["target"], e["type"]) for e in graph["edges"] if e.get("resolution") == "supported"}
    anchors = sorted(source_degrees, key=lambda node: digest({"snapshot": graph["snapshot"]["source_sha256"], "node": node}))[:64]
    clean_verdicts = Counter(check_edges(graph, graph).values())
    variants = []
    for seed in protocol["corruption_seeds_cpu"]:
        for severity in protocol["severity_cpu"]:
            for kind in ("delete", "rewire"):
                step = time.perf_counter()
                observed, sidecar = perturb_graph(graph, kind, severity, seed, source_graph=graph)
                intervention_seconds = time.perf_counter() - step
                by_id = {edge["id"]: edge for edge in observed["edges"]}
                false = [by_id[edge_id] for edge_id in sidecar["false_edge_ids"]]
                invariant = digest({"snapshot": observed["snapshot"], "nodes": observed["nodes"]}) == source_hash
                guard = all((e["source"], e["target"], e["type"]) not in supported and e["source"] != e["target"] for e in false)
                degrees_unchanged = (Counter(e["source"] for e in observed["edges"]) == source_degrees and
                                     Counter(e["target"] for e in observed["edges"]) == target_degrees)
                correct_count = (len(graph["edges"]) - len(observed["edges"]) == sidecar["achieved_edge_count"] if kind == "delete"
                                 else len(graph["edges"]) == len(observed["edges"]) and len(false) == sidecar["achieved_edge_count"])
                if not (invariant and guard and correct_count and (kind != "rewire" or degrees_unchanged)):
                    raise ValueError("Full-graph intervention invariant failed")
                verdicts = check_edges(observed, graph)
                variants.append({"sidecar": sidecar, "source_and_nodes_unchanged": invariant,
                                 "full_source_false_relation_guard": guard,
                                 "degree_sequences_unchanged": degrees_unchanged,
                                 "checker_status_counts": dict(sorted(Counter(verdicts.values()).items())),
                                 "false_edge_checker_counts": dict(sorted(Counter(verdicts[e["id"]] for e in false).items())),
                                 "intervention_seconds": intervention_seconds,
                                 "topology": topology_metrics(graph, observed, anchors),
                                 "total_diagnostic_seconds": time.perf_counter() - step,
                                 "process_lifetime_peak_rss_bytes": peak_rss_bytes()})
                del observed
    if digest(graph) != original_hash:
        raise ValueError("Input graph changed during diagnostics")
    return {"graph_sha256": original_hash, "source_and_nodes_sha256": source_hash,
            "nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
            "unknown_bindings": len(graph.get("unknown", [])), "parse_errors": graph.get("errors", []),
            "clean_checker_status_counts": dict(sorted(clean_verdicts.items())), "anchors": anchors,
            "variants": variants, "elapsed_seconds": time.perf_counter() - started,
            "process_lifetime_peak_rss_bytes": peak_rss_bytes()}


def validate_header(record: dict, prepared: Path, identity: dict) -> Path:
    if record.get("status") != "ok" or record.get("preparation_schema_version") != 2:
        raise ValueError("Preparation record is not a successful schema-2 artifact")
    if record.get("implementation_sha256") != identity["implementation_sha256"]:
        raise ValueError("Preparation implementation differs from current code")
    if record.get("protocol_sha256") != identity["protocol_sha256"]:
        raise ValueError("Preparation protocol differs from requested protocol")
    path = (prepared / record["graph_path"]).resolve()
    if not path.is_relative_to(prepared.resolve()):
        raise ValueError("Graph path escapes prepared directory")
    if file_hash(path) != record["graph_file_sha256"]:
        raise ValueError("Graph bytes differ from preparation record")
    return path


def validate_graph_identity(record: dict, graph: dict, identity: dict) -> None:
    if (graph.get("extractor_sha256") != identity["extractor_sha256"] or
        graph["snapshot"]["commit"] != record["commit"] or
        graph["snapshot"]["source_sha256"] != record["snapshot_sha256"]):
        raise ValueError("Graph extractor/commit/source identity differs from preparation")


def validate_record(record: dict, prepared: Path, identity: dict) -> tuple[Path, dict]:
    path = validate_header(record, prepared, identity)
    graph = load_graph(path)
    validate_graph_identity(record, graph, identity)
    return path, graph


def scientific_payload(value):
    """Canonical scientific content, excluding measured execution and its hashes.

    RSS is execution-dependent even though it is not a duration. Full artifact
    hashes still protect the actual timing/RSS records; this separate projection
    permits exact serial/parallel comparison of scientific fields.
    """
    omitted = {"elapsed_seconds", "intervention_seconds", "total_diagnostic_seconds",
               "process_lifetime_peak_rss_bytes", "result_sha256", "scientific_sha256",
               "diagnostic_file_sha256"}
    if isinstance(value, dict):
        return {key: scientific_payload(item) for key, item in value.items() if key not in omitted}
    if isinstance(value, list):
        return [scientific_payload(item) for item in value]
    return value


def assert_inputs_unchanged(identity: dict, protocol_path: Path, case_manifest: Path | None) -> None:
    if (identity["schema_version"] != SCHEMA or file_hash(SCRIPT) != identity["script_sha256"] or
        implementation_sha256() != identity["implementation_sha256"] or
        extractor_sha256() != identity["extractor_sha256"] or
        digest(read_json(protocol_path)) != identity["protocol_sha256"] or
        (case_manifest is not None and file_hash(case_manifest) != identity["public_case_manifest_sha256"])):
        raise RuntimeError("Inputs or executable identity changed during diagnostics")


def validate_result(result: dict, graph: dict, identity: dict, graph_key: str) -> None:
    if (result.get("schema_version") != SCHEMA or result.get("identity_sha256") != digest(identity) or
        result.get("input_graph_file_sha256") != graph_key or result.get("graph_sha256") != digest(graph) or
        len(result.get("variants", [])) != 18 or result.get("scientific_sha256") != digest(scientific_payload(result)) or
        result.get("result_sha256") != digest({k: v for k, v in result.items() if k != "result_sha256"})):
        raise ValueError("Cached diagnostic identity differs or variants are incomplete")


def graph_job(records: list[dict], prepared: str, protocol_path: str, case_manifest: str | None,
              identity: dict, cached_path: str) -> dict:
    """One independent graph job; workers never write shared artifacts."""
    prepared, protocol_path = Path(prepared), Path(protocol_path)
    case_manifest = Path(case_manifest) if case_manifest else None
    assert_inputs_unchanged(identity, protocol_path, case_manifest)
    path, graph = validate_record(records[0], prepared, identity)
    for record in records[1:]:
        validate_header(record, prepared, identity)
        validate_graph_identity(record, graph, identity)
    graph_key = records[0]["graph_file_sha256"]
    cached_path = Path(cached_path)
    reused = cached_path.exists()
    if reused:
        result = read_json(cached_path)
    else:
        result = {**diagnose_graph(graph, read_json(protocol_path)), "schema_version": SCHEMA,
                  "identity_sha256": digest(identity), "input_graph_file_sha256": graph_key,
                  "commit": graph["snapshot"]["commit"], "scope": identity["scope"],
                  "synthetic": identity["synthetic"]}
        result["scientific_sha256"] = digest(scientific_payload(result))
        result["result_sha256"] = digest(result)
    validate_result(result, graph, identity, graph_key)
    assert_inputs_unchanged(identity, protocol_path, case_manifest)
    for record in records:
        validate_header(record, prepared, identity)
    return {"result": result, "reused": reused, "validation_process_id": os.getpid()}


def execution_event(output: Path, event: dict) -> None:
    # Only the parent writes this append-only journal. It is deliberately outside
    # scientific identity: changing worker count does not invalidate resumption.
    with (output / "EXECUTIONS.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        stream.flush()


def run(prepared: Path, output: Path, protocol_path: Path, *, expected_cases: int = 300,
        allow_partial: bool = False, case_ids: list[str] | None = None, synthetic: bool = False,
        case_manifest: Path | None = None, workers: int = 1) -> dict:
    protocol = read_json(protocol_path)
    if protocol["corruption_seeds_cpu"] != [1729, 2718, 3141] or protocol["severity_cpu"] != [0.1, 0.3, 0.5]:
        raise ValueError("This version requires the registered three CPU seeds and three severities")
    if expected_cases <= 0:
        raise ValueError("expected_cases must be positive")
    if not isinstance(workers, int) or isinstance(workers, bool) or workers <= 0:
        raise ValueError("workers must be a positive integer")
    if case_manifest is None and not synthetic:
        case_manifest = SCRIPT.parent.parent / "docs/DATASET_MANIFEST.json"
    public_cases = {r["case_id"]: r for r in read_json(case_manifest)["cases"]} if case_manifest else {}
    identity = {"schema_version": SCHEMA, "scope": "full_source_snapshot_supported_relations",
                "script_sha256": file_hash(SCRIPT), "implementation_sha256": implementation_sha256(),
                "extractor_sha256": extractor_sha256(), "protocol_sha256": digest(protocol),
                "expected_cases": expected_cases, "case_ids_filter": sorted(case_ids or []),
                "synthetic": synthetic, "public_case_manifest_sha256": file_hash(case_manifest) if case_manifest else None,
                "topology_query_rule": "64_hash_ordered_callers_two_hop_outgoing_v1"}
    output.mkdir(parents=True, exist_ok=True)
    identity_path = output / "IDENTITY.json"
    if identity_path.exists() and read_json(identity_path) != identity:
        raise ValueError("Output identity differs; use a new versioned output directory")
    write_json(identity_path, identity)
    started = time.perf_counter()
    execution_id = digest({"time_ns": time.time_ns(), "process_id": os.getpid()})
    execution_event(output, {"event": "start", "execution_id": execution_id, "workers": workers,
                            "parent_process_id": os.getpid(), "identity_sha256": digest(identity)})
    rows, failures, completed, aggregates = [], [], set(), defaultdict(list)
    groups, results, errors = {}, {}, {}
    records = [read_json(path) for path in sorted((prepared / "cases").glob("*.json"))]
    if case_ids:
        records = [r for r in records if r.get("case_id") in set(case_ids)]
    if len({r.get("case_id") for r in records}) != len(records):
        raise ValueError("Duplicate issue IDs in prepared records")
    for index, record in enumerate(records, 1):
        try:
            if public_cases:
                public = public_cases.get(record["case_id"])
                if not public or any(record.get(k) != public[k] for k in ("repo", "commit", "split")) or record.get("case_sha256") != public["public_case_sha256"]:
                    raise ValueError("Preparation case identity differs from public dataset manifest")
            validate_header(record, prepared, identity)
            graph_key = record["graph_file_sha256"]
            # Send only the fields needed to validate this issue's graph. The
            # preparation's packed diagnostics never cross the process boundary.
            job_record = {key: record[key] for key in ("case_id", "status", "preparation_schema_version",
                          "implementation_sha256", "protocol_sha256", "graph_path", "graph_file_sha256",
                          "commit", "snapshot_sha256")}
            groups.setdefault(graph_key, []).append(job_record)
        except Exception as exc:
            errors[record.get("case_id")] = f"{type(exc).__name__}: {exc}"

    def arguments(graph_key):
        return (groups[graph_key], str(prepared), str(protocol_path), str(case_manifest) if case_manifest else None,
                identity, str(output / "graphs" / (graph_key + ".json")))

    def accept(graph_key, outcome=None, error=None):
        if error is not None:
            for item in groups[graph_key]:
                errors[item["case_id"]] = f"{type(error).__name__}: {error}"
            execution_event(output, {"event": "graph_error", "execution_id": execution_id,
                                    "graph_key": graph_key, "error": f"{type(error).__name__}: {error}"})
        else:
            assert_inputs_unchanged(identity, protocol_path, case_manifest)
            path = output / "graphs" / (graph_key + ".json")
            result = outcome["result"]
            if outcome["reused"]:
                if read_json(path) != result:
                    raise RuntimeError("Cached diagnostic changed during validation")
            else:
                write_json(path, result)
            # Keep small aggregation/mapping data, not all per-query records.
            aggregate_variants = [{"sidecar": {field: v["sidecar"][field] for field in
                                   ("kind", "requested_severity", "seed", "achieved_severity", "achieved_edge_count")},
                                   "topology": {"mean_two_hop_jaccard": v["topology"]["mean_two_hop_jaccard"]},
                                   "total_diagnostic_seconds": v["total_diagnostic_seconds"]}
                                  for v in result["variants"]]
            results[graph_key] = {"variants": aggregate_variants, "scientific_sha256": result["scientific_sha256"],
                                  "file_sha256": file_hash(path)}
            execution_event(output, {"event": "graph_validated", "execution_id": execution_id,
                                    "graph_key": graph_key, "reused": outcome["reused"],
                                    "validation_process_id": outcome["validation_process_id"]})
        print(f"[{len(results) + sum(any(i['case_id'] in errors for i in group) for group in groups.values())}/{len(groups)} graphs] {graph_key}: {'error' if error else 'ok'}", flush=True)

    if workers == 1:
        for graph_key in groups:
            try:
                accept(graph_key, graph_job(*arguments(graph_key)))
            except Exception as exc:
                accept(graph_key, error=exc)
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            remaining, pending = iter(groups), {}
            def submit_next():
                graph_key = next(remaining, None)
                while graph_key is not None:
                    try:
                        pending[pool.submit(graph_job, *arguments(graph_key))] = graph_key
                        break
                    except Exception as exc:
                        accept(graph_key, error=exc)
                        graph_key = next(remaining, None)
            for _ in range(min(workers, len(groups))):
                submit_next()
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    graph_key = pending.pop(future)
                    try:
                        accept(graph_key, future.result())
                    except Exception as exc:
                        accept(graph_key, error=exc)
                    submit_next()

    # Preserve deterministic first-occurrence order for floating-point sums,
    # independently of the process completion/scheduling order.
    assert_inputs_unchanged(identity, protocol_path, case_manifest)
    failures = [{"case_id": record.get("case_id"), "error": errors[record.get("case_id")]}
                for record in records if record.get("case_id") in errors]
    for graph_key in groups:
        if graph_key not in results:
            continue
        for variant in results[graph_key]["variants"]:
            side = variant["sidecar"]
            aggregates[(side["kind"], side["requested_severity"], side["seed"])].append({
                "achieved_severity": side["achieved_severity"], "changed": side["achieved_edge_count"],
                "jaccard": variant["topology"]["mean_two_hop_jaccard"], "elapsed": variant["total_diagnostic_seconds"]})
        completed.add(graph_key)
    for record in records:
        if record.get("case_id") in errors:
            continue
        graph_key = record["graph_file_sha256"]
        validate_header(record, prepared, identity)
        result = results[graph_key]
        sidecar_path = output / "graphs" / (graph_key + ".json")
        rows.append({"case_id": record["case_id"], "repo": record["repo"], "split": record["split"],
                     "commit": record["commit"], "case_sha256": record.get("case_sha256"), "graph_key": graph_key,
                     "diagnostic_path": str(sidecar_path.relative_to(output)).replace("\\", "/"),
                     "diagnostic_file_sha256": result["file_sha256"],
                     "diagnostic_scientific_sha256": result["scientific_sha256"], "uses_gold": False})
    expected_ids = {key for key, row in public_cases.items() if row["split"] == "test"}
    complete = (not synthetic and not case_ids and len(rows) == expected_cases == 300 and
                len(records) == expected_cases and not failures and {r["case_id"] for r in rows} == expected_ids)
    manifest = {"schema_version": SCHEMA, "identity": identity, "identity_sha256": digest(identity),
                "status": "complete_cpu_resource" if complete else "partial_cpu_diagnostics",
                "synthetic": synthetic, "attempted_cases": len(records), "successful_cases": len(rows),
                "expected_cases": expected_cases, "unique_graphs": len(completed), "failures": failures,
                "issue_graph_mapping": rows, "uses_gold": False,
                "interpretation": "Controlled metadata diagnostics, not model outcomes; duplicate snapshots are not independent observations. Checker uses the same lexical extractor as intervention provenance and is not independent semantic verification.",
                "memory_measurement": "Diagnostic-worker process-lifetime peak resident memory, dependent on execution and prior worker tasks; null means unavailable."}
    report_key = digest(manifest)
    write_json(output / "reports" / (report_key + ".json"), manifest)
    write_json(output / "MANIFEST.json", manifest)
    summary = {k: manifest[k] for k in ("status", "attempted_cases", "successful_cases", "expected_cases", "unique_graphs", "failures", "synthetic")}
    summary["aggregation_unit"] = "unique source graph; issue mappings do not add independent observations"
    summary["variant_grid"] = [{"kind": kind, "requested_severity": severity, "seed": seed,
        "unique_graph_count": len(values), "zero_change_graph_count": sum(v["changed"] == 0 for v in values),
        "mean_achieved_severity": sum(v["achieved_severity"] for v in values) / len(values),
        "minimum_achieved_severity": min(v["achieved_severity"] for v in values),
        "maximum_achieved_severity": max(v["achieved_severity"] for v in values),
        "mean_two_hop_jaccard": sum(v["jaccard"] for v in values if v["jaccard"] is not None) / len(nonempty) if (nonempty := [v for v in values if v["jaccard"] is not None]) else None,
        "total_diagnostic_seconds": sum(v["elapsed"] for v in values)} for (kind, severity, seed), values in sorted(aggregates.items())]
    write_json(output / "reports" / (digest(summary) + ".summary.json"), summary)
    write_json(output / "SUMMARY.json", summary)
    execution_event(output, {"event": "finish", "execution_id": execution_id, "workers": workers,
                            "status": summary["status"], "wall_seconds": time.perf_counter() - started,
                            "successful_cases": len(rows), "failed_cases": len(failures)})
    if not complete and not allow_partial:
        raise ValueError("Final CPU resource requires 300 valid test cases; report saved as partial. Use --allow-partial for development audits.")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--protocol", type=Path, default=SCRIPT.parent.parent / "configs/protocol.json")
    parser.add_argument("--expected-cases", type=int, default=300)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--case-ids", help="Comma-separated IDs for explicit partial verification only")
    parser.add_argument("--synthetic", action="store_true", help="Watermark synthetic verification; cannot be complete")
    parser.add_argument("--case-manifest", type=Path, help="Public answer-free dataset manifest; defaults to docs/DATASET_MANIFEST.json")
    parser.add_argument("--workers", type=int, default=1, help="Independent graph processes; default 1. Timing/RSS depend on execution.")
    args = parser.parse_args()
    print(json.dumps(run(args.prepared, args.out, args.protocol, expected_cases=args.expected_cases,
                         allow_partial=args.allow_partial, case_ids=args.case_ids.split(",") if args.case_ids else None,
                         synthetic=args.synthetic, case_manifest=args.case_manifest, workers=args.workers), indent=2))


if __name__ == "__main__":
    main()
