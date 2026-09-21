"""Best-effort local memory gate before TTS synthesis.

Never unloads or switches the user's LM Studio model. Only refuses a new TTS
request when free host memory is clearly too low for an additional local engine.
"""

from __future__ import annotations

from typing import Any


def probe_host_memory() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ram_total_mb": None,
        "ram_available_mb": None,
        "vram_total_mb": None,
        "vram_free_mb": None,
        "notes": [],
    }
    try:
        import psutil  # type: ignore

        mem = psutil.virtual_memory()
        result["ram_total_mb"] = round(mem.total / (1024 * 1024))
        result["ram_available_mb"] = round(mem.available / (1024 * 1024))
    except Exception as exc:  # pragma: no cover - optional dependency
        result["notes"].append(f"RAM-probe niet beschikbaar: {exc}")

    # Optional NVIDIA probe — never required; absence must not block TTS.
    try:
        import subprocess

        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            shell=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            first = proc.stdout.strip().splitlines()[0]
            total_s, free_s = [part.strip() for part in first.split(",")]
            result["vram_total_mb"] = int(float(total_s))
            result["vram_free_mb"] = int(float(free_s))
        else:
            result["notes"].append("Geen betrouwbare VRAM-meting (nvidia-smi ontbreekt of faalde).")
    except Exception:
        result["notes"].append("VRAM niet gemeten — TTS mag doorgaan zonder GPU-cijfers.")

    return result


def evaluate_tts_memory_budget(
    *,
    min_free_ram_mb: int = 1500,
    min_free_vram_mb: int = 0,
    engine_min_vram_gb: float | None = None,
) -> dict[str, Any]:
    probe = probe_host_memory()
    reasons: list[str] = []
    ok = True

    available = probe.get("ram_available_mb")
    if isinstance(available, (int, float)) and min_free_ram_mb > 0 and available < min_free_ram_mb:
        ok = False
        reasons.append(
            f"Onvoldoende vrij RAM ({int(available)} MB < {min_free_ram_mb} MB). "
            "Laad geen extra TTS-engine oncontroleerd naast LM Studio."
        )

    required_vram = max(float(min_free_vram_mb or 0), float(engine_min_vram_gb or 0) * 1024)
    free_vram = probe.get("vram_free_mb")
    if required_vram > 0 and isinstance(free_vram, (int, float)) and free_vram < required_vram:
        ok = False
        reasons.append(
            f"Onvoldoende vrije VRAM ({int(free_vram)} MB < {int(required_vram)} MB) "
            "voor de gekozen VoiceStudio-engine naast het actieve LM Studio-model. "
            "HADES forceert geen modelontlading."
        )

    return {
        "ok": ok,
        "probe": probe,
        "reasons": reasons,
        "forced_model_unload": False,
    }
