"""Neural product HTTP routes — status, settings, domains, checkpoints.

Lazy-imports the Neural package so Normal HADES startup stays free of PyTorch
when Neural is unused. GUI must display truthful unavailable states.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["neural"])


class NeuralSettingsPatch(BaseModel):
    neural_allow: bool | None = None
    neural_mode: Literal["off", "shadow", "read", "learn"] | None = None
    neural_requirement: Literal["off", "preferred", "required"] | None = None
    neural_shadow_sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    neural_dual_memory_enabled: bool | None = None
    neural_domain_coding_enabled: bool | None = None
    neural_domain_research_enabled: bool | None = None
    neural_domain_trading_enabled: bool | None = None
    neural_max_concurrent_infer: int | None = Field(default=None, ge=1, le=64)
    expected_revision: int | None = None


def mount_neural_routes(ctx: dict[str, Any]) -> APIRouter:
    """Mount /neural/* routes. ``ctx`` requires ``database`` (settings store)."""

    def _db():
        database = ctx.get("database")
        if database is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        return database

    def _settings_values() -> dict[str, Any]:
        payload = _db().get_settings()
        return dict(payload or {})

    @router.get("/neural/status")
    async def neural_status() -> dict[str, Any]:
        def _status() -> dict[str, Any]:
            values = _settings_values()
            allow = bool(values.get("neural_allow"))
            mode = str(values.get("neural_mode") or "off")
            # Never start engines from a read-only status probe.
            try:
                from neural.deps import neural_available
                from neural.product_controller import get_neural_product_controller

                available = neural_available()
                controller = get_neural_product_controller()
                # Sync domain enables from settings without starting runtime.
                controller.domains.set_enabled("coding", bool(values.get("neural_domain_coding_enabled", True)))
                controller.domains.set_enabled("research", bool(values.get("neural_domain_research_enabled", True)))
                controller.domains.set_enabled("trading", bool(values.get("neural_domain_trading_enabled", False)))
                controller.domains.set_enabled("general", True)
                snap = controller.status()
                snap["settings"] = {
                    "neural_allow": allow,
                    "neural_mode": mode,
                    "neural_requirement": values.get("neural_requirement") or "off",
                    "neural_shadow_sample_rate": float(values.get("neural_shadow_sample_rate") or 0.0),
                    "neural_dual_memory_enabled": bool(values.get("neural_dual_memory_enabled")),
                }
                # F-06: READ is research-only until real LM fusion exists — never claim product-ready.
                snap["read_product_ready"] = False
                snap["mode_label"] = (
                    "research_only"
                    if mode == "read"
                    else "unsupported"
                    if mode == "learn"
                    else mode
                )
                if mode == "read":
                    snap["not_product_ready"] = True
                    snap["not_product_ready_reason"] = "neural_read_not_product_ready"
                snap["dependency_available"] = available
                # Truth: ready only if allow+mode imply an active runtime that is inference-ready.
                if not allow or mode == "off":
                    snap["ready"] = False
                    snap["product_state"] = "disabled"
                elif not available:
                    snap["ready"] = False
                    snap["product_state"] = "dependency_unavailable"
                else:
                    snap["product_state"] = "ready" if snap.get("ready") else snap.get("health", {}).get("state") or "idle"
                return snap
            except Exception as exc:  # noqa: BLE001
                return {
                    "ready": False,
                    "product_state": "unavailable",
                    "dependency_available": False,
                    "error": str(exc),
                    "settings": {
                        "neural_allow": allow,
                        "neural_mode": mode,
                    },
                    "artifacts": {
                        "base_model": "unknown",
                        "hades_adapter": None,
                        "fast_memory": "ephemeral_session",
                        "slow_memory": None,
                        "exact_brain": "separate",
                    },
                    "domains": {},
                }

        return await asyncio.to_thread(_status)

    @router.get("/neural/settings")
    async def neural_settings() -> dict[str, Any]:
        values = await asyncio.to_thread(_settings_values)
        return {
            "neural_allow": bool(values.get("neural_allow")),
            "neural_mode": str(values.get("neural_mode") or "off"),
            "neural_requirement": str(values.get("neural_requirement") or "off"),
            "neural_shadow_sample_rate": float(values.get("neural_shadow_sample_rate") or 0.0),
            "neural_dual_memory_enabled": bool(values.get("neural_dual_memory_enabled")),
            "neural_domain_coding_enabled": bool(values.get("neural_domain_coding_enabled", True)),
            "neural_domain_research_enabled": bool(values.get("neural_domain_research_enabled", True)),
            "neural_domain_trading_enabled": bool(values.get("neural_domain_trading_enabled", False)),
            "neural_max_concurrent_infer": int(values.get("neural_max_concurrent_infer") or 1),
            "learn_default": "disabled",
            "notes": [
                "LEARN changes durable Neural state and remains clearly distinct from READ.",
                "Neural systems recommend; they do not override permissions or policy.",
            ],
        }

    @router.patch("/neural/settings")
    async def patch_neural_settings(body: NeuralSettingsPatch) -> dict[str, Any]:
        def _patch() -> dict[str, Any]:
            db = _db()
            updates: dict[str, Any] = {}
            for key in (
                "neural_allow",
                "neural_mode",
                "neural_requirement",
                "neural_shadow_sample_rate",
                "neural_dual_memory_enabled",
                "neural_domain_coding_enabled",
                "neural_domain_research_enabled",
                "neural_domain_trading_enabled",
                "neural_max_concurrent_infer",
            ):
                value = getattr(body, key)
                if value is not None:
                    updates[key] = value
            if not updates:
                return {"updated": False, "values": {}}
            result = db.update_settings(updates)
            return {"updated": True, "values": {k: result.get(k) for k in updates}, "config_revision": result.get("config_revision")}

        try:
            return await asyncio.to_thread(_patch)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/neural/domains")
    async def neural_domains() -> dict[str, Any]:
        def _domains() -> dict[str, Any]:
            from neural.product_controller import get_neural_product_controller

            controller = get_neural_product_controller()
            values = _settings_values()
            controller.domains.set_enabled("coding", bool(values.get("neural_domain_coding_enabled", True)))
            controller.domains.set_enabled("research", bool(values.get("neural_domain_research_enabled", True)))
            controller.domains.set_enabled("trading", bool(values.get("neural_domain_trading_enabled", False)))
            return controller.domains.to_dict()

        return await asyncio.to_thread(_domains)

    @router.post("/neural/runtime/start")
    async def neural_runtime_start() -> dict[str, Any]:
        def _start() -> dict[str, Any]:
            values = _settings_values()
            allow = bool(values.get("neural_allow"))
            mode = str(values.get("neural_mode") or "off")
            from neural.product_controller import get_neural_product_controller

            controller = get_neural_product_controller()
            return controller.start(mode=mode, allow=allow, auto_load_model=True)

        return await asyncio.to_thread(_start)

    @router.post("/neural/runtime/stop")
    async def neural_runtime_stop() -> dict[str, Any]:
        def _stop() -> dict[str, Any]:
            from neural.product_controller import get_neural_product_controller

            return get_neural_product_controller().stop()

        return await asyncio.to_thread(_stop)

    @router.post("/neural/experience-ingest")
    async def neural_experience_ingest(
        limit: int = 32,
        query: str = "",
    ) -> dict[str, Any]:
        """Offline/batch verified-experience → ContinualLearningPipeline ingest.

        Requires neural_allow + mode in {read, shadow}. LEARN is refused.
        Never trains from raw assistant text.
        """

        def _ingest() -> dict[str, Any]:
            values = _settings_values()
            from neural.experience_ingest import maybe_ingest_verified_experiences

            store = ctx.get("gen2_store")
            report = maybe_ingest_verified_experiences(
                store,
                values,
                query=query,
                limit=max(1, min(int(limit or 32), 128)),
            )
            return report.to_dict()

        return await asyncio.to_thread(_ingest)

    return router
