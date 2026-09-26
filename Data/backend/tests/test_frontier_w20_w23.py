"""W20–W23 — multimodal, voice transport, data analysis, security honesty."""

from __future__ import annotations

import unittest

from Data.modules.common.security_ops import security_posture
from Data.modules.documents.intelligence import (
    declare_vision_capability,
    multimodal_eval_families,
    structure_from_extraction,
)
from Data.modules.execution.data_analysis import (
    AutomationBinding,
    mcp_trust_policy,
    safe_calculate,
    summarize_csv,
)
from Data.modules.voice.transport import VoiceTurnBridge, probe_voice_capabilities


class MultimodalW20Tests(unittest.TestCase):
    def test_vision_honesty_and_document_structure(self) -> None:
        unmeasured = declare_vision_capability(model_id="text-only", supports_vision=None, probed=False)
        self.assertEqual(unmeasured.vision, "UNMEASURED")
        self.assertTrue(unmeasured.public_dict()["truth"]["unmeasured_is_not_supported"])
        unsupported = declare_vision_capability(model_id="t", supports_vision=False, probed=True)
        self.assertEqual(unsupported.vision, "UNSUPPORTED")
        doc = structure_from_extraction(
            source_path="/tmp/a.pdf",
            text="hello",
            pages=[{"page": 1, "text": "hello"}],
            tables=[{"page": 1, "rows": 2}],
            ocr_confidence=0.91,
        )
        payload = doc.public_dict()
        self.assertEqual(payload["ocr_status"], "MEASURED")
        self.assertTrue(payload["truth"]["not_independent_multimodal_runtime"])
        families = multimodal_eval_families()
        self.assertTrue(all(f["status"] == "FEATURE_GATED" for f in families))


class VoiceW21Tests(unittest.TestCase):
    def test_voice_is_transport(self) -> None:
        status = probe_voice_capabilities(asr_ready=None, tts_ready=False)
        payload = status.public_dict()
        self.assertEqual(payload["asr"], "NOT_CONFIGURED")
        self.assertEqual(payload["tts"], "UNAVAILABLE")
        self.assertTrue(payload["truth"]["voice_is_transport"])
        bridge = VoiceTurnBridge(conversation_id="c1", transcript_final="hi")
        self.assertTrue(bridge.public_dict()["truth"]["no_second_assistant"])


class DataAnalysisW22Tests(unittest.TestCase):
    def test_safe_calculate_and_csv_and_mcp_policy(self) -> None:
        ok = safe_calculate("(2+3)*4")
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["value"], 20.0)
        bad = safe_calculate("__import__('os').system('x')")
        self.assertFalse(bad["ok"])
        csv_summary = summarize_csv("a,b\n1,2\n3,4\n")
        self.assertEqual(csv_summary["row_count"], 2)
        self.assertTrue(mcp_trust_policy()["tool_description_is_metadata_not_system_authority"])
        auto = AutomationBinding(job_kind="schedules.run").public_dict()
        self.assertTrue(auto["truth"]["no_automation_runtime_v2"])


class SecurityW23Tests(unittest.TestCase):
    def test_security_posture_honesty(self) -> None:
        loop = security_posture(loopback=True, auth_configured=False, secrets_broker=True)
        self.assertEqual(loop["auth"]["status"], "MEASURED")
        self.assertIn("owner", loop["rbac_roles"])
        remote = security_posture(loopback=False, auth_configured=False, secrets_broker=False)
        self.assertEqual(remote["auth"]["status"], "UNMEASURED")
        self.assertTrue(remote["truth"]["unmeasured_os_enforcement_is_not_secure"])


if __name__ == "__main__":
    unittest.main()
