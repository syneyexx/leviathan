# One Brain vs Cognition vs Model Runtime

LEVIATHAN separates these responsibilities deliberately:

| Layer | Owns | Does not own |
| --- | --- | --- |
| **One Brain** | Shared knowledge / memory / evidence / experience access | Model selection, weights, VRAM |
| **Cognition** | How a task is approached (strategy, orchestration roles) | Physical model residency |
| **ContextBuilder** | What the selected model invocation sees | Loading models |
| **Model Control Plane** | Routing, residency, gateway, providers | Brain storage |
| **ResidencyManager** | Whether/where a model is physically available | Inference QoS (Gateway) |
| **Gateway** | Concurrency / priority admission | Loading weights |
| **Runtime adapters** | llama.cpp / vLLM / external HTTP inference | Registry identity |

## Logical routing vs physical residency

- **Active/default model** is a routing default. It does **not** mean the model is loaded.
- **Role assignments** (General/`chat`, Coding, Research, …) select which model id is preferred.
- **Explicit request/session model** always wins over role/default/fallback.
- **Residency leases** protect live inference. The same model shared by General + Coding loads **once**.

## Managed vs external

| Kind | Examples | LEVIATHAN may |
| --- | --- | --- |
| Managed | llama.cpp worker, vLLM worker | start/stop process, claim PID, unload |
| External | LM Studio, remote OpenAI-compatible | route + HTTP only — never kill process / invent VRAM release |

## Residency policies

- `KEEP_HOT` — remain resident after last lease
- `IDLE_UNLOAD` — unload after idle timeout (worker exits)
- `WARM_THEN_UNLOAD` — only if a backend truly supports GPU→RAM demotion (currently unsupported / rejected)

## Large-model offload

llama.cpp may use real `-ngl` GPU layer offload. Placement is reported as CPU / GPU / HYBRID only when options make that known; otherwise UNKNOWN. Never fabricate VRAM.

## Troubleshooting

- Missing `LEVIATHAN_LLAMA_CPP_EXECUTABLE` → managed GGUF is **UNAVAILABLE**, not echo-success.
- Stale READY after restart → reconciled to DEAD/UNLOADED (leases never restored).
- Unload with active leases → HTTP 409 `MODEL_ACTIVE_LEASES`.
