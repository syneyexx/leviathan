from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HEALTH_MODULE = REPO_ROOT / "tools" / "local_startup_health.py"


def load_health_module():
    spec = importlib.util.spec_from_file_location("hades_local_startup_health_test", HEALTH_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load tools/local_startup_health.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status: int, body: str = "") -> None:
        self.status = status
        self._body = body.encode("utf-8")

    def read(self, _max_bytes: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class StartupReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.health = load_health_module()

    def test_http_error_status_is_not_ready(self) -> None:
        def opener(_url: str, *, timeout: float):
            self.assertEqual(timeout, 0.25)
            return FakeResponse(404, "HADES Local Bridge")

        self.assertFalse(
            self.health.is_url_ready(
                "http://127.0.0.1:8000/openapi.json",
                expected_text="HADES Local Bridge",
                timeout=0.25,
                opener=opener,
            )
        )

    def test_success_status_with_wrong_identity_is_not_ready(self) -> None:
        self.assertFalse(
            self.health.is_url_ready(
                "http://127.0.0.1:8000/openapi.json",
                expected_text="HADES Local Bridge",
                opener=lambda _url, timeout: FakeResponse(200, f"other service {timeout}"),
            )
        )

    def test_both_backend_and_frontend_are_required(self) -> None:
        def opener(url: str, *, timeout: float):
            del timeout
            if url.endswith("/openapi.json"):
                return FakeResponse(200, '{"info":{"title":"HADES Local Bridge"}}')
            raise OSError("frontend unavailable")

        self.assertFalse(
            self.health.wait_for_local_hades(
                attempts=1,
                opener=opener,
                sleep_fn=lambda _seconds: None,
            )
        )

    def test_all_required_hades_services_ready_returns_true(self) -> None:
        def opener(url: str, *, timeout: float):
            del timeout
            if url.endswith("/openapi.json"):
                return FakeResponse(200, '{"info":{"title":"HADES Local Bridge"}}')
            return FakeResponse(200, "<title>HADES — Local AI Workspace</title>")

        self.assertTrue(
            self.health.wait_for_local_hades(
                attempts=1,
                opener=opener,
                sleep_fn=lambda _seconds: None,
            )
        )

    def test_zero_attempts_fails_closed(self) -> None:
        self.assertFalse(
            self.health.wait_for_local_hades(
                attempts=0,
                opener=lambda _url, timeout: FakeResponse(200, str(timeout)),
                sleep_fn=lambda _seconds: None,
            )
        )

    def test_default_backend_probe_is_lightweight_identity_not_full_health(self) -> None:
        self.assertEqual(self.health.BACKEND_LIVENESS_URL, "http://127.0.0.1:8000/openapi.json")
        self.assertEqual(self.health.BACKEND_IDENTITY, "HADES Local Bridge")
        self.assertEqual(self.health.FRONTEND_IDENTITY, "HADES — Local AI Workspace")
        self.assertTrue(all("/api/health" not in url for url, _marker in self.health.DEFAULT_TARGETS))


if __name__ == "__main__":
    unittest.main()
