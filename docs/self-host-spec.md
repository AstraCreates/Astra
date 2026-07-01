# Self-Host Spec — Final Decisions

## Model

**Qwen3.6-35B-A3B MoE Q4_K_M GGUF** (MoE — 35B total, ~3B active params per token)

| Param | Value |
|---|---|
| Weight quant | Q4_K_M GGUF — 21 GB on-disk |
| KV quant | Q4 (`-ctk q4_0 -ctv q4_0`) |
| Default context | 32K tokens (extendable) |
| Serving stack | llama-server (NOT vLLM — GGUF not supported) |
| Thinking mode | Disabled in API calls (`enable_thinking: False`) |

**Why MoE wins at this scale:** ~3B active params per token despite 35B total parameters.
That means memory bandwidth demand per forward pass is roughly equivalent to a 3B dense model
while retaining the knowledge and reasoning quality of a 35B model. At 600 GB/s (M5 Ultra)
this is compute-bound, not memory-bound, at any realistic concurrency.

**KV cache Q4 quantization:** 4× memory reduction with <1% throughput loss. With 21 GB model
weight + Q4 KV on 256 GB unified RAM, ~235 GB remains for KV cache — effectively unlimited
headroom for concurrent sessions at typical context lengths.

---

## Serving Command

```bash
llama-server \
  --model qwen3.6-35b-a3b-q4_k_m.gguf \
  --parallel 4 \
  --cont-batching \
  -ctk q4_0 \
  -ctv q4_0 \
  --port 8080
```

`--parallel 4` + `--cont-batching`: serves 4 simultaneous decode streams, continuous batching
fills gaps between them. Benchmark result: **0 failures at 25 concurrent users**.

---

## Benchmark Results

| Metric | Value |
|---|---|
| Single-user throughput | 75 tok/s |
| Aggregate at 25 concurrent users | 170 tok/s |
| Failures at 25 concurrent users | 0 |
| Hardware | M5 Ultra 256 GB (600 GB/s bandwidth) |

---

## Hardware Target

### Mac Studio M5 Ultra — inference node

- 256 GB unified RAM (recommended); 512 GB available if needed
- 600 GB/s memory bandwidth
- Model (21 GB) + Q4 KV for all active streams fits comfortably in unified memory
- KV reads at memory-bus speed (not PCIe) → no bottleneck at any practical concurrency

### Why M5 Ultra vs alternatives

| Option | RAM | Bandwidth | Model fits | Notes |
|---|---|---|---|---|
| M5 Ultra 256 GB | 256 GB | 600 GB/s | Yes (21 GB) | Recommended |
| DGX Spark | 128 GB | 273 GB/s | Yes | Lower bandwidth, fewer streams |
| RTX PRO 5000 | 72 GB VRAM | PCIe limited | Yes | VRAM-bound for KV; paused sessions on host RAM |

---

## Thinking Mode

llama.cpp/llama-server exposes Qwen3 thinking mode via `chat_template_kwargs`. Disable it for
production API calls to avoid unpredictable latency spikes:

```python
# In API call kwargs
extra_body = {
    "chat_template_kwargs": {"enable_thinking": False}
}
```

Thinking mode can be selectively enabled for planner agents that benefit from extended reasoning,
but should be off by default for all other agents.

---

## Astra Config Flags (set in .env when self-hosting)

```env
ASTRA_SELF_HOST=true
SELF_HOST_BASE_URL=http://localhost:8080/v1   # llama-server OpenAI-compat endpoint
SELF_HOST_MODEL=qwen3.6-35b-a3b-q4_k_m       # whatever llama-server loads as
ASTRA_NATIVE_TOOL_CALLS=true                  # self-hosted model supports function calling
ASTRA_COMPRESSION_THRESHOLD=32768             # match context window
```

`factory.py` `_self_host_override()` routes all agent kwargs to the local endpoint when these
are set. `capabilities_for()` in `model_catalog.py` automatically returns `native_tool_calls=True`
for the self-hosted model when `ASTRA_SELF_HOST=true`.

---

## Economics Trigger

Self-hosting beats OpenRouter when sustained utilization justifies capex. The 21 GB GGUF +
llama-server setup runs on a single M5 Ultra 256 GB (~$9K), serving 25+ concurrent users
with zero failures.

Current cloud rate reference:
- deepseek-v4-flash: $0.09/$0.18 per 1M (subsidized, will reprice)
- deepseek-v4-pro: $0.435/$0.87 per 1M

At 20+ sustained concurrent users, self-host amortizes in under 12 months vs API bills.

---

## Previous Spec (superseded)

The prior spec targeted **Qwen3-Coder 122B-A10B AWQ + vLLM** on Mac Studio M3 Ultra 512 GB.
That was superseded by benchmarking results showing Qwen3.6-35B-A3B MoE Q4_K_M on llama-server
delivers equivalent agent quality at 75 tok/s single-user / 170 tok/s aggregate, fits in 21 GB
GGUF (vs 61 GB AWQ), and runs on a 256 GB M5 Ultra rather than requiring a 512 GB M3 Ultra.
