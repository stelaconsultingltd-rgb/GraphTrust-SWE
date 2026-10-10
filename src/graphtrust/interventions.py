"""Seeded relationship interventions and a source-consistency baseline.

The reference for checking is re-extracted source, never reference repair
patches. A contradiction is a mismatch with a statically resolved call site;
unknown bindings are not promoted to runtime truth.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import random
from typing import Any

from .graph import edge_identifier


def _digest(value: dict[str, Any]) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def _relation(edge: dict[str, Any]) -> tuple[str, str, str]:
    return edge["source"], edge["target"], edge["type"]


def perturb_graph(graph: dict[str, Any], kind: str, severity: float,
                  seed: int, *, source_graph: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Delete edges or swap compatible targets; preserve all source evidence.

    Rewiring changes pairs of relationships. The achieved count can fall below
    the requested count for odd counts or constrained graphs; this shortfall is
    reported, never disguised by inserting arbitrary replacement relationships.
    Candidate searches are bounded to keep repository-scale intervention runs
    practical. When ``graph`` is a packed or pruned view, ``source_graph`` must
    supply the full source-derived graph from the identical snapshot. Generated
    relations are forbidden if supported anywhere in that full graph, including
    other call sites omitted from the supplied metadata. Without ``source_graph``
    the supplied graph itself defines the supported relationship set.
    """
    if kind not in {"delete", "rewire"}:
        raise ValueError("kind must be 'delete' or 'rewire'")
    if not isinstance(severity, (int, float)) or not math.isfinite(severity) or not 0 <= severity <= 1:
        raise ValueError("severity must be a finite number between zero and one")
    if not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if source_graph is not None:
        snapshot = graph.get("snapshot")
        if not isinstance(snapshot, dict) or not snapshot.get("source_sha256") or snapshot != source_graph.get("snapshot"):
            raise ValueError("source_graph must describe the same source snapshot as graph")
    result = deepcopy(graph)
    edges = sorted(result["edges"], key=lambda item: item["id"])
    count = len(edges)
    requested_count = int(math.floor(count * severity + 0.5))
    rng = random.Random(seed)
    changed: list[dict[str, Any]] = []
    deleted: list[str] = []
    false: list[str] = []
    rejected: dict[str, int] = {}
    if kind == "delete":
        selected = set(rng.sample(range(count), requested_count))
        deleted = sorted(edges[index]["id"] for index in selected)
        result["edges"] = [edge for index, edge in enumerate(edges) if index not in selected]
    else:
        nodes = {node["id"]: node for node in graph["nodes"]}
        original_relations = {_relation(edge) for edge in graph["edges"]}
        if source_graph is not None:
            original_relations.update(_relation(edge) for edge in source_graph["edges"]
                                      if edge.get("resolution") == "supported")
        generated: set[tuple[str, str, str]] = set()
        groups: dict[tuple[str, str], list[int]] = {}
        for index, edge in enumerate(edges):
            target = nodes.get(edge["target"])
            if target is None or edge.get("resolution") != "supported":
                rejected["unsupported_or_missing_target"] = rejected.get("unsupported_or_missing_target", 0) + 1
                continue
            groups.setdefault((edge["type"], target["kind"]), []).append(index)
        order = list(range(count))
        rng.shuffle(order)
        for pool in groups.values():
            rng.shuffle(pool)
        used: set[int] = set()
        for first_index in order:
            if len(false) + 2 > requested_count:
                break
            if first_index in used:
                continue
            first = edges[first_index]
            target = nodes.get(first["target"])
            if target is None:
                continue
            pool = groups.get((first["type"], target["kind"]), [])
            if not pool:
                continue
            offset = rng.randrange(len(pool))
            for step in range(min(128, len(pool))):
                second_index = pool[(offset + step) % len(pool)]
                if second_index == first_index or second_index in used:
                    continue
                second = edges[second_index]
                proposed = [dict(first, target=second["target"]), dict(second, target=first["target"])]
                reason = None
                if first["target"] == second["target"]:
                    reason = "unchanged_target"
                elif any(edge["source"] == edge["target"] for edge in proposed):
                    reason = "self_loop"
                elif any(_relation(edge) in original_relations for edge in proposed):
                    reason = "originally_supported_relation"
                elif _relation(proposed[0]) == _relation(proposed[1]) or any(_relation(edge) in generated for edge in proposed):
                    reason = "duplicate_generated_relation"
                if reason:
                    rejected[reason] = rejected.get(reason, 0) + 1
                    continue
                for index, replacement in zip((first_index, second_index), proposed):
                    original = edges[index]
                    replacement["id"] = edge_identifier(replacement)
                    generated.add(_relation(replacement))
                    false.append(replacement["id"])
                    changed.append({"original_edge_id": original["id"], "replacement_edge_id": replacement["id"],
                                    "source": original["source"], "original_target": original["target"],
                                    "target": replacement["target"]})
                    edges[index] = replacement
                used.update((first_index, second_index))
                break
        result["edges"] = sorted(edges, key=lambda item: item["id"])
    achieved = len(deleted) if kind == "delete" else len(false)
    sidecar = {"schema_version": 1, "kind": kind, "seed": seed,
               "requested_severity": severity, "requested_edge_count": requested_count,
               "achieved_edge_count": achieved, "achieved_severity": achieved / count if count else 0.0,
               "deleted_edge_ids": deleted, "false_edge_ids": sorted(false),
               "changed_edge_ids": sorted(item["original_edge_id"] for item in changed),
               "changed": sorted(changed, key=lambda item: item["original_edge_id"]),
               "exclusions": {"unachieved_edge_count": requested_count - achieved,
                              "odd_pair_shortfall": requested_count % 2 if kind == "rewire" else 0,
                              "candidate_rejections": dict(sorted(rejected.items())),
                              "candidate_search_limit": 128 if kind == "rewire" else None},
               "original_graph_sha256": _digest(graph), "perturbed_graph_sha256": _digest(result)}
    return result, sidecar


def _site(edge: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(edge.get(key, "") for key in ("source", "path", "line", "expression"))


def check_edges(observed_graph: dict[str, Any], reference_graph: dict[str, Any]) -> dict[str, str]:
    """Classify metadata against source-derived evidence from the same snapshot.

    Supported means the lexical resolver corroborates the target at that call
    site. Contradicted means that resolver identifies a different target.
    Everything else is unknown, including mismatched snapshots and calls with
    unresolved dynamic bindings. The checker does not infer runtime behavior.
    """
    observed = observed_graph["edges"]
    if observed_graph.get("snapshot", {}).get("source_sha256") != reference_graph.get("snapshot", {}).get("source_sha256"):
        return {edge["id"]: "unknown" for edge in observed}
    supported: dict[tuple[Any, ...], set[tuple[str, str]]] = {}
    for edge in reference_graph["edges"]:
        if edge.get("resolution") == "supported":
            supported.setdefault(_site(edge), set()).add((edge["type"], edge["target"]))
    uncertain = {_site(item) for item in reference_graph.get("unknown", [])}
    verdicts = {}
    for edge in observed:
        site = _site(edge)
        alternatives = supported.get(site, set())
        if (edge["type"], edge["target"]) in alternatives:
            verdict = "supported"
        elif site in uncertain or not alternatives:
            verdict = "unknown"
        else:
            verdict = "contradicted"
        verdicts[edge["id"]] = verdict
    return verdicts
