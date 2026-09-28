"""telemetry pool — bounded samples, hardware windows, diagnostics bundles.

Long-running high-frequency samplers live inside this worker process when
enabled — never forever JobRuntime leases, never FastAPI-hosted forever loops.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool

_SECRET_ENV_KEYS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "API_KEY",
    "APIKEY",
    "CREDENTIAL",
    "PRIVATE",
)


def _sample_once() -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "ts": time.time(),
        "cpuPercent": "UNMEASURED",
        "memory": "UNMEASURED",
        "disk": "UNMEASURED",
        "gpu": "UNMEASURED",
    }
    try:
        import psutil

        metrics["cpuPercent"] = float(psutil.cpu_percent(interval=0.1))
        vm = psutil.virtual_memory()
        metrics["memory"] = {
            "total": int(vm.total),
            "available": int(vm.available),
            "percent": float(vm.percent),
        }
        du = psutil.disk_usage("/")
        metrics["disk"] = {
            "total": int(du.total),
            "free": int(du.free),
            "percent": float(du.percent),
        }
    except Exception:  # noqa: BLE001
        pass
    # GPU: never zero-fill — leave UNMEASURED when nvidia-smi absent.
    try:
        import subprocess

        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            gpus = []
            for line in proc.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    gpus.append(
                        {
                            "utilization": float(parts[0]),
                            "memoryUsedMiB": float(parts[1]),
                            "memoryTotalMiB": float(parts[2]),
                        }
                    )
            metrics["gpu"] = gpus or "UNMEASURED"
        else:
            metrics["gpu"] = "UNMEASURED"
    except Exception:  # noqa: BLE001
        metrics["gpu"] = "UNMEASURED"
    return metrics


def _redact_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(token in upper for token in _SECRET_ENV_KEYS):
            out[key] = "<REDACTED>"
        else:
            # Bound value length.
            out[key] = str(value)[:200]
    return out


def _collect_diagnostics(ctx: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    settings = ctx["settings"]
    sections = {
        "worker": {
            "workerId": ctx.get("worker_id"),
            "pool": "telemetry",
        },
        "runtime": {
            "platform": os.name,
            "pid": os.getpid(),
        },
        "telemetrySample": _sample_once(),
        "envRedacted": _redact_env() if args.get("include_env") else {"omitted": True},
        "omissions": [
            "api_tokens",
            "passwords",
            "full_conversations",
            "raw_database_dump",
            "broker_credentials",
        ],
        "app": {
            "artifactsRoot": str(getattr(getattr(settings, "artifacts", None), "root", "")),
        },
        "redactionPolicyVersion": 1,
        "collectedAt": time.time(),
    }
    art_root = Path(getattr(getattr(settings, "artifacts", None), "root", ".") or ".")
    out = art_root / "diagnostics" / f"{ctx.get('job_id', 'diag')}.json"
    # Prefer job id from args if present
    job = args.get("_job_id")
    if job:
        out = art_root / "diagnostics" / f"{job}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(sections, indent=2, default=str), encoding="utf-8")
    tmp.replace(out)
    return {
        "artifactRef": str(out),
        "sections": list(sections.keys()),
        "omissions": sections["omissions"],
        "redactionPolicyVersion": 1,
    }


def _hardware_window(args: dict[str, Any]) -> dict[str, Any]:
    duration = min(float(args.get("duration_seconds") or 5.0), 60.0)
    interval = max(float(args.get("interval_seconds") or 1.0), 0.25)
    deadline = time.monotonic() + duration
    samples: list[dict[str, Any]] = []
    dropped = 0
    while time.monotonic() < deadline:
        sample = _sample_once()
        if len(samples) >= 1000:
            dropped += 1
            samples.pop(0)
        samples.append(sample)
        time.sleep(interval)
    return {
        "sampleCount": len(samples),
        "droppedSamples": dropped,
        "durationSeconds": duration,
        "intervalSeconds": interval,
        "samples": samples[-20:],  # bound JobStore payload
        "truth": {"missingMetricIsUnmeasuredNotZero": True},
    }


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    cap = str(getattr(job, "capability_id", "") or "telemetry.sample")
    args = dict(getattr(job, "arguments", None) or {})
    args["_job_id"] = job.job_id
    try:
        if "diagnostics.collect" in cap or cap.endswith("diagnostics.collect"):
            result = _collect_diagnostics(ctx, args)
        elif "hardware_window" in cap or "process_window" in cap:
            result = _hardware_window(args)
        else:
            result = {"sample": _sample_once()}
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.COMPLETED,
            result=result,
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        fenced_transition(
            ctx["job_store"],
            job.job_id,
            JobState.FAILED,
            error=str(exc)[:500],
            worker_id=str(ctx.get("worker_id") or ""),
            ctx=ctx,
        )
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("telemetry", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
