"""Regression: voice CANCELLED must not be wrapped as COMPLETED (Phase 1.3)."""

from __future__ import annotations

import unittest
from typing import Any

from Data.modules.execution import (
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    SideEffect,
)


class _CancelVoiceExecutor:
    def execute(
        self,
        *,
        action: Any,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "CANCELLED",
            "detail": "barge_in",
            "session_id": (arguments or {}).get("session_id"),
            "action": action,
        }


class VoiceCancelStatusTests(unittest.TestCase):
    def test_voice_cancelled_returns_cancelled_not_completed(self) -> None:
        catalog = CapabilityCatalog()
        catalog.register(
            CapabilityDefinition(
                id="voice.test_cancel",
                name="Voice Test Cancel",
                description="Test-only voice cancel path",
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.VOICE,
                provider_ref="cancel",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {"session_id": {"type": "string"}},
                },
                output_schema={"type": "object"},
                metadata={"execution_class": "INLINE_SAFE"},
            )
        )
        gateway = ExecutionGateway(
            catalog=catalog,
            voice_executor=_CancelVoiceExecutor(),
        )
        result = gateway.execute(
            CapabilityRequest(
                capability_id="voice.test_cancel",
                arguments={"session_id": "sess-1"},
            )
        )
        self.assertEqual(result.status, CapabilityStatus.CANCELLED)
        self.assertNotEqual(result.status, CapabilityStatus.COMPLETED)
        self.assertIsInstance(result.output, dict)
        self.assertEqual((result.output or {}).get("status"), "CANCELLED")
        self.assertEqual(gateway.telemetry.get("cancellations"), 1)
        self.assertEqual(gateway.telemetry.get("completed"), 0)


if __name__ == "__main__":
    unittest.main()
