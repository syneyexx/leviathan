# Adaptive Model Fabric — Hardware Topology & Per-Device Placement

## Ownership

| Concern | Owner |
|---|---|
| Public model façade | `ModelControlPlane` |
| Model identity / metadata | Model Registry |
| Logical model selection | Model Router / MeasuredRouter |
| Resource requirements, hardware snapshot, placement planning | **ResourceManager** |
| Cross-process physical reservations | **ResourceAdmission** |
| Live model lifecycle / leases | ModelResidencyManager |
| Local serving process lifecycle | ServingSupervisor |
| Inference QoS (INTERACTIVE / BACKGROUND / BATCH) | ModelGateway |
| Backend-native device/launch argv+env | BackendLaunchStrategy + provider adapters |
| Generic background workers | WorkerSupervisor |

Do **not** collapse these into one class. Do **not** create parallel V2 managers.

## Aggregate vs contiguous VRAM

For a machine with:

- GPU 0 = 16 GB
- GPU 1 = 6 GB

LEVIATHAN reports:

- `aggregatePhysicalVramBytes` = 22 GB (**informational**)
- `largestSingleDeviceTotalBytes` = 16 GB (**placement-relevant**)

A single non-sharded model requiring 18 GB is **rejected** even though aggregate is 22 GB.

## Placement flow (managed local)

```
Request → Router → resource requirement → ResourceManager.plan_placement
  → ResourceAdmission.try_reserve (device-aware)
  → RuntimeManager.load(deployment_plan)
  → BackendLaunchStrategy (argv + CUDA_VISIBLE_DEVICES)
  → ServingSupervisor → READY → PlacementReceipt
  → Gateway → inference → measured feedback → unload/release
```

External API providers bypass local physical placement (`PhysicalPlacement.EXTERNAL`).

## Reservations

One SQLite table: `resource_reservations` (migration 41 adds device columns).

- `GPU_EXCLUSIVE` is **per device** when `device_stable_id` is known
- `GPU_SHARED` is **amount-aware**
- Accounting modes: `PENDING_LOAD` | `LIVE_MEASURED` | `LIVE_UNMEASURED` | `RELEASED`
- LIVE_MEASURED uses measured VRAM as occupancy; reservation is **not** double-counted

## Stable device identity

Prefer vendor UUID → PCI bus id → ordinal+name fallback.

`stableDeviceId` and `currentOrdinal` are separate. Hard pins bind to stable IDs so ordinal swaps after reboot do not silently retarget another GPU.

## Multi-GPU

Backend-native only, capability-gated (`SUPPORTED` | `UNSUPPORTED` | `UNKNOWN` | `UNVERIFIED`).

- llama.cpp: `--tensor-split`, `--main-gpu`, device visibility
- vLLM-class: `--tensor-parallel-size` only when verified; asymmetric 16+6 TP is rejected
- Default asymmetric policy: **workload separation** (main on large GPU, specialist on small)

## Low-RAM / Windows

Host RAM pressure: `NORMAL` | `WARNING` | `CRITICAL` | `UNKNOWN`.

CPU offload under CRITICAL pressure is refused. Telemetry uses psutil (Windows-capable) + optional nvidia-smi; unknown metrics stay unknown (never fabricated 0°C / 0 MB).

## API

- `GET /api/models/hardware` — inventory + reservations + residency
- `POST /api/models/{id}/placement-preflight` — dry-run (no load, no reserve)
- `PUT /api/models/hardware/policy` — device enable/headroom policy
- `GET /api/models/reservations` — held reservations

## UI truth rules

- Temperature unknown → show **Unknown**, not 0°C
- Always show both aggregate and largest-single-GPU
- Unsupported multi-GPU controls stay disabled with reason

## Brain invariant

GPU/placement/quantization changes never reindex, delete, or duplicate Brain.
