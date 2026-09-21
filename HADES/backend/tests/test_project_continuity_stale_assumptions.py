from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import Database
from project_continuity import ProjectContinuityService


class ProjectContinuityStaleAssumptionTests(unittest.TestCase):
    def test_stale_assumptions_are_reported_without_reentering_active_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(str(Path(temp_dir) / "hades.db"))
            db.initialize()
            service = ProjectContinuityService(db)
            project = service.create_project("Continuity truth")

            falsified = service.add_item(
                project["id"],
                kind="assumption",
                title="Provider is available",
                body="Temporary working assumption",
                provenance="inferred",
                status="unverified",
            )
            superseded = service.add_item(
                project["id"],
                kind="assumption",
                title="Old workspace layout",
                body="Historical working assumption",
                provenance="inferred",
                status="unverified",
            )
            excluded = service.add_item(
                project["id"],
                kind="assumption",
                title="User-excluded guess",
                body="Must stay outside active and stale context",
                provenance="inferred",
                status="unverified",
            )

            service.set_assumption_status(falsified["id"], "falsified")
            service.set_assumption_status(superseded["id"], "superseded")
            service.exclude_item(excluded["id"])

            package = service.context_package(project["id"])
            active_ids = {item["id"] for item in package["assumptions"]}
            stale_ids = {item["id"] for item in package["stale_assumptions"]}

            self.assertNotIn(falsified["id"], active_ids)
            self.assertNotIn(superseded["id"], active_ids)
            self.assertNotIn(excluded["id"], active_ids)
            self.assertIn(falsified["id"], stale_ids)
            self.assertIn(superseded["id"], stale_ids)
            self.assertNotIn(excluded["id"], stale_ids)


if __name__ == "__main__":
    unittest.main()
