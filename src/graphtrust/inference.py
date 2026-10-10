"""Resumable, failure-preserving local inference. No hosted API is used.

The in-process deadline is measured after a backend returns. It is deliberately
not advertised as a hard interruption of GPU generation.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import time
from typing import Protocol


class Backend(Protocol):
    identity: dict
    synthetic: bool

    def generate(self, prompt: str, seed: int, max_output_tokens: int, temperature: float) -> dict: ...


class PredictionError(ValueError):
    """Output failed the preregistered JSON schema."""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checkpoint_manifest(model_path: str | Path, *, require_weights: bool = True) -> dict | None:
    """Fingerprint local checkpoint bytes, independent of mutable path names.

    Hash weights and every JSON/tokenizer/template artifact used by standard
    Transformers loading. Training logs, documentation, and cache locks are not
    runtime inputs. A model directory without weight files is rejected. Set
    require_weights=False to fingerprint a tokenizer-only preflight directory.
    """
    root = Path(model_path)
    if not root.is_dir():
        return None
    suffixes = {".safetensors", ".bin", ".pt", ".pth", ".json", ".model", ".tiktoken", ".jinja", ".txt", ".vocab", ".merges"}
    files = sorted((p for p in root.rglob("*") if p.is_file() and p.suffix in suffixes), key=lambda p: p.relative_to(root).as_posix())
    if require_weights and not any(p.suffix in {".safetensors", ".bin", ".pt", ".pth"} for p in files):
        raise ValueError("local model checkpoint has no recognized weight files")
    entries = [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": _file_hash(p)} for p in files]
    return {"files": entries, "sha256": _hash(entries)}


def tokenizer_fingerprint(tokenizer) -> str:
    """Match tokenizer-only CLI preflights to the loaded model tokenizer.

    Uses actual tokenizer vocabulary/normalization, its chat template, special
    tokens, and implementation class; unrelated model weights/configs cannot
    change this identity. Fast tokenizers expose the required serialized state.
    """
    native = getattr(tokenizer, "backend_tokenizer", None)
    if native is None or not callable(getattr(native, "to_str", None)):
        raise ValueError("a fast tokenizer with backend_tokenizer.to_str is required for reproducible identity")
    def strings(value):
        if isinstance(value, dict):
            return {key: strings(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [strings(item) for item in value]
        return str(value)
    return _hash({
        "backend_tokenizer": native.to_str(),
        "chat_template": getattr(tokenizer, "chat_template", None),
        "special_tokens_map": strings(getattr(tokenizer, "special_tokens_map", {})),
        "class": f"{type(tokenizer).__module__}.{type(tokenizer).__qualname__}",
    })


def _unique_list(value, name: str, limit: int | None = None) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise PredictionError(f"{name} must be a list of nonempty strings")
    if len(value) != len(set(value)):
        raise PredictionError(f"{name} contains duplicate entries")
    if limit is not None and len(value) > limit:
        raise PredictionError(f"{name} contains more than {limit} entries")
    return value


def parse_prediction(text: str) -> dict:
    """Strict JSON only: no fenced blocks, salvaged fragments, or coercions."""
    if not isinstance(text, str):
        raise PredictionError("output must be text")
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PredictionError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        data = json.loads(text, object_pairs_hook=unique_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError) as exc:
        raise PredictionError("output is not a JSON object") from exc
    keys = {"files", "source_ids", "edge_ids", "abstain"}
    if not isinstance(data, dict) or set(data) != keys:
        raise PredictionError("output must contain exactly files, source_ids, edge_ids, abstain")
    _unique_list(data["files"], "files", 5)
    _unique_list(data["source_ids"], "source_ids")
    _unique_list(data["edge_ids"], "edge_ids")
    if type(data["abstain"]) is not bool:
        raise PredictionError("abstain must be a JSON boolean")
    for path in data["files"]:
        posix = PurePosixPath(path)
        if path != str(posix) or "\\" in path or posix.is_absolute() or ".." in posix.parts or re.match(r"^[A-Za-z]:", path):
            raise PredictionError("files must be normalized relative POSIX paths")
    if data["abstain"] and data["files"]:
        raise PredictionError("abstention cannot include predicted files")
    if not data["abstain"] and not data["files"]:
        raise PredictionError("empty file predictions require abstain=true")
    return data


def _backend_identity(backend) -> dict:
    identity = getattr(backend, "identity", None)
    if callable(identity):
        identity = identity()
    if identity is None:
        identity = {"class": f"{type(backend).__module__}.{type(backend).__qualname__}"}
    if not isinstance(identity, dict):
        raise ValueError("backend.identity must be a JSON-serializable dict")
    _json(identity)
    return identity


def run_contexts(
    contexts: list[dict],
    output: Path,
    backend: Backend,
    seeds: list[int],
    model_name: str,
    max_output_tokens: int = 256,
    timeout_seconds: float = 90,
    temperature: float = 0.2,
    max_calls: int | None = None,
) -> dict:
    """Append one durable record per attempted arm/seed, then resume exactly.

    Recorded failures are terminal for that run key. Changing configuration is a
    new experiment; there is no selective retry of failed or invalid outputs.
    A truncated existing log is rejected for explicit recovery, never ignored.
    """
    if max_output_tokens <= 0 or timeout_seconds <= 0 or not math.isfinite(timeout_seconds) or temperature < 0 or not math.isfinite(temperature):
        raise ValueError("invalid generation configuration")
    if not seeds or any(type(seed) is not int for seed in seeds) or len(seeds) != len(set(seeds)):
        raise ValueError("seeds must be a nonempty list of unique integers")
    if max_calls is not None and (type(max_calls) is not int or max_calls < 0):
        raise ValueError("max_calls must be a nonnegative integer or None")
    identity = _backend_identity(backend)
    synthetic = bool(getattr(backend, "synthetic", False))
    config = {"max_output_tokens": max_output_tokens, "timeout_seconds": timeout_seconds, "temperature": temperature, "thinking": False}
    seen = {}
    output = Path(output)
    if output.exists():
        with output.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                    run_id = record["run_id"]
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"invalid existing JSONL record at line {number}; preserve and repair the log explicitly") from exc
                if run_id in seen:
                    raise ValueError(f"duplicate run ID in existing log at line {number}")
                seen[run_id] = record
    scheduled = []
    scheduled_ids = set()
    for context in contexts:
        if _text_hash(context["prompt"]) != context["context_sha256"]:
            raise ValueError("context hash does not match prompt")
        validate_context = getattr(backend, "validate_context", None)
        if validate_context is not None:
            validate_context(context["prompt"], max_output_tokens)
        for seed in seeds:
            key = {"context_sha256": context["context_sha256"], "case_id": context["case_id"], "condition": context["condition"], "model_name": model_name, "backend": identity, "seed": seed, "generation": config}
            run_id = _hash(key)
            if run_id in scheduled_ids:
                raise ValueError("duplicate arm/seed in requested run")
            scheduled_ids.add(run_id)
            scheduled.append((context, seed, run_id))
    output.parent.mkdir(parents=True, exist_ok=True)
    journal = Path(str(output) + ".attempts.jsonl")
    starts = {}
    if journal.exists():
        with journal.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                    run_id = record["run_id"]
                    if record["status"] != "started" or run_id in starts:
                        raise ValueError("invalid or duplicate start")
                    starts[run_id] = record
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"invalid attempt journal at line {number}; preserve and repair explicitly") from exc
    attempted = resumed = 0
    statuses = Counter()
    # Single-writer append. The CLI must not share one log between processes.
    with output.open("a", encoding="utf-8", newline="\n") as handle, journal.open("a", encoding="utf-8", newline="\n") as journal_handle:
        for run_id, start_record in starts.items():
            if run_id not in seen:
                interrupted = dict(start_record, status="interrupted", error="Process ended before a terminal record; automatic retry is disabled", error_kind="process_interruption", latency_seconds=None)
                handle.write(_json(interrupted) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                seen[run_id] = interrupted
        for context, seed, run_id in scheduled:
            if run_id in seen:
                resumed += 1
                statuses[seen[run_id]["status"]] += 1
                continue
            if max_calls is not None and attempted >= max_calls:
                continue
            record = {
                "schema_version": "1.0", "run_id": run_id,
                "case_id": context["case_id"], "repo": context.get("repo", ""), "condition": context["condition"],
                "model_name": model_name, "backend": identity, "seed": seed, "generation": config,
                "source_sha256": context["source_sha256"], "context_sha256": context["context_sha256"],
                "visible_files": context.get("visible_files", []), "visible_source_ids": context.get("visible_source_ids", []), "visible_edge_ids": context.get("visible_edge_ids", []),
                "started_at": datetime.now(timezone.utc).isoformat(), "synthetic": synthetic,
                "status": "error", "raw_output": None, "response": None, "prediction": None,
                "input_tokens": context.get("input_tokens"), "input_token_method": context.get("token_method", "unknown"),
                "output_tokens": None, "timeout_enforcement": "elapsed_after_return",
            }
            journal_handle.write(_json(dict(record, status="started")) + "\n")
            journal_handle.flush()
            os.fsync(journal_handle.fileno())
            started = time.monotonic()
            fatal = None
            try:
                result = backend.generate(context["prompt"], seed=seed, max_output_tokens=max_output_tokens, temperature=temperature)
                if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                    raise TypeError("backend.generate must return a dict with text")
                record["raw_output"] = result["text"]
                for field in ("input_tokens", "output_tokens"):
                    value = result.get(field)
                    if value is not None:
                        if type(value) is not int or value < 0:
                            raise TypeError(f"backend {field} must be a nonnegative integer")
                        record[field] = value
                if "input_tokens" in result:
                    record["input_token_method"] = result.get("token_method", "backend_tokenizer")
                record["rendered_prompt_sha256"] = result.get("rendered_prompt_sha256")
                try:
                    prediction = parse_prediction(result["text"])
                    record["prediction"] = prediction
                    record["response"] = prediction
                    invalid_files = sorted(set(prediction["files"]) - set(context.get("visible_files", [])))
                    invalid_sources = sorted(set(prediction["source_ids"]) - set(context.get("visible_source_ids", [])))
                    invalid_edges = sorted(set(prediction["edge_ids"]) - set(context.get("visible_edge_ids", [])))
                    record.update(invalid_files=invalid_files, invalid_source_ids=invalid_sources, invalid_edge_ids=invalid_edges)
                    record["status"] = "parse_error" if invalid_files or invalid_sources or invalid_edges else "ok"
                except PredictionError as exc:
                    record["status"] = "parse_error"
                    record["error"] = str(exc)
            except Exception as exc:
                record["status"] = "timeout" if isinstance(exc, TimeoutError) else "error"
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["error_kind"] = "out_of_memory" if "outofmemory" in type(exc).__name__.lower() or "out of memory" in str(exc).lower() else type(exc).__name__
            except BaseException as exc:
                record["status"] = "interrupted"
                record["error"] = f"{type(exc).__name__}: interrupted before generation returned"
                record["error_kind"] = type(exc).__name__
                fatal = exc
            record["latency_seconds"] = time.monotonic() - started
            if record["latency_seconds"] > timeout_seconds:
                record["completed_status"] = record["status"]
                record["status"] = "timeout"
            handle.write(_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            seen[run_id] = record
            attempted += 1
            statuses[record["status"]] += 1
            if fatal is not None:
                raise fatal
    return {"attempted": attempted, "resumed": resumed, "scheduled": len(scheduled), "remaining": sum(run_id not in seen for _, _, run_id in scheduled), "statuses": dict(statuses), "synthetic": synthetic, "output": str(output)}


class MockBackend:
    """Synthetic wiring fixture, deliberately not a localization model."""
    synthetic = True

    def __init__(self, response: dict | None = None):
        self.response = response
        self.identity = {"name": "synthetic_mock_v1", "response": response}

    def generate(self, prompt: str, seed: int, max_output_tokens: int, temperature: float) -> dict:
        if self.response is not None:
            result = self.response
        else:
            matches = re.findall(r"^SOURCE (\S+) FILE (\S+) LINES", prompt, re.MULTILINE)
            result = {"files": [matches[0][1]] if matches else [], "source_ids": [matches[0][0]] if matches else [], "edge_ids": [], "abstain": not bool(matches)}
        text = _json(result)
        return {"text": text, "input_tokens": len(prompt.encode("utf-8")), "output_tokens": len(text.encode("utf-8")), "token_method": "byte_upper_bound"}


class TransformersBackend:
    """Gemma 4's supported AutoProcessor path; dependencies load on demand.

    Pin revision to the checkpoint commit in production. Set device_map="auto"
    for a Kaggle GPU; the actual device map is included in the run fingerprint.
    """
    synthetic = False

    def __init__(self, model_path: str, revision: str | None = None, device_map: str = "auto", dtype: str = "auto", local_files_only: bool = False):
        try:
            import torch
            import transformers
            from transformers import AutoProcessor, AutoModelForMultimodalLM
        except ImportError as exc:
            raise ImportError("Install the inference extra (transformers>=5.10.1, torch, accelerate) for real model runs") from exc
        self.torch = torch
        local_manifest = checkpoint_manifest(model_path)
        self.processor = AutoProcessor.from_pretrained(model_path, revision=revision, local_files_only=local_files_only)
        self.model = AutoModelForMultimodalLM.from_pretrained(model_path, revision=revision, device_map=device_map, dtype=dtype, local_files_only=local_files_only)
        self.model.eval()
        # ProcessorMixin may own the template separately from its tokenizer.
        # Fingerprint the active template actually used by _render.
        self.processor.tokenizer.chat_template = self.processor.chat_template
        resolved_revision = getattr(self.model.config, "_commit_hash", None)
        if local_manifest is None and not resolved_revision:
            raise ValueError("remote checkpoint did not expose a resolved commit hash; use a pinned local checkpoint")
        self.identity = {
            "name": "transformers", "model_path": model_path, "requested_revision": revision,
            "resolved_revision": resolved_revision, "local_checkpoint": local_manifest,
            "checkpoint_sha256": local_manifest["sha256"] if local_manifest else None,
            "tokenizer_sha256": tokenizer_fingerprint(self.processor.tokenizer),
            "torch": torch.__version__, "transformers": transformers.__version__, "dtype": str(self.model.dtype),
            "device_map": {str(k): str(v) for k, v in getattr(self.model, "hf_device_map", {"": str(self.model.device)}).items()},
            "chat_template_sha256": _text_hash(str(self.processor.chat_template)), "enable_thinking": False,
            "generation_defaults_sha256": _hash(self.model.generation_config.to_dict()),
            "gpu_names": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())] if torch.cuda.is_available() else [],
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        }

    def _render(self, prompt: str) -> str:
        return self.processor.apply_chat_template(
            [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )

    def count_tokens(self, prompt: str) -> int:
        inputs = self.processor(text=self._render(prompt), return_tensors="pt", add_special_tokens=False)
        return int(inputs["input_ids"].shape[-1])

    def generate(self, prompt: str, seed: int, max_output_tokens: int, temperature: float) -> dict:
        from transformers import set_seed
        set_seed(seed)
        if self.torch.cuda.is_available():
            self.torch.cuda.manual_seed_all(seed)
        rendered = self._render(prompt)
        inputs = self.processor(text=rendered, return_tensors="pt", add_special_tokens=False).to(self.model.device)
        length = int(inputs["input_ids"].shape[-1])
        kwargs = {"max_new_tokens": max_output_tokens, "do_sample": temperature > 0, "return_dict_in_generate": False}
        if temperature > 0:
            kwargs["temperature"] = temperature
        with self.torch.inference_mode():
            outputs = self.model.generate(**inputs, **kwargs)
        generated = outputs[0][length:]
        text = self.processor.decode(generated, skip_special_tokens=True)
        return {"text": text, "input_tokens": length, "output_tokens": int(generated.shape[-1]), "token_method": "backend_tokenizer", "rendered_prompt_sha256": _text_hash(rendered)}


class LlamaCppBackend:
    """GGUF inference with its embedded Jinja template and thinking disabled.

    The GGUF file is hashed into the resume identity. Unsupported templates fail
    explicitly rather than silently falling back to a different chat format.
    """
    synthetic = False

    def __init__(self, model_path: str, n_ctx: int = 4608, n_gpu_layers: int = -1, n_threads: int | None = None):
        if type(n_ctx) is not int or n_ctx <= 0:
            raise ValueError("n_ctx must be a positive integer")
        try:
            import llama_cpp
            from llama_cpp.llama_chat_format import Jinja2ChatFormatter
        except ImportError as exc:
            raise ImportError("Install llama-cpp-python with a supported Gemma 4 build for GGUF runs") from exc
        kwargs = {"model_path": model_path, "n_ctx": n_ctx, "n_gpu_layers": n_gpu_layers, "verbose": False}
        if n_threads is not None:
            kwargs["n_threads"] = n_threads
        self.llm = llama_cpp.Llama(**kwargs)
        self.n_ctx = n_ctx
        template = self.llm.metadata.get("tokenizer.chat_template")
        if not isinstance(template, str) or not template:
            raise ValueError("GGUF must provide tokenizer.chat_template; a guessed format is not allowed")
        self.formatter = Jinja2ChatFormatter(
            template=template,
            eos_token=self.llm.detokenize([self.llm.token_eos()], special=True).decode("utf-8"),
            bos_token=self.llm.detokenize([self.llm.token_bos()], special=True).decode("utf-8"),
        )
        self.identity = {"name": "llama_cpp", "model_path": str(Path(model_path).resolve()), "model_sha256": _file_hash(Path(model_path)), "llama_cpp_python": llama_cpp.__version__, "n_ctx": n_ctx, "n_gpu_layers": n_gpu_layers, "n_threads": n_threads, "chat_template_sha256": _text_hash(template), "enable_thinking": False}
        # Conservative GGUF tokenizer identity binds the actual file containing
        # its vocabulary, embedded template, and runtime tokenization version.
        # It intentionally differs from a Transformers tokenizer fingerprint;
        # a GGUF arm must regenerate contexts using this backend's counter.
        self.identity["tokenizer_sha256"] = _hash({"format": "gguf", "model_sha256": self.identity["model_sha256"], "chat_template_sha256": self.identity["chat_template_sha256"], "llama_cpp_python": llama_cpp.__version__})

    def _format(self, prompt: str):
        return self.formatter(messages=[{"role": "user", "content": prompt}], enable_thinking=False)

    def count_tokens(self, prompt: str) -> int:
        formatted = self._format(prompt)
        return len(self.llm.tokenize(formatted.prompt.encode("utf-8"), add_bos=False, special=True))

    def validate_context(self, prompt: str, max_output_tokens: int) -> None:
        input_tokens = self.count_tokens(prompt)
        if input_tokens + max_output_tokens > self.n_ctx:
            raise ValueError(f"GGUF input ({input_tokens}) plus output allowance ({max_output_tokens}) exceeds n_ctx={self.n_ctx}")

    def generate(self, prompt: str, seed: int, max_output_tokens: int, temperature: float) -> dict:
        formatted = self._format(prompt)
        token_ids = self.llm.tokenize(formatted.prompt.encode("utf-8"), add_bos=False, special=True)
        if len(token_ids) + max_output_tokens > self.n_ctx:
            raise ValueError(f"GGUF input ({len(token_ids)}) plus output allowance ({max_output_tokens}) exceeds n_ctx={self.n_ctx}")
        result = self.llm.create_completion(prompt=token_ids, seed=seed, max_tokens=max_output_tokens, temperature=temperature, stop=formatted.stop, stopping_criteria=formatted.stopping_criteria)
        return {"text": result["choices"][0]["text"], "input_tokens": result["usage"]["prompt_tokens"], "output_tokens": result["usage"]["completion_tokens"], "token_method": "backend_tokenizer", "rendered_prompt_sha256": _text_hash(formatted.prompt)}
