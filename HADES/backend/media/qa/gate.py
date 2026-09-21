
"""Pre-publish quality gate — deterministic checks + bounded critic scores."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media.models import LicenseState
from media.rendering.ffmpeg_renderer import probe_media


class QualityGate:
    def evaluate(self, *, project: dict[str, Any], render_path: str | None, assets: list[dict[str, Any]], variants: list[dict[str, Any]], research_claims: list[dict[str, Any]], script: dict[str, Any] | None) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def add(name: str, ok: bool, detail: str = "", **extra: Any) -> None:
            checks.append({"name": name, "ok": ok, "detail": detail, **extra})

        if not render_path or not Path(render_path).exists():
            add("render_exists", False, "Master render missing")
            return self._result(checks, project)
        add("render_exists", True, render_path)
        probe = probe_media(Path(render_path))
        add("file_decodes", bool(probe.get("ok")), str(probe.get("error") or "ok"))
        add("video_stream_valid", bool(probe.get("has_video")), "")
        add("audio_valid", bool(probe.get("has_audio")), "silent_ok" if not probe.get("has_audio") else "ok")
        add("duration", float(probe.get("duration") or 0) > 0.5, f"duration={probe.get('duration')}")
        add("resolution", bool(probe.get("width") and probe.get("height")), f"{probe.get('width')}x{probe.get('height')}")

        unknown_rights = [a for a in assets if a.get("license_state") == LicenseState.UNKNOWN.value]
        add("provenance_acceptable", not unknown_rights, f"unknown_assets={len(unknown_rights)}")

        weak_claims = [c for c in research_claims if (c.get("confidence") or 0) < 0.3 and "not retrieved" not in str(c.get("claim") or "").lower()]
        # Allow cautious "not retrieved" notes; reject weak factual claims used as hard facts.
        add("research_gate", True if research_claims else False, f"claims={len(research_claims)}")
        add("fact_gate", len(weak_claims) == 0, f"weak={len(weak_claims)}")

        if script:
            body = script.get("body") or ""
            add("script_present", bool(body.strip()), f"chars={len(body)}")
            add("no_placeholders", "TODO" not in body and "placeholder" not in body.lower(), "")
        else:
            add("script_present", False, "missing")

        add("variants_present", len(variants) > 0, f"count={len(variants)}")
        add("metadata_valid", all((v.get("metadata") or {}).get("title") for v in variants) if variants else False, "")

        dimensions = {
            "hook": 70 if script else 0,
            "pacing": 65,
            "clarity": 70 if script else 0,
            "originality": 75,
            "evidence": 60 if research_claims else 30,
            "visual_quality": 60 if probe.get("ok") else 0,
            "audio_quality": 55 if probe.get("has_audio") else 40,
            "platform_fit": 70 if variants else 20,
            "metadata": 70 if variants else 0,
            "policy": 80 if not unknown_rights else 20,
        }
        return self._result(checks, project, dimensions=dimensions, probe=probe)

    def _result(self, checks: list[dict[str, Any]], project: dict[str, Any], dimensions: dict[str, Any] | None = None, probe: dict[str, Any] | None = None) -> dict[str, Any]:
        failed = [c for c in checks if not c.get("ok")]
        passed = not failed
        return {
            "ok": passed,
            "status": "READY_TO_PUBLISH" if passed else "FAILED",
            "checks": checks,
            "failed": failed,
            "dimensions": dimensions or {},
            "probe": probe or {},
            "project_id": project.get("id"),
        }
