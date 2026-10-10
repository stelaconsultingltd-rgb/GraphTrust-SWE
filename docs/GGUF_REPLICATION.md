# GGUF replication and fallback

**Status: checkpoint and source revisions selected; build, loading, memory use, throughput, and inference remain untested.** This document records preparation, not experimental results. No model weights were downloaded during the metadata review.

`MODEL_LOCK.json` pins the official Google Kaggle version and text-model filename. E4B replication uses **QAT Q4_0 version 2**, `gemma-4-E4B_q4_0-it.gguf` (5,154,939,136 bytes). The pre-freeze E2B fallback uses `gemma-4-E2B_q4_0-it.gguf` (3,349,514,112 bytes). Multimodal projector files are unnecessary for this text-only study. The read-only Kaggle metadata API reports file sizes without SHA-256 checksums; compute hashes from the actual attached files before inference. [Official E4B model](https://www.kaggle.com/models/google/gemma-4/Gguf/gemma-4-e4b-it-qat-q4_0-gguf/2), [official E2B model](https://www.kaggle.com/models/google/gemma-4/Gguf/gemma-4-e2b-it-qat-q4_0-gguf/2).

Google documents llama.cpp as a Gemma inference route. Our package uses its Python binding with the GGUF's embedded chat template and explicitly disables thinking; a guessed chat format is rejected. [Google integration instructions](https://ai.google.dev/gemma/docs/integrations/llamacpp).

## Build the pinned Python binding

The selected binding commit is `1652066e0af45f2313b339670ef9555e8a54e545` (source version 0.3.36), with vendored llama.cpp `0c1e57098bba43ac29e6e3b677cdceebdd22334f`. Inspection confirmed that this submodule includes the Gemma 4 architecture and that `Jinja2ChatFormatter` forwards `enable_thinking=False` to template rendering. This is source compatibility evidence; it is not a successful runtime test. [Pinned formatter](https://github.com/abetlen/llama-cpp-python/blob/1652066e0af45f2313b339670ef9555e8a54e545/llama_cpp/llama_chat_format.py), [pinned architecture](https://github.com/ggml-org/llama.cpp/blob/0c1e57098bba43ac29e6e3b677cdceebdd22334f/src/models/gemma4.cpp).

The following Linux commands prepare a CUDA build. They require Git, a C/C++ compiler and a compatible CUDA toolkit; inspect the actual Kaggle runtime before building. The binding's maintained instructions support `CMAKE_ARGS="-DGGML_CUDA=on"`. No prebuilt wheel has been selected or verified for this study. [Binding installation instructions](https://github.com/abetlen/llama-cpp-python/blob/1652066e0af45f2313b339670ef9555e8a54e545/README.md).

```bash
git clone --no-checkout https://github.com/abetlen/llama-cpp-python.git runs/runtime-source/llama-cpp-python
git -C runs/runtime-source/llama-cpp-python checkout 1652066e0af45f2313b339670ef9555e8a54e545
git -C runs/runtime-source/llama-cpp-python submodule update --init --recursive
git -C runs/runtime-source/llama-cpp-python rev-parse HEAD
git -C runs/runtime-source/llama-cpp-python/vendor/llama.cpp rev-parse HEAD
CMAKE_ARGS="-DGGML_CUDA=on" python -m pip wheel --no-deps --wheel-dir runs/runtime-wheels runs/runtime-source/llama-cpp-python
```

Verify both printed commits against the lock. Install the exact resulting wheel, record its SHA-256, compiler/CMake/CUDA versions, build log, and `pip freeze --all`, and retain the source licenses. The wheel's declared runtime dependencies must be satisfied; `--no-deps` above controls wheel building, not runtime compatibility. Jinja2 must remain at the study's pinned 3.1.6. If building fails or the checkpoint/template is unsupported, preserve the failure and amend the runtime lock before model outcomes are inspected.

For a separate standalone llama.cpp sanity check, its documented CUDA CMake build is available at pinned commit `f2918cabbffe8abf8e2a90c1c089085fa116c2cf`. A standalone CLI/server is not the package's preregistered Python runtime. [Pinned llama.cpp build instructions](https://github.com/ggml-org/llama.cpp/blob/f2918cabbffe8abf8e2a90c1c089085fa116c2cf/docs/build.md).

## Rebuild exact-tokenizer contexts

Set `GRAPHTRUST_GGUF_MODEL` to the actual mounted text GGUF file; do not use a guessed attachment path. Validate filename and file size against the lock, compute SHA-256, and save it with the runtime wheel hash. The package records the GGUF and template hashes in each backend identity. The GGUF tokenizer identity differs from the Transformers identity, so primary-model prompt token counts cannot be reused.

After the primary protocol is scientifically frozen, use the primary holdout manifest to select the balanced replication subset:

```bash
python -m graphtrust contexts --data data/swebench-lite --prepared runs/cpu --out runs/replication --stage replication --primary-manifest runs/holdout/manifest.json --freeze runs/protocol-frozen.json --tokenizer-backend gguf --tokenizer "$GRAPHTRUST_GGUF_MODEL" --pack-budget 2400 --input-budget 4000
python -m graphtrust validate --directory runs/replication
python -m graphtrust infer --contexts runs/replication/contexts.jsonl --out runs/replication/records.jsonl --backend gguf --model "$GRAPHTRUST_GGUF_MODEL" --seeds 17 --max-calls 180 --freeze runs/protocol-frozen.json
```

These commands require the generated local CPU corpus/graphs and accepted primary manifests. Run a development smoke check of the GGUF loading, rendering, disabled-thinking behavior and exact token counting first; never diagnose compatibility using holdout outcomes. Preserve the selected primary subset and disclose any secondary runtime qualification shortfall instead of selecting replacement cases. Record actual GPU memory and latency rather than treating file size as a memory or throughput measurement.

E4B/QAT/GGUF and E2B/Transformers differ in quantization and runtime. Analyze corruption effects within each model separately. The secondary run cannot support a clean causal claim about model size. If quota is insufficient, omit replication transparently and preserve the complete primary comparison.

If E2B GGUF is needed as the primary fallback, make that decision on development issues before freeze, regenerate every pilot arm with its own backend tokenizer, and repeat all six conditions with both seeds. This is an entire-study switch; individual failing holdout attempts cannot be substituted.
