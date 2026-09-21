"""Restore/compare/audit/fuse/pack/ping empty-success honesty."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]


class RestoreCompareFuseToastHonestyTests(unittest.TestCase):
    def test_restore_backup_empty_is_noop(self) -> None:
        from build_agent import BuildAgentService

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            source.mkdir()
            agent = BuildAgentService(root)
            run_id = "run_empty_restore"
            work = agent.runs_root / run_id / "work"
            work.mkdir(parents=True)
            backup = agent.runs_root / run_id / "pre_apply_backup"
            backup.mkdir(parents=True)
            # Empty backup tree → no files restored.
            (agent.runs_root / run_id / "meta.json").write_text(
                json.dumps({"source": str(source), "work_root": str(work)}),
                encoding="utf-8",
            )
            outcome = agent.restore_backup(run_id)
            self.assertFalse(outcome.get("restored"))
            self.assertEqual(outcome.get("status"), "noop")
            self.assertEqual(outcome.get("error"), "no_files_restored")

    def test_coding_restore_toast_gates_files(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "coding-agent-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('result.status === "restored" && restoredCount > 0', page)
        self.assertIn("Backup herstel leverde geen bestanden op.", page)

    def test_compare_runs_empty_fail_closed(self) -> None:
        from gen2.flight_recorder import compare_runs, export_audit_bundle
        from gen2.store import Gen2Store

        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(Path(tmp) / "gen2.db")
            empty = compare_runs(store, "missing_a", "missing_b")
            self.assertFalse(empty.get("ok"))
            self.assertEqual(empty.get("error"), "no_events")
            one_sided = compare_runs(store, "missing_a", "missing_b")
            # both missing → no_events
            self.assertIn(one_sided.get("error"), {"no_events", "empty_run"})
            bundle = export_audit_bundle(store, "missing_run")
            self.assertFalse(bundle.get("ok"))
            self.assertEqual(bundle.get("error"), "no_events")

    def test_mission_control_flight_toast_gates(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "mission-control-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('toast.message("0 events — run onbekend of leeg")', page)
        self.assertIn('toast.error(String((bundle as { error?: string }).error || "Audit bundle leeg"))', page)
        self.assertIn(
            'toast.error(String((result as { error?: string }).error || "Compare mislukt (lege run)"))',
            page,
        )
        self.assertIn('st === "failed" || st === "blocked" || !st', page)
        self.assertNotIn('toast.success(`Ping job ${String(job.id || "")}: ${st || "ok"}`)', page)
        self.assertIn("fuseCount <= 0", page)

    def test_memory_pack_empty_rejected(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "memory-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("Knowledge pack is leeg (geen memories, bronnen of agents).", page)
        self.assertIn("importedTotal <= 0", page)

    def test_agents_cancel_noop_is_message(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "agents-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('toast.message("Geen actieve run om te annuleren.")', page)
        self.assertNotIn(
            'toast.success(result.cancelled_task_ids.length ? `${result.cancelled_task_ids.length} taak(en) geannuleerd.` : "Geen actieve run om te annuleren.")',
            page,
        )


if __name__ == "__main__":
    unittest.main()
