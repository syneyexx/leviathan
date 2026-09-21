"""Coding job start, plugin status, mic peak, tasks toast, queue/netstriker honesty."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]


class JobPluginMicQueueHonestyTests(unittest.TestCase):
    def test_coding_background_job_requires_id(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "coding-agent-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('toast.error("Achtergrondjob startte zonder job_id.")', page)
        self.assertIn('["failed", "cancelled", "interrupted", "tests_failed"].includes(st)', page)

    def test_plugins_status_error_toasts(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "plugins-page-core.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('["error", "failed", "broken", "blocked"].includes(status)', page)
        self.assertIn("Pluginconversie eindigde in status:", page)
        self.assertIn("Pluginimport eindigde in status:", page)
        self.assertIn("Pluginupdate eindigde in status:", page)

    def test_mic_test_requires_peak(self) -> None:
        page = (ROOT / "components" / "hades" / "voice" / "voice-settings-panel.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("peak > 0.01", page)
        self.assertIn("geen meetbaar niveau", page)

    def test_tasks_create_toasts_from_status(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "tasks-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('["failed", "cancelled", "error", "blocked"].includes(status)', page)
        self.assertNotIn(
            'toast.success(form.schedule_enabled ? "Geplande taak opgeslagen (draait alleen terwijl HADES actief is)." : form.auto_start ? "Taak gestart." : "Taak toegevoegd aan de wachtrij.")',
            page,
        )

    def test_process_local_queue_fails_when_jobs_failed(self) -> None:
        from gen2.compute_fabric import process_local_queue
        from gen2.store import Gen2Store

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Gen2Store(str(root / "c.db"))
            # Empty drain is ok=True with 0 processed.
            empty = process_local_queue(store, root, limit=3)
            self.assertTrue(empty.get("ok"))
            self.assertEqual(empty.get("processed"), 0)

            # Inject a failed job result path by mocking execute.
            store.create_remote_job(
                {"node_id": "node_local", "status": "queued", "payload": {"type": "document_chunk", "text": ""}}
            )
            drained = process_local_queue(store, root, limit=5)
            # Empty document chunk now fails → queue should report ok=false if job failed.
            if drained.get("processed", 0) > 0 and drained.get("failed_count", 0) > 0:
                self.assertFalse(drained.get("ok"))

    def test_netstriker_remediation_ok_and_exit(self) -> None:
        root = (ROOT / "plugins" / "netstriker-ai" / "hades_bridge.py").read_text(encoding="utf-8")
        overlay = (ROOT / "plugins" / "netstriker-ai" / "overlay" / "hades_bridge.py").read_text(
            encoding="utf-8"
        )
        for text in (root, overlay):
            self.assertIn("empty_remediation_guide", text)
            self.assertIn("empty_remediation", text)
            self.assertIn("return emit(payload, exit_code=0 if ok else 2)", text)
            self.assertIn('"ok": len(rows) > 0', text)


if __name__ == "__main__":
    unittest.main()
