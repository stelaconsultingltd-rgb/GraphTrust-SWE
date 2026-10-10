"""Small, reproducible command interface; no implicit remote publishing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io import read_json, read_jsonl, write_json, write_jsonl


def tokenizer_counter(model: str):
    from transformers import AutoTokenizer
    from .inference import tokenizer_fingerprint
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=Path(model).exists())
    def count(text: str) -> int:
        # Include the exact Gemma chat framing for full prompt accounting.
        rendered = tokenizer.apply_chat_template([{"role": "user", "content": [{"type": "text", "text": text}]}],
                   tokenize=False, add_generation_prompt=True, enable_thinking=False)
        return len(tokenizer.encode(rendered, add_special_tokens=False))
    count.tokenizer_identity = tokenizer_fingerprint(tokenizer)
    return count


def _protocol(args) -> dict:
    protocol = read_json(args.protocol or Path(__file__).parent / "resources" / "protocol.json")
    for arg, key in (("pack_budget", "max_source_tokens"), ("input_budget", "max_input_tokens")):
        value = getattr(args, arg, None)
        if value is not None:
            protocol[key] = value
    return protocol


def _print(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="graphtrust", description="GraphTrust-SWE controlled graph-evidence benchmark")
    parser.add_argument("--protocol", help="Protocol JSON; defaults to the bundled v1 development protocol")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="Acquire revision-pinned public SWE-bench Lite")
    fetch.add_argument("--out", default="data/swebench-lite")
    fetch.add_argument("--revision")
    prepare = commands.add_parser("prepare", help="Build CPU graphs and intervention diagnostics; resumable")
    prepare.add_argument("--data", default="data/swebench-lite")
    prepare.add_argument("--out", default="runs/cpu")
    prepare.add_argument("--split", choices=["dev", "test", "all"], default="all")
    prepare.add_argument("--limit", type=int)
    prepare.add_argument("--workers", type=int, default=3)
    contexts = commands.add_parser("contexts", help="Materialize fixed-source six-arm contexts, without gold")
    contexts.add_argument("--data", default="data/swebench-lite")
    contexts.add_argument("--prepared", default="runs/cpu")
    contexts.add_argument("--out", default="runs/pilot")
    contexts.add_argument("--stage", choices=["pilot", "holdout", "replication"], default="pilot")
    contexts.add_argument("--tokenizer", help="Pinned local Gemma tokenizer or HF repository; required for scientific freeze")
    contexts.add_argument("--tokenizer-backend", choices=["transformers", "gguf"], default="transformers")
    contexts.add_argument("--pack-budget", type=int)
    contexts.add_argument("--input-budget", type=int)
    contexts.add_argument("--freeze", default="runs/protocol-frozen.json")
    contexts.add_argument("--primary-manifest", default="runs/holdout/manifest.json")
    infer = commands.add_parser("infer", help="Run inference with persistent per-attempt accounting")
    infer.add_argument("--contexts", required=True)
    infer.add_argument("--out", required=True)
    infer.add_argument("--backend", choices=["transformers", "gguf", "mock"], required=True)
    infer.add_argument("--model", required=True)
    infer.add_argument("--seeds", default="17,42")
    infer.add_argument("--max-calls", type=int)
    infer.add_argument("--freeze", default="runs/protocol-frozen.json")
    report = commands.add_parser("report", help="Score evaluator-only reference edits and reproduce figures")
    report.add_argument("--records", required=True)
    report.add_argument("--contexts", required=True)
    report.add_argument("--gold", required=True)
    report.add_argument("--out", required=True)
    freeze = commands.add_parser("freeze", help="Freeze only after a complete real, exact-tokenizer pilot passes gates")
    freeze.add_argument("--pilot", default="runs/pilot")
    freeze.add_argument("--out", default="runs/protocol-frozen.json")
    validate = commands.add_parser("validate", help="Verify manifest and six-arm source invariance")
    validate.add_argument("--directory", required=True)
    demo = commands.add_parser("demo", help="Run the offline synthetic demo; NEVER research results")
    demo.add_argument("--out", default="runs/demo")
    demo.add_argument("--fixtures", default=str(Path(__file__).parent / "resources" / "synthetic"))
    args = parser.parse_args(argv)

    if args.command == "fetch":
        from .corpus import fetch_corpus
        _print(fetch_corpus(args.out, args.revision))
    elif args.command == "prepare":
        from .pipeline import prepare_cases
        from .corpus import validate_corpus
        validate_corpus(args.data)
        cases = read_jsonl(Path(args.data) / "cases.jsonl")
        if args.split != "all":
            cases = [c for c in cases if c["split"] == args.split]
        if args.limit is not None:
            cases = cases[:args.limit]
        _print(prepare_cases(cases, args.data, args.out, _protocol(args), args.workers))
    elif args.command == "contexts":
        from .pipeline import create_contexts
        from .corpus import validate_corpus
        validate_corpus(args.data)
        from .io import digest
        if args.stage != "pilot":
            frozen = read_json(args.freeze)
            from .provenance import implementation_sha256
            if frozen["status"] != "frozen" or frozen["protocol_sha256"] != digest(_protocol(args)):
                raise ValueError("Holdout preparation requires a matching scientifically frozen protocol")
            if frozen.get("implementation_sha256") != implementation_sha256():
                raise ValueError("Implementation differs from the pilot freeze")
        if args.tokenizer and args.tokenizer_backend == "gguf":
            from .inference import LlamaCppBackend
            tokenizer_backend = LlamaCppBackend(args.tokenizer, n_gpu_layers=0)
            counter = tokenizer_backend.count_tokens
            token_identity = tokenizer_backend.identity["tokenizer_sha256"]
        else:
            counter = tokenizer_counter(args.tokenizer) if args.tokenizer else None
            token_identity = counter.tokenizer_identity if counter else None
        primary = read_json(args.primary_manifest) if args.stage == "replication" else None
        _print(create_contexts(read_jsonl(Path(args.data) / "cases.jsonl"), args.prepared, args.out,
                               _protocol(args), args.stage, counter, token_identity, primary))
    elif args.command == "infer":
        from .inference import LlamaCppBackend, MockBackend, TransformersBackend, run_contexts
        from .io import digest
        from .provenance import implementation_sha256
        protocol = _protocol(args)
        rows = read_jsonl(args.contexts)
        manifest = None
        if args.backend != "mock":
            manifest = read_json(Path(args.contexts).parent / "manifest.json")
            if (manifest["contexts_sha256"] != digest(rows) or manifest["protocol_sha256"] != digest(protocol)
                    or manifest.get("implementation_sha256") != implementation_sha256()
                    or manifest.get("token_method") != "tokenizer"):
                raise ValueError("Real inference requires current, exact, checksum-verified context artifacts")
            if [int(s) for s in args.seeds.split(",")] != manifest["sampling_seeds"]:
                raise ValueError("Sampling seeds differ from the context manifest")
        if args.backend == "transformers":
            backend = TransformersBackend(args.model)
        elif args.backend == "gguf":
            backend = LlamaCppBackend(args.model)
        else:
            backend = MockBackend()
        if manifest is not None:
            if backend.identity["tokenizer_sha256"] != manifest["tokenizer_identity"]:
                raise ValueError("Inference tokenizer differs from context preparation")
            if any(backend.count_tokens(row["prompt"]) != row["input_tokens"] for row in rows):
                raise ValueError("Runtime tokenizer counts differ from stored exact counts")
            if manifest["stage"] == "holdout":
                frozen = read_json(args.freeze)
                if (frozen.get("status") != "frozen" or frozen["protocol_sha256"] != digest(protocol)
                        or frozen.get("implementation_sha256") != implementation_sha256()
                        or frozen["backend_sha256"] != digest(backend.identity)):
                    raise ValueError("Primary holdout backend differs from the accepted pilot freeze")
        _print(run_contexts(rows, args.out, backend,
                            [int(s) for s in args.seeds.split(",")], args.model,
                            max_output_tokens=protocol["max_output_tokens"],
                            timeout_seconds=protocol["timeout_seconds"], temperature=protocol["temperature"],
                            max_calls=args.max_calls))
    elif args.command == "report":
        from .metrics import evaluate_runs, write_report
        gold = {r["case_id"]: r["files"] for r in read_jsonl(args.gold)}
        _print(write_report(evaluate_runs(read_jsonl(args.records), gold, read_jsonl(args.contexts)), args.out))
    elif args.command == "freeze":
        from .pipeline import freeze_protocol
        _print(freeze_protocol(_protocol(args), args.pilot, args.out))
    elif args.command == "validate":
        from .io import digest
        directory = Path(args.directory)
        manifest = read_json(directory / "manifest.json")
        rows = read_jsonl(directory / "contexts.jsonl")
        if manifest["contexts_sha256"] != digest(rows):
            raise ValueError("Context artifact checksum mismatch")
        groups = {}
        for row in rows:
            groups.setdefault(row["case_id"], []).append(row)
            if any(word in row["prompt"] for word in ("known_false_edge_ids", "test_patch", '"patch":')):
                raise ValueError("Evaluator-only label marker detected in prompt")
        for case_id, arms in groups.items():
            if len({a["source_sha256"] for a in arms}) != 1:
                raise ValueError(f"Source mismatch for {case_id}")
            if sorted(a["condition"] for a in arms) != sorted(_protocol(args)["conditions"]):
                raise ValueError(f"Missing/duplicate arms for {case_id}")
        _print({"valid": True, "issues": len(groups), "contexts": len(rows), "token_method": manifest["token_method"]})
    elif args.command == "demo":
        run_demo(args.fixtures, args.out, _protocol(args))


def run_demo(fixtures: str | Path, output: str | Path, protocol: dict) -> None:
    from .graph import build_graph
    from .inference import MockBackend, run_contexts
    from .io import digest
    from .metrics import evaluate_runs, write_report
    from .pipeline import materialize_case, save_graph

    output = Path(output)
    protocol = {**protocol, "max_source_tokens": 10000, "max_input_tokens": 16000, "max_relation_tokens": 4000}
    case = {"case_id": "synthetic-whitespace", "repo": "graphtrust/synthetic", "commit": "synthetic",
            "split": "dev", "issue_text": "Whitespace around a string should be normalized before storage. Inspect normalize and process."}
    graph = build_graph(fixtures, commit="synthetic")
    rows, qualification = materialize_case(case, graph, protocol)
    if not qualification["eligible"]:
        raise ValueError(f"Synthetic fixture failed structural qualification: {qualification}")
    if (output / "contexts.jsonl").exists() and digest(read_jsonl(output / "contexts.jsonl")) != digest(rows):
        raise ValueError("Demo contexts changed; use a new output directory to preserve old evidence")
    write_jsonl(output / "contexts.jsonl", rows)
    save_graph(output / "graph.json.gz", graph)
    write_json(output / "qualification.json", qualification)
    write_json(output / "manifest.json", {"stage": "synthetic_demo", "status": "synthetic_only",
                "cases": 1, "contexts": len(rows), "contexts_sha256": digest(rows),
                "token_method": "byte_upper_bound", "protocol_sha256": digest(protocol)})
    run_contexts(rows, output / "records.jsonl", MockBackend(), [17, 42], "synthetic-mock")
    scored = evaluate_runs(read_jsonl(output / "records.jsonl"), {case["case_id"]: ["normalize.py", "app.py"]}, rows)
    summary = write_report(scored, output / "report")
    _print({"status": "synthetic_demo_only", "contexts": len(rows), "attempts": len(scored),
            "source_identical": len({r["source_sha256"] for r in rows}) == 1,
            "report": str(output / "report" / "REPORT.md"), "summary_models": list(summary.get("models", {}))})
