# HADES Adaptive Training Memory Engine (ATME)

**Baseline:** implemented on `origin/main` at `149a107f135e61eb5c8b9e26b39d5adad7a54f8f`  
**Architecture family (v1 streaming allowlist):** `llama_like` (Llama / Qwen2 / Qwen3 / Mistral-style decoder stacks)  
**Status:** software-complete for Phases 0–6 on this host; NVIDIA/Windows GPU runtime gates remain `UNVERIFIED_ON_HOST` here.

## What ATME adds

ATME extends the existing isolated TRAINEN worker. It does **not** replace Chat/Agents inference and does not import PyTorch into the normal HADES process.

Execution spectrum (fastest → slowest):

1. `gpu_resident`
2. `gpu_resident_4bit`
3. `cpu_offload`
4. `ram_layer_streaming`
5. `nvme_layer_streaming`
6. reject

`auto` selects the fastest **feasible** plan with confidence ≥ medium.

## Package layout

```text
backend/training/
  execution_plan.py
  hardware_probe.py
  model_inspector.py
  estimator.py
  compatibility.py
  planner.py
  telemetry.py
  benchmark.py
  failure_codes.py
  strategies/
  streaming/
```

Heavy streaming runtimes are only imported inside `training_worker.py`.

## API

Compatible extensions on `/api/training/*`:

- `GET /training/hardware`
- `POST /training/models/inspect`
- `POST /training/plans`
- `POST /training/benchmarks`
- `GET /training/benchmarks/latest`
- `GET /training/jobs/{id}/telemetry`

`TrainingJobInput` accepts `memory_strategy`, `activation_checkpointing`, `host_memory_limit_bytes`, `vram_reserve_bytes`, `stream_buffer_count`, `experimental_streaming_allowed` while preserving `load_in_4bit`.

## Persistence

Each job stores `requested_memory_strategy`, `resolved_execution_plan`, planner/model/hardware hashes, and runtime peak VRAM/RAM / H2D bytes. Secrets and raw records never enter `job.json` or telemetry.

## Verification notes

- Local unit/planner/buffer/parity tests: see `backend/tests/test_atme_*.py`
- CUDA peak-VRAM reduction vs resident: capability-gated; skipped without NVIDIA
- Windows pinned-memory / CUDA streams: `UNVERIFIED_ON_HOST` on this Linux cloud agent
- GitHub Actions: `NOT_RUN_GITHUB_CHECK_DISABLED_BY_USER`
- Streamed checkpoint **resume** is intentionally not advertised (`streamed_resume_supported=false`)

## Non-goals (unchanged)

ATME does not claim that arbitrary models fit in 16 GB VRAM, that NVMe equals VRAM, that GGUF is trainable, or that allocation success equals good throughput.
