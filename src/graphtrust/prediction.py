"""Versioned whole-response decoding and gold-independent prediction checks."""
from __future__ import annotations

import json
import math
import hashlib
from pathlib import PurePosixPath
import re

RESPONSE_CONTRACT_VERSION = "files_citations_v2"
RECORD_SCHEMA_VERSION = "2.0"
MAX_FILES = 5
MAX_CITATIONS = 2
RECORD_DIGEST_RULE = "sorted_compact_ascii_json_v2"


def canonical_record(value) -> str:
    """Durable v2 JSON encoding; preserves arbitrary raw backend text safely."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def record_digest(value) -> str:
    return hashlib.sha256(canonical_record(value).encode("utf-8")).hexdigest()


class PredictionError(ValueError):
    """The entire response does not satisfy the versioned JSON/type contract."""


def parse_prediction(text: str) -> dict:
    """Decode one complete object, bare or in one whole JSON-tagged fence.

    Defaults for omitted citations/abstain are explicit. Literal strings, ranked
    order and extra fields are retained; semantic violations are checked later.
    Fragments, prose, missing files, duplicate object keys and bad types fail.
    """
    if not isinstance(text, str):
        raise PredictionError("output must be text")
    payload = text.strip(" \t\r\n")
    if payload.startswith("```"):
        fence = re.fullmatch(r"```json[ \t]*\r?\n(.*?)\r?\n```", payload, re.DOTALL | re.IGNORECASE)
        if fence is None:
            raise PredictionError("output must be one whole JSON-tagged fenced object")
        payload = fence.group(1)

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PredictionError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise PredictionError("nonfinite JSON number")
        return number

    try:
        data = json.loads(payload, object_pairs_hook=unique_object,
                          parse_float=finite_float,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        # Validate all decoded strings/keys, including unknown fields. Escaped
        # paired surrogates decode to one scalar; lone surrogates are not text.
        json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise PredictionError("output must be one complete unambiguous JSON object") from exc
    if not isinstance(data, dict) or "files" not in data:
        raise PredictionError("files is required in the JSON object")
    for name in ("files", "citations"):
        values = data.get(name, [])
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise PredictionError(f"{name} must be a JSON array of strings")
    if type(data.get("abstain", False)) is not bool:
        raise PredictionError("abstain must be a JSON boolean when supplied")
    return {**data, "citations": data.get("citations", []), "abstain": data.get("abstain", False)}


def exact_file_path(value: str) -> bool:
    """No normalization or guessed path repair is permitted for ranked slots."""
    path = PurePosixPath(value)
    return bool(value and value != "." and value == str(path) and value.strip() == value
                and "\\" not in value and ":" not in value and not path.is_absolute()
                and ".." not in path.parts)


def validate_prediction(prediction: dict, context: dict) -> dict:
    """Flag parsed semantic violations without erasing valid localization slots.

    Only visible metadata determines citation validity. A supplied false edge is
    a valid identifier; source truth and gold labels never enter this function.
    """
    files, citations = prediction["files"], prediction.get("citations", [])
    visible_files = set(context.get("visible_files", []))
    visible_sources = set(context.get("visible_source_ids", []))
    visible_edges = set(context.get("visible_edge_ids", []))
    invalid_files = [item for item in files if not exact_file_path(item) or item not in visible_files]
    kinds = {}
    invalid_citations = []
    for item in citations:
        matches = (["edge"] if item in visible_edges else []) + (["source_id"] if item in visible_sources else []) + (["source_file"] if item in visible_files else [])
        if len(matches) != 1:
            invalid_citations.append(item)
        else:
            kinds[item] = matches[0]
    flags = {
        "extra_fields": sorted(set(prediction) - {"files", "citations", "abstain"}),
        "invalid_files": invalid_files,
        "invalid_citations": invalid_citations,
        "duplicate_files": len(files) != len(set(files)),
        "duplicate_citations": len(citations) != len(set(citations)),
        "too_many_files": len(files) > MAX_FILES,
        "too_many_citations": len(citations) > MAX_CITATIONS,
        "abstain_with_files": prediction.get("abstain", False) and bool(files),
        "empty_without_abstain": not prediction.get("abstain", False) and not files,
    }
    return {
        "invalid_prediction": any(bool(value) for value in flags.values()),
        "prediction_flags": flags,
        "invalid_files": invalid_files,
        "invalid_citations": invalid_citations,
        "valid_graph_citations": sorted(item for item, kind in kinds.items() if kind == "edge"),
        "valid_source_id_citations": sorted(item for item, kind in kinds.items() if kind == "source_id"),
        "valid_file_citations": sorted(item for item, kind in kinds.items() if kind == "source_file"),
    }


def validate_record_prediction(record: dict, context: dict) -> tuple[dict | None, dict]:
    """Verify retained v2 output/classification without accepting a late run."""
    if (record.get("schema_version") != RECORD_SCHEMA_VERSION
            or record.get("response_contract_version") != RESPONSE_CONTRACT_VERSION
            or context.get("response_contract_version") != RESPONSE_CONTRACT_VERSION):
        raise ValueError("Unknown or mismatched response-contract version")
    if "raw_output" not in record or type(record.get("contract_parseable")) is not bool or type(record.get("invalid_prediction")) is not bool:
        raise ValueError("V2 record requires raw output and explicit contract/semantic flags")
    if record["raw_output"] is not None and not isinstance(record["raw_output"], str):
        raise ValueError("Raw output must be text or explicit null")
    status = record.get("status")
    statuses = {"ok", "invalid_prediction", "parse_error", "error", "timeout", "interrupted"}
    completed = record.get("completed_status", status)
    if status not in statuses or completed not in statuses:
        raise ValueError("Unknown v2 terminal/completed status")
    if "completed_status" in record and status != "timeout":
        raise ValueError("Completed status is only valid for elapsed timeouts")
    latency = record.get("latency_seconds")
    limit = record.get("generation", {}).get("timeout_seconds", 90)
    if (type(limit) not in {int, float} or not math.isfinite(limit) or limit <= 0
            or (latency is None and status != "interrupted")
            or (latency is not None and (type(latency) not in {int, float} or not math.isfinite(latency) or latency < 0))):
        raise ValueError("Terminal latency/budget must be finite and nonnegative")
    if latency is not None and latency > limit and status != "timeout":
        raise ValueError("Over-budget return must retain timeout status")
    if "completed_status" in record and (latency is None or latency <= limit):
        raise ValueError("Elapsed timeout must exceed its recorded budget")
    if record["contract_parseable"]:
        try:
            decoded = parse_prediction(record["raw_output"])
        except PredictionError as exc:
            raise ValueError("Stored contract_parseable flag contradicts raw output") from exc
        checked = validate_prediction(decoded, context)
        expected = "invalid_prediction" if checked["invalid_prediction"] else "ok"
        if (completed != expected or record.get("response") != decoded or record.get("prediction") != decoded
                or any(record.get(key) != value for key, value in checked.items())):
            raise ValueError("Stored prediction or classification differs from raw output")
        return decoded, checked
    if (completed in {"ok", "invalid_prediction"} or record["invalid_prediction"]
            or record.get("response") is not None or record.get("prediction") is not None):
        raise ValueError("Unparsed record contains a parsed prediction/classification")
    if completed == "parse_error":
        if not isinstance(record["raw_output"], str):
            raise ValueError("Parse-error output must retain the raw text")
        try:
            parse_prediction(record["raw_output"])
        except PredictionError:
            pass
        else:
            raise ValueError("Parse-error classification contradicts raw output")
    return None, {}
