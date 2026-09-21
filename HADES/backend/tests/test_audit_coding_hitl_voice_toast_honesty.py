"""Coding apply/job toasts, HITL reject, PR-help, and speak-response empty honesty."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]


class CodingHitlVoiceToastHonestyTests(unittest.TestCase):
    def test_coding_agent_job_toast_gates_success_statuses(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "coding-agent-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('const JOB_SUCCESS = new Set(["verified", "completed"]);', page)
        self.assertIn("if (JOB_SUCCESS.has(st))", page)
        self.assertIn("toast.error(`Job eindstatus: ${buildStatusLabel(st)}`)", page)
        self.assertIn("if (JOB_SUCCESS.has(status))", page)
        self.assertIn("toast.error(`Build-run eindstatus: ${buildStatusLabel(status)}`)", page)
        self.assertNotIn(
            "toast.success(`Job eindstatus: ${buildStatusLabel(st)}`);\n          void refreshRecentJobs();",
            page,
        )

    def test_coding_agent_apply_requires_files(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "coding-agent-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("result.applied === true && Number(result.file_count ?? 0) > 0", page)
        self.assertIn("Apply leverde geen bestanden op.", page)

    def test_apply_to_source_empty_diff_is_not_applied(self) -> None:
        from build_agent import BuildAgentService

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            source.mkdir()
            (source / "readme.txt").write_text("hello\n", encoding="utf-8")
            agent = BuildAgentService(root)
            run_id = "run_empty_apply"
            work = agent.runs_root / run_id / "work"
            work.mkdir(parents=True)
            (work / "readme.txt").write_text("hello\n", encoding="utf-8")
            (agent.runs_root / run_id / "meta.json").write_text(
                json.dumps({"source": str(source), "work_root": str(work)}),
                encoding="utf-8",
            )
            with patch.object(agent, "check_apply_conflicts", return_value=[]):
                with patch.object(agent, "_changed_files", return_value=[]):
                    outcome = agent.apply_to_source(run_id, approved=True)
            self.assertFalse(outcome.get("applied"))
            self.assertEqual(outcome.get("status"), "noop")
            self.assertEqual(outcome.get("file_count"), 0)
            self.assertEqual(outcome.get("error"), "no_files_applied")

    def test_pr_help_toast_gates_ok(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "mission-control-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("if ((result as { ok?: boolean }).ok)", page)
        self.assertIn("PR-help mislukt (run niet gevonden).", page)

    def test_workflow_hitl_reject_uses_error_toast(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "workflows-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('hitlStatus === "failed"', page)
        self.assertIn('hitlDecision === "reject"', page)
        self.assertIn("resumeFailed", page)
        self.assertIn('toast.error(', page)
        self.assertIn('HITL:', page)
        self.assertNotIn('toast.success(`HITL: ${String(result.status || "besloten")}`)', page)

    def test_speak_response_empty_segments_honesty_markers(self) -> None:
        src = (ROOT / "backend" / "voice" / "routes.py").read_text(encoding="utf-8")
        self.assertIn('"error": "no_speech_segments"', src)
        self.assertIn('"skipped": "already_spoken"', src)
        self.assertIn("if spoken_key in session.spoken_response_ids", src)
        self.assertIn("if events:", src)

    def test_speak_response_empty_vs_idempotent(self) -> None:
        """Empty synthesis without spoken mark fails; mark present is idempotent skip."""
        from fastapi.testclient import TestClient

        import main
        from voice.runtime import get_session_manager

        client = TestClient(main.app)
        mgr = get_session_manager()
        session = mgr.start(conversation_id="audit-speak-empty", client_tab_id="tab-audit", force=True)
        try:
            with patch("voice.routes.synthesize_response_segments", return_value=[]):
                empty = client.post(
                    "/api/voice/session/speak-response",
                    json={
                        "session_id": session.session_id,
                        "response_id": "resp-audit-empty",
                        "text": "Hallo wereld.",
                    },
                )
            self.assertEqual(empty.status_code, 200, empty.text)
            body = empty.json()
            self.assertFalse(body.get("ok"))
            self.assertEqual(body.get("error"), "no_speech_segments")

            session.spoken_response_ids.add(f"resp-audit-skip:{session.generation}")
            with patch("voice.routes.synthesize_response_segments", return_value=[]):
                skipped = client.post(
                    "/api/voice/session/speak-response",
                    json={
                        "session_id": session.session_id,
                        "response_id": "resp-audit-skip",
                        "text": "Hallo wereld.",
                    },
                )
            self.assertEqual(skipped.status_code, 200, skipped.text)
            body2 = skipped.json()
            self.assertTrue(body2.get("ok"))
            self.assertEqual(body2.get("skipped"), "already_spoken")
        finally:
            mgr.stop(session.session_id)


if __name__ == "__main__":
    unittest.main()
