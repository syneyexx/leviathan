from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from voice.routes import InstallInput, mount_voice_routes


def _install_endpoint(settings: dict[str, object]):
    router = mount_voice_routes({"runtime_values": lambda: dict(settings)})
    endpoint = None
    for route in router.routes:
        if getattr(route, "path", None) == "/voice/install":
            # Module-level router accumulates mounts; use the latest binding.
            endpoint = route.endpoint
    if endpoint is None:
        raise AssertionError("voice install route not found")
    return endpoint


class VoiceInstallPolicyBoundaryTests(unittest.TestCase):
    def test_dependency_install_respects_subprocess_block(self) -> None:
        endpoint = _install_endpoint({"network_policy": "allow", "subprocess_policy": "block"})
        with patch("voice.routes.run_install", return_value={"ok": True}) as run_install:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    endpoint(
                        InstallInput(
                            steps=["deps"],
                            approved_network=True,
                            approved_subprocess=True,
                        )
                    )
                )
        self.assertEqual(raised.exception.status_code, 403)
        run_install.assert_not_called()

    def test_model_download_respects_network_block(self) -> None:
        endpoint = _install_endpoint({"network_policy": "block", "subprocess_policy": "allow"})
        with patch("voice.routes.run_install", return_value={"ok": True}) as run_install:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    endpoint(
                        InstallInput(
                            steps=["piper_voice"],
                            approved_network=True,
                        )
                    )
                )
        self.assertEqual(raised.exception.status_code, 403)
        run_install.assert_not_called()

    def test_dependency_install_requires_explicit_subprocess_approval_when_asked(self) -> None:
        endpoint = _install_endpoint({"network_policy": "allow", "subprocess_policy": "ask"})
        with patch("voice.routes.run_install", return_value={"ok": True}) as run_install:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(endpoint(InstallInput(steps=["deps"], approved_network=True)))
        self.assertEqual(raised.exception.status_code, 409)
        run_install.assert_not_called()

    def test_model_download_requires_explicit_network_approval_when_asked(self) -> None:
        endpoint = _install_endpoint({"network_policy": "ask", "subprocess_policy": "allow"})
        with patch("voice.routes.run_install", return_value={"ok": True}) as run_install:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(endpoint(InstallInput(steps=["piper_voice"])))
        self.assertEqual(raised.exception.status_code, 409)
        run_install.assert_not_called()

    def test_explicit_approvals_allow_requested_install_steps(self) -> None:
        endpoint = _install_endpoint({"network_policy": "ask", "subprocess_policy": "ask"})
        with patch("voice.routes.run_install", return_value={"ok": True}) as run_install:
            result = asyncio.run(
                endpoint(
                    InstallInput(
                        steps=["deps"],
                        approved_network=True,
                        approved_subprocess=True,
                    )
                )
            )
        self.assertEqual(result, {"ok": True})
        run_install.assert_called_once()


if __name__ == "__main__":
    unittest.main()
