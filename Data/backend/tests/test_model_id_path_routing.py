"""Model API path routing — slash-bearing IDs must not 405 / shadow suffixes."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.config import Settings
from Data.backend.migrations import MigrationRunner
from Data.backend.routes.models import MODELS_STATIC_SEGMENTS, build_models_router
from Data.modules.models import ModelControlPlane
from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelDescriptor,
    ModelLifecycleState,
    ModelSource,
)


def _descriptor(model_id: str, *, provider_id: str = "lm_studio") -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id,
        display_name=model_id.split(":")[-1],
        provider_id=provider_id,
        source=ModelSource.REMOTE,
        capabilities=ModelCapabilities(
            chat=CapabilityState.UNVERIFIED,
            streaming=CapabilityState.UNVERIFIED,
        ),
        lifecycle_state=ModelLifecycleState.AVAILABLE,
    )


def _is_routing_miss(resp) -> bool:
    """True only for route/method miss — not domain 404s like PROVIDER_NOT_FOUND."""
    if resp.status_code == 405:
        return True
    if resp.status_code != 404:
        return False
    try:
        detail = resp.json().get("detail")
    except Exception:  # noqa: BLE001
        return True
    if isinstance(detail, dict):
        code = str(detail.get("code") or "")
        if code == "route_not_found":
            return True
        if code in {
            "MODEL_NOT_FOUND",
            "PROVIDER_NOT_FOUND",
            "CAPABILITY_NOT_SUPPORTED",
            "VALIDATION_ERROR",
        }:
            return False
        return False
    return True


class ModelIdPathRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "control.db"
        self._prev = os.environ.get("LEVIATHAN_DATABASE_PATH")
        os.environ["LEVIATHAN_DATABASE_PATH"] = str(db)
        os.environ.setdefault("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", "false")
        settings = Settings.from_env()
        MigrationRunner(settings.database_path).apply_all()
        self.plane = ModelControlPlane(settings)
        self.plane.bootstrap()
        app = FastAPI()
        app.include_router(build_models_router(self.plane))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("LEVIATHAN_DATABASE_PATH", None)
        else:
            os.environ["LEVIATHAN_DATABASE_PATH"] = self._prev
        self.tmp.cleanup()

    def _register(self, model_id: str) -> None:
        self.plane.registry.upsert_discovered(
            [_descriptor(model_id, provider_id="lm_studio")],
            provider_id="lm_studio",
        )

    def test_static_segments_listed(self) -> None:
        self.assertIn("status", MODELS_STATIC_SEGMENTS)
        self.assertIn("hardware", MODELS_STATIC_SEGMENTS)
        self.assertIn("residency", MODELS_STATIC_SEGMENTS)

    def test_static_routes_not_shadowed(self) -> None:
        r = self.client.get("/api/models/status")
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.get("/api/models/hardware")
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.get("/api/models/residency")
        self.assertEqual(r.status_code, 200, r.text)

    def test_simple_and_slash_ids(self) -> None:
        cases = [
            "simple-model",
            "provider:model",
            "provider:org/model",
            "provider:org/deep/model",
            "provider:model with space",
            "provider:模型/测试",
        ]
        for model_id in cases:
            with self.subTest(model_id=model_id):
                self._register(model_id)
                encoded = quote(model_id, safe="")
                r = self.client.get(f"/api/models/{encoded}")
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["model"]["id"], model_id)
                if "/" in model_id:
                    r2 = self.client.get(f"/api/models/{model_id}")
                    self.assertEqual(r2.status_code, 200, r2.text)
                    self.assertEqual(r2.json()["model"]["id"], model_id)
                for path, method in (
                    (f"/api/models/{encoded}/profile", "GET"),
                    (f"/api/models/{encoded}/residency", "GET"),
                    (f"/api/models/{encoded}/capabilities", "GET"),
                    (f"/api/models/{encoded}/activate", "POST"),
                    (f"/api/models/{encoded}/unload", "POST"),
                ):
                    resp = self.client.request(method, path)
                    self.assertFalse(
                        _is_routing_miss(resp),
                        f"{method} {path} -> {resp.status_code} {resp.text}",
                    )
                    if method == "GET":
                        self.assertEqual(resp.status_code, 200, resp.text)

                put_profile = self.client.put(
                    f"/api/models/{encoded}/profile",
                    json={"temperature": 0.5},
                )
                self.assertFalse(_is_routing_miss(put_profile), put_profile.text)
                put_res = self.client.put(
                    f"/api/models/{encoded}/residency-policy",
                    json={"pinned": False},
                )
                self.assertFalse(_is_routing_miss(put_res), put_res.text)

                for suffix in ("probe", "benchmark", "test", "load"):
                    body: dict = {"prompt": "ping"} if suffix == "test" else {}
                    resp = self.client.post(f"/api/models/{encoded}/{suffix}", json=body)
                    self.assertFalse(
                        _is_routing_miss(resp),
                        f"POST {suffix} -> {resp.status_code} {resp.text}",
                    )

                deleted = self.client.delete(f"/api/models/{encoded}")
                self.assertFalse(_is_routing_miss(deleted), deleted.text)

    def test_profile_suffix_not_swallowed_by_detail(self) -> None:
        model_id = "provider:org/deep/model"
        self._register(model_id)
        r = self.client.get(f"/api/models/{model_id}/profile")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("profile", r.json())
        r2 = self.client.get(f"/api/models/{model_id}")
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["model"]["id"], model_id)

    def test_route_table_orders_suffixes_before_bare_detail(self) -> None:
        src = Path(__file__).resolve().parents[1] / "routes" / "models.py"
        text = src.read_text(encoding="utf-8")
        self.assertLess(
            text.index('@router.get("/api/models/{model_id:path}/profile")'),
            text.index('@router.get("/api/models/{model_id:path}")'),
        )
        self.assertLess(
            text.index('@router.post("/api/models/{model_id:path}/activate")'),
            text.index('@router.get("/api/models/{model_id:path}")'),
        )
        self.assertLess(
            text.index('@router.get("/api/models/{model_id:path}")'),
            text.index('@router.delete("/api/models/{model_id:path}")'),
        )


if __name__ == "__main__":
    unittest.main()
