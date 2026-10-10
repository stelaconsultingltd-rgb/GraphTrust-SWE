"""Evaluator-only localization scoring and issue-level paired statistics.

This module uses the standard library. It never supplies gold labels or corruption
labels to a model. ``write_report`` optionally imports matplotlib for figures.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
from pathlib import Path, PurePosixPath
import random
import statistics
from typing import Any

METRICS = (
    "file_recall_at5", "hit_at5", "cited_false_edges", "abstain",
    "invalid_files", "invalid_source_ids", "invalid_edge_ids", "parse_error", "invalid_output", "timeout", "error",
    "graph_citations", "source_citations",
    "latency_seconds", "input_tokens", "output_tokens", "coverage_ceiling",
)
CONDITIONS = (
    "source_only", "clean", "deleted", "rewired", "clean_checked",
    "rewired_checked",
)


def _path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip().replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or ":" in value:
        return None
    return str(path) if str(path) != "." else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def evaluate_runs(
    records: list[dict], gold: dict[str, list[str]], context_metadata: list[dict],
) -> list[dict]:
    """Score every attempt, including failures, without dropping hard cases.

    Recall is the number of *distinct reference files* present in the first five
    predicted slots divided by the number of reference files. Invalid/duplicate
    slots are not replaced. Missing/empty gold has a null score, never a fabricated
    zero. Matching context metadata is required; corruption labels stay evaluator
    only. Explicit abstention earns zero localization credit even with file names.
    """
    contexts: dict[tuple[str, str], dict] = {}
    for context in context_metadata:
        key = (context["case_id"], context["condition"])
        if key in contexts and contexts[key] != context:
            raise ValueError(f"Conflicting context metadata: {key}")
        contexts[key] = context
    scored = []
    for index, record in enumerate(records):
        case_id, condition = record["case_id"], record["condition"]
        context = contexts.get((case_id, condition))
        if context is None:
            raise ValueError(f"Missing context metadata: {(case_id, condition)}")
        if (record.get("context_sha256") and context.get("context_sha256")
                and record["context_sha256"] != context["context_sha256"]):
            raise ValueError(f"Context hash mismatch: {case_id}/{condition}")
        if record.get("repo") and context.get("repo") and record["repo"] != context["repo"]:
            raise ValueError(f"Repository mismatch: {case_id}")
        visible = {_path(item) for item in context.get("visible_files", [])} - {None}
        visible_edges = set(context.get("visible_edge_ids", []))
        visible_sources = set(context.get("visible_source_ids", []))
        false_edges = set(context.get("known_false_edge_ids", []))
        if not false_edges <= visible_edges:
            raise ValueError(f"False-edge labels must refer to visible edges: {case_id}")
        reference = {_path(item) for item in gold.get(case_id, [])} - {None}
        status = record.get("status", "error")
        response = record.get("response", record.get("prediction"))
        malformed = status in {"ok", "invalid_output", "parse_error"} and (
            not isinstance(response, dict)
            or not _strings(response.get("files"))
            or not _strings(response.get("edge_ids", []))
            or not _strings(response.get("source_ids", []))
            or not isinstance(response.get("abstain", False), bool)
        )
        parsed = status in {"ok", "invalid_output", "parse_error"} and not malformed
        response = response if parsed else {}
        raw_files = response.get("files", [])
        paths = [_path(item) for item in raw_files]
        top5 = {item for item in paths[:5] if item in visible}
        abstain = bool(response.get("abstain", False))
        matches = len(top5 & reference) if status == "ok" and not abstain else 0
        edge_ids = set(response.get("edge_ids", []))
        source_ids = set(response.get("source_ids", []))
        configuration = {key: record[key] for key in ("backend", "generation") if key in record}
        scored.append({
            "record_index": index,
            "attempt_id": record.get("attempt_id", ""),
            "run_id": record.get("run_id", ""),
            "record_sha256": hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
            "case_id": case_id,
            "repo": record.get("repo", context.get("repo", "unspecified")),
            "condition": condition,
            "seed": record.get("seed", 0),
            "model_name": record.get("model_name", "unspecified"),
            "model_configuration_sha256": hashlib.sha256(json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()).hexdigest() if configuration else "unspecified",
            "context_sha256": record.get("context_sha256", context.get("context_sha256", "")),
            "source_sha256": record.get("source_sha256", context.get("source_sha256", "")),
            "synthetic": bool(record.get("synthetic", False)),
            "status": "parse_error" if malformed else status,
            "gold_present": bool(reference),
            "gold_file_count": len(reference),
            "reference_files": sorted(reference),
            "predicted_files": raw_files,
            "file_recall_at5": matches / len(reference) if reference else None,
            "hit_at5": float(matches > 0) if reference else None,
            "cited_false_edges": len(edge_ids & false_edges),
            "graph_citations": len(edge_ids & visible_edges),
            "source_citations": len(source_ids & visible_sources) if "visible_source_ids" in context else len(source_ids),
            "abstain": float(abstain),
            "invalid_files": sum(item not in visible for item in paths),
            "invalid_edge_ids": len(edge_ids - visible_edges),
            "invalid_source_ids": len(source_ids - visible_sources) if "visible_source_ids" in context else 0,
            "empty_prediction": float(parsed and not raw_files),
            "parse_error": float(status == "parse_error" or malformed),
            "invalid_output": float(status == "invalid_output"),
            "timeout": float(status == "timeout"),
            "error": float(status not in {"ok", "parse_error", "invalid_output", "timeout"}),
            "latency_seconds": _number(record.get("latency_seconds")),
            "input_tokens": _number(record.get("input_tokens")),
            "output_tokens": _number(record.get("output_tokens")),
            "source_file_coverage": len(visible & reference) / len(reference) if reference else None,
            "coverage_ceiling": min(5, len(visible & reference)) / len(reference) if reference else None,
        })
    return scored


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _issue_values(rows: list[dict], metric: str) -> dict[tuple[str, str], float]:
    groups: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        if row.get(metric) is not None:
            groups.setdefault((row["repo"], row["case_id"]), []).append(float(row[metric]))
    return {key: statistics.fmean(values) for key, values in groups.items()}


def _percentile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def _interval(values: dict[tuple[str, str], float], samples: int, seed: int) -> dict:
    groups: dict[str, list[float]] = {}
    for (repo, _), value in sorted(values.items()):
        groups.setdefault(repo, []).append(value)
    n = sum(map(len, groups.values()))
    estimate = _mean(list(values.values()))
    explanation = None
    if n < 2 or samples < 1:
        explanation = "Insufficient issues or bootstrap disabled; interval unavailable."
    elif len(groups) < 2:
        explanation = "One repository: between-repository uncertainty cannot be estimated."
    if explanation:
        return {"mean": estimate, "ci95": None, "issues": n, "repositories": len(groups),
                "uncertainty_note": explanation}
    rng = random.Random(seed)
    repos = sorted(groups)
    draws = []
    for _ in range(samples):
        sampled = []
        for repo in rng.choices(repos, k=len(repos)):
            items = groups[repo]
            sampled.extend(rng.choices(items, k=len(items)))
        draws.append(statistics.fmean(sampled))
    draws.sort()
    note = ("Fewer than six repository clusters: interval is exploratory and does not "
            "support broad repository-population claims." if len(groups) < 6 else
            "Only six or a small number of repository clusters; interpret generalization cautiously.")
    return {"mean": estimate, "ci95": [_percentile(draws, .025), _percentile(draws, .975)],
            "issues": n, "repositories": len(groups), "uncertainty_note": note}


def _derived_seed(seed: int, *parts: str) -> int:
    digest = hashlib.sha256((str(seed) + "|" + "|".join(parts)).encode()).hexdigest()
    return int(digest[:16], 16)


def _condition_summary(rows: list[dict], samples: int, seed: int, label: str) -> dict:
    return {
        "runs": len(rows),
        "issues": len({(row["repo"], row["case_id"]) for row in rows}),
        "missing_gold_runs": sum(not row["gold_present"] for row in rows),
        "localization_runs": sum(bool(row["gold_present"]) for row in rows),
        "failed_runs": sum(row["status"] != "ok" for row in rows),
        "metrics": {metric: _interval(_issue_values(rows, metric), samples,
                                      _derived_seed(seed, label, metric)) for metric in METRICS},
    }


def summarize(scored: list[dict], bootstrap_samples: int = 2000, seed: int = 20261010) -> dict:
    """Return separated-model summaries with failures in the denominator.

    All attempts are counted. For outcome analysis the last attempt of each
    (model, issue, condition, sampling seed) is used. Paired comparisons include
    only issues with identical seed sets in both arms, including failed attempts.
    Sampling repeats are averaged within an issue before resampling repositories
    and then issues. No analysis pools model runtimes or quantizations.
    """
    if bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be nonnegative")
    latest: dict[tuple, dict] = {}
    configurations: dict[str, set[str]] = {}
    for row in scored:
        configurations.setdefault(row["model_name"], set()).add(row.get("model_configuration_sha256", "unspecified"))
    def model_key(row):
        name = row["model_name"]
        return name if len(configurations[name]) == 1 else name + " [configuration " + row.get("model_configuration_sha256", "unspecified")[:12] + "]"
    for row in scored:
        latest[(model_key(row), row["repo"], row["case_id"], row["condition"], row["seed"])] = row
    result = {
        "schema_version": 1,
        "attempts": len(scored),
        "outcome_runs": len(latest),
        "superseded_attempts": len(scored) - len(latest),
        "synthetic": bool(scored) and all(row.get("synthetic", False) for row in scored),
        "synthetic_attempts": sum(bool(row.get("synthetic", False)) for row in scored),
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": seed,
        "estimand": "Mean across issues after averaging sampling seeds within each issue.",
        "interval_method": "Percentile hierarchical repository/issue bootstrap; 95% exploratory intervals.",
        "failure_policy": "Last attempt per logical run; terminal failures score zero localization. All attempts remain in CSV.",
        "models": {},
    }
    for model in sorted({model_key(row) for row in scored}):
        rows = [row for row in latest.values() if model_key(row) == model]
        conditions = sorted({row["condition"] for row in rows})
        model_result = {"attempts": sum(model_key(row) == model for row in scored),
                        "synthetic": any(row.get("synthetic", False) for row in rows),
                        "conditions": {}, "repositories": {}, "paired_comparisons": []}
        for condition in conditions:
            arm = [row for row in rows if row["condition"] == condition]
            model_result["conditions"][condition] = _condition_summary(arm, bootstrap_samples, seed, model + condition)
        for repo in sorted({row["repo"] for row in rows}):
            model_result["repositories"][repo] = {
                condition: _condition_summary(
                    [row for row in rows if row["repo"] == repo and row["condition"] == condition],
                    0, seed, model + repo + condition)
                for condition in conditions
            }
        for left, right in itertools.combinations(conditions, 2):
            left_rows, right_rows = {}, {}
            for row in rows:
                target = left_rows if row["condition"] == left else right_rows if row["condition"] == right else None
                if target is not None:
                    target.setdefault((row["repo"], row["case_id"]), {})[row["seed"]] = row
            overlapping = set(left_rows) & set(right_rows)
            paired = {key for key in overlapping if set(left_rows[key]) == set(right_rows[key])}
            comparison = {"left": left, "right": right, "direction": "right minus left",
                          "paired_issues": len(paired), "unmatched_seed_issues": len(overlapping - paired),
                          "unpaired_issues": len(set(left_rows) | set(right_rows)) - len(paired), "metrics": {}}
            for metric in METRICS:
                differences = {}
                for key in sorted(paired):
                    seeds = sorted(left_rows[key], key=str)
                    a = [left_rows[key][s][metric] for s in seeds]
                    b = [right_rows[key][s][metric] for s in seeds]
                    if all(value is not None for value in a + b):
                        differences[key] = statistics.fmean(b) - statistics.fmean(a)
                comparison["metrics"][metric] = _interval(
                    differences, bootstrap_samples, _derived_seed(seed, model, left, right, metric))
            model_result["paired_comparisons"].append(comparison)
        result["models"][model] = model_result
    return result


def _format(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.4f}"


def _figures(summary: dict, outdir: Path) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    paths = []
    # Every plot uses measured rows. A synthetic run is visibly watermarked.
    for model, data in summary["models"].items():
        stamp = "SYNTHETIC DEMO — NOT RESEARCH EVIDENCE" if data["synthetic"] else "Recorded evaluation runs"
        slug = hashlib.sha256(model.encode()).hexdigest()[:10]
        arms = data["conditions"]
        for number, names, title in (
            (1, ["clean", "deleted", "rewired"], "Missing and false relationship effects"),
            (2, ["clean", "clean_checked", "rewired", "rewired_checked"], "Source checking benefits and costs"),
        ):
            names = [name for name in names if name in arms]
            if not names:
                continue
            fig, axes = plt.subplots(1, 2 if number == 2 else 1, figsize=(11 if number == 2 else 7, 4), squeeze=False)
            metrics = ["file_recall_at5", "latency_seconds"] if number == 2 else ["file_recall_at5"]
            for ax, metric in zip(axes[0], metrics):
                valid = [name for name in names if arms[name]["metrics"][metric]["mean"] is not None]
                means = [arms[name]["metrics"][metric]["mean"] for name in valid]
                ax.bar(range(len(valid)), means)
                ax.set_xticks(range(len(valid)), valid, rotation=25, ha="right")
                ax.set_ylabel("File recall@5" if metric == "file_recall_at5" else "Seconds per attempt")
                for i, name in enumerate(valid):
                    ci = arms[name]["metrics"][metric]["ci95"]
                    if ci is not None:
                        ax.plot([i, i], ci, color="black", linewidth=1.4)
                if metric == "file_recall_at5":
                    ax.set_ylim(0, 1)
            fig.suptitle(f"{title}\n{model} | {stamp}", fontsize=10)
            fig.tight_layout()
            name = f"figure_{number}_{slug}.png"
            fig.savefig(outdir / name, dpi=160)
            plt.close(fig)
            paths.append(name)
        repos = data["repositories"]
        if repos:
            fig, ax = plt.subplots(figsize=(9, 4))
            names = [name for name in CONDITIONS if name in arms]
            width = .8 / max(len(names), 1)
            for index, name in enumerate(names):
                points = [(i, values[name]["metrics"]["file_recall_at5"]["mean"])
                          for i, values in enumerate(repos.values())
                          if values.get(name, {}).get("metrics", {}).get("file_recall_at5", {}).get("mean") is not None]
                ax.bar([i - .4 + width * index for i, _ in points], [value for _, value in points], width, label=name)
            ax.set_xticks(range(len(repos)), list(repos), rotation=20, ha="right")
            ax.set_ylim(0, 1)
            ax.set_ylabel("File recall@5")
            ax.legend(fontsize=7)
            ax.set_title(f"Results across repositories\n{model} | {stamp}", fontsize=10)
            fig.tight_layout()
            name = f"figure_3_{slug}.png"
            fig.savefig(outdir / name, dpi=160)
            plt.close(fig)
            paths.append(name)
    return paths


def write_report(scored: list[dict], outdir: str | Path) -> dict:
    """Write auditable scored rows, statistics, Markdown, and optional figures."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    summary = summarize(scored)
    fields = sorted({field for row in scored for field in row})
    with (outdir / "results.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or ["case_id"])
        writer.writeheader()
        for row in scored:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})
    summary["figures"] = _figures(summary, outdir)
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# GraphTrust-SWE evaluation report", "",
             "**SYNTHETIC DEMO — NOT RESEARCH EVIDENCE.**" if summary["synthetic"] else "Results describe the supplied evaluation records only.", "",
             f"Attempts: {summary['attempts']}; outcome runs: {summary['outcome_runs']}; superseded attempts: {summary['superseded_attempts']}.", "",
             summary["estimand"], summary["interval_method"], summary["failure_policy"], "",
             "Reference edits are localization proxies, not definitive root-cause labels. Missing gold is excluded from localization denominators and disclosed below.", ""]
    if summary["synthetic_attempts"] and not summary["synthetic"]:
        lines += [f"**Mixed evidence: {summary['synthetic_attempts']} attempts are synthetic. Synthetic model strata must never appear as empirical paper findings.**", ""]
    if not scored:
        lines += ["No evaluation records: there are no empirical results.", ""]
    for model, data in summary["models"].items():
        lines += [f"## Model: {model}", "", "| Condition | Runs | Issues | Missing gold runs | Failed runs | File recall@5 | Hit@5 | False citations/issue | Coverage ceiling |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        if data["synthetic"]:
            lines.insert(len(lines) - 2, "**This model stratum contains synthetic demonstrations; it is not research evidence.**\n")
        for condition, arm in data["conditions"].items():
            metrics = arm["metrics"]
            lines.append(f"| {condition} | {arm['runs']} | {arm['issues']} | {arm['missing_gold_runs']} | {arm['failed_runs']} | "
                         + " | ".join(_format(metrics[name]["mean"]) for name in ("file_recall_at5", "hit_at5", "cited_false_edges", "coverage_ceiling")) + " |")
        lines += ["", "Paired differences are right minus left; seed sets must match within each issue. Full intervals, denominators, repository strata, and timing/token metrics are in summary.json.", "",
                  "| Left | Right | Matched issues | Scored recall issues | Unpaired issues | Recall difference | 95% interval |", "|---|---|---:|---:|---:|---:|---|"]
        for comparison in data["paired_comparisons"]:
            metric = comparison["metrics"]["file_recall_at5"]
            lines.append(f"| {comparison['left']} | {comparison['right']} | {comparison['paired_issues']} | {metric['issues']} | {comparison['unpaired_issues']} | {_format(metric['mean'])} | {metric['ci95'] or 'unavailable'} |")
        lines += ["", "Intervals from few repository clusters are exploratory; a single-repository interval is not estimated. No cross-model pooling or model-size causal claim is supported.", ""]
    for name in summary["figures"]:
        lines += [f"![Recorded results]({name})", ""]
    if not summary["figures"]:
        lines += ["Figures omitted: matplotlib is unavailable or no measured conditions are present.", ""]
    (outdir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
