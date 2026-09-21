"""Workspace backup, sandbox apply, catalog, resume, reindex, skill-bridge honesty."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]


class BackupSandboxCatalogHonestyTests(unittest.TestCase):
    def test_settings_workspace_backup_gates_phase_and_path(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "settings-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('phase === "completed" || phase === "completed_with_warnings"', page)
        self.assertIn("path.trim().length > 0", page)
        self.assertNotIn(
            'toast.success(path ? `Volledige workspace-archive gemaakt: ${path}` : "Volledige workspace-archive gemaakt")',
            page,
        )

    def test_workspace_backup_api_rejects_cancelled(self) -> None:
        src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        self.assertIn('result.get("phase") == "cancelled"', src)
        self.assertIn("workspace backup missing archive_path", src)
        self.assertIn('result.get("phase") not in {"completed", "completed_with_warnings"}', src)

    def test_sandbox_apply_requires_known_plugin(self) -> None:
        from gen2.services import Gen2Services
        from gen2.store import Gen2Store

        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(str(Path(tmp) / "g.db"))
            svc = Gen2Services(store, data_root=Path(tmp))
            db = MagicMock()
            db.list_plugins.return_value = [{"id": "known-plugin"}]
            svc.platform_db = db
            with self.assertRaises(ValueError) as ctx:
                svc.envelope_for_policy_profile("missing-plugin", "strict")
            self.assertIn("unknown_plugin", str(ctx.exception))

    def test_mission_control_catalog_sandbox_gates(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "mission-control-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("Catalog leeg of geen beschikbare suites", page)
        self.assertIn("Sandbox profile apply leverde geen geldige envelope op.", page)
        self.assertNotIn('toast.success("Catalog geladen")', page)

    def test_coding_resume_and_files_reindex_gates(self) -> None:
        coding = (ROOT / "components" / "hades" / "pages" / "coding-agent-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('["queued", "running", "paused", "interrupted"].includes(st)', coding)
        self.assertIn("Hervatten eindigde in status:", coding)
        files = (ROOT / "components" / "hades" / "pages" / "files-page.tsx").read_text(encoding="utf-8")
        self.assertIn("Opnieuw indexeren leverde 0 chunks op.", files)
        self.assertNotIn(
            "toast.success(result.unchanged ? \"Bestand was al up-to-date.\" : `Opnieuw geïndexeerd (${result.chunks} chunks).`)",
            files,
        )

    def test_workflow_skill_bridge_requires_id(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "workflows-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("Workflow→skill bridge leverde geen skill id op.", page)
        self.assertNotIn(
            'toast.success(skillId ? `Skill candidate: ${skillId}` : "Workflow→skill bridge uitgevoerd")',
            page,
        )


if __name__ == "__main__":
    unittest.main()
