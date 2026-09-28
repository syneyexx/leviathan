"""HTTP route tests for /api/modules lifecycle + /api/skills — no live third-party network."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.modules import build_modules_router
from Data.backend.routes.skills import build_skills_router
from Data.modules.module_manager import ModuleContext, ModuleManager
from Data.modules.module_manager.external.store import ExternalCapabilityStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "external_capabilities"
FACTORY = "Data.modules.module_manager.external.module:create_external_capability_module"


class _Obs:
    def emit(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


class ExternalModulesSkillsRouteTests(unittest.TestCase):
    def test_modules_lifecycle_and_skills_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp) / "mods" / "fake-cli"
            mods.mkdir(parents=True)
            tool = FIXTURES / "fake_cli" / "tool.py"
            manifest = {
                "module_id": "fake-cli",
                "name": "Fake CLI",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool.parent),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "command": [sys.executable, str(tool), "{query}"],
                        "operations": [
                            {"name": "search", "command": [sys.executable, str(tool), "{query}"]}
                        ],
                    },
                    "result": {"format": "json"},
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_cli.search",
                        "name": "Search",
                        "external_name": "search",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (mods / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "control.db"
            store = ExternalCapabilityStore(db)
            store.initialize()
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "fake-cli",
                ModuleContext(
                    database_path=str(db),
                    data_root=tmp,
                    metadata={"external_capability_store": store},
                ),
            )
            store.upsert_skill(
                {
                    "skill_id": "skill:demo",
                    "name": "demo-scroll",
                    "description": "cinematic scroll builder",
                    "content_hash": "abc123",
                    "source_repo": "test/fake",
                    "trigger_description": "build a cinematic site",
                    "enabled": True,
                    "catalog_only": False,
                    "module_id": "fake-cli",
                }
            )
            store.upsert_skill(
                {
                    "skill_id": "catalog:other",
                    "name": "catalog-only-skill",
                    "description": "huge catalog entry",
                    "content_hash": "def456",
                    "source_repo": "test/catalog",
                    "enabled": True,
                    "catalog_only": True,
                }
            )

            app = FastAPI()
            app.include_router(
                build_modules_router(module_manager=manager, observability=_Obs(), job_runtime=None)
            )
            app.include_router(build_skills_router(external_store=store, observability=_Obs()))
            client = TestClient(app)

            listed = client.get("/api/modules")
            self.assertEqual(listed.status_code, 200)
            body = listed.json()
            self.assertTrue(body.get("enabled"))
            ids = [m.get("manifest", {}).get("module_id") for m in body.get("modules") or []]
            self.assertIn("fake-cli", ids)

            got = client.get("/api/modules/fake-cli")
            self.assertEqual(got.status_code, 200)
            self.assertEqual(got.json()["module"]["manifest"]["module_id"], "fake-cli")

            installed = client.post("/api/modules/fake-cli/install", json={})
            self.assertEqual(installed.status_code, 200)
            self.assertIn("result", installed.json())

            ready = client.post("/api/modules/fake-cli/ensure-ready")
            self.assertEqual(ready.status_code, 200)
            self.assertTrue(ready.json().get("result", {}).get("ready") or ready.json().get("module"))

            health = client.get("/api/modules/fake-cli/health")
            self.assertEqual(health.status_code, 200)

            caps = client.get("/api/modules/fake-cli/capabilities")
            self.assertEqual(caps.status_code, 200)
            self.assertGreaterEqual(int(caps.json().get("count") or 0), 1)

            executed = client.post(
                "/api/modules/fake-cli/execute",
                json={"operation": "search", "arguments": {"query": "leviathan"}},
            )
            self.assertEqual(executed.status_code, 200)
            result = executed.json().get("result") or {}
            status = result.get("status") if isinstance(result, dict) else None
            self.assertIn(status, {"COMPLETED", "OK", "SUCCESS", None})

            versions = client.get("/api/modules/fake-cli/versions")
            self.assertEqual(versions.status_code, 200)

            started = client.post("/api/modules/fake-cli/start")
            self.assertEqual(started.status_code, 200)

            stopped = client.post("/api/modules/fake-cli/stop")
            self.assertEqual(stopped.status_code, 200)

            restarted = client.post("/api/modules/fake-cli/restart")
            self.assertEqual(restarted.status_code, 200)

            logs = client.get("/api/modules/fake-cli/logs")
            self.assertEqual(logs.status_code, 200)
            self.assertIn("lines", logs.json())

            jobs = client.get("/api/modules/fake-cli/jobs")
            self.assertEqual(jobs.status_code, 200)
            self.assertIn("jobs", jobs.json())

            check_update = client.get("/api/modules/fake-cli/check-update")
            self.assertEqual(check_update.status_code, 200)

            sweep = client.post("/api/modules/sweep-idle")
            self.assertEqual(sweep.status_code, 200)
            self.assertIn("stopped", sweep.json() or {})

            # Version APIs (sync path — no JobRuntime wired on this TestClient).
            install_ver = client.post(
                "/api/modules/fake-cli/install-version",
                json={"ref": None, "activate": True},
            )
            self.assertIn(install_ver.status_code, {200, 400, 409, 422, 424})
            activate_ver = client.post(
                "/api/modules/fake-cli/activate-version",
                json={"version_id": "missing-version"},
            )
            self.assertIn(activate_ver.status_code, {200, 400, 404, 409, 422})
            rollback_ver = client.post("/api/modules/fake-cli/rollback-version", json={})
            self.assertIn(rollback_ver.status_code, {200, 400, 404, 409, 422})

            skills = client.get("/api/skills", params={"query": "cinematic", "limit": 10})
            self.assertEqual(skills.status_code, 200)
            skill_body = skills.json()
            self.assertGreaterEqual(skill_body.get("count") or 0, 1)
            self.assertTrue(skill_body.get("truth", {}).get("catalog_not_prompt_injected"))
            names = [s.get("name") for s in skill_body.get("skills") or []]
            self.assertIn("demo-scroll", names)
            self.assertNotIn("catalog-only-skill", names)
            totals = skill_body.get("totals") or {}
            self.assertIn("installed", totals)
            self.assertIn("catalog", totals)
            self.assertIn("available", totals)
            self.assertIn("agent_skills", totals)
            self.assertIsNone(totals.get("agent_skills"))
            self.assertIsNone(totals.get("updates_available"))
            # List rows must not include instruction bodies.
            for row in skill_body.get("skills") or []:
                self.assertNotIn("instructions", row)

            catalog = client.get("/api/skills", params={"include_catalog": True, "limit": 50})
            self.assertEqual(catalog.status_code, 200)
            cat_names = [s.get("name") for s in catalog.json().get("skills") or []]
            self.assertIn("catalog-only-skill", cat_names)

            all_skills = client.get("/api/skills", params={"classification": "all", "limit": 50})
            self.assertEqual(all_skills.status_code, 200)
            all_names = [s.get("name") for s in all_skills.json().get("skills") or []]
            self.assertIn("demo-scroll", all_names)
            self.assertIn("catalog-only-skill", all_names)

            core_only = client.get("/api/skills", params={"classification": "core", "enabled_only": False})
            self.assertEqual(core_only.status_code, 200)
            core_names = [s.get("name") for s in core_only.json().get("skills") or []]
            self.assertIn("demo-scroll", core_names)
            self.assertNotIn("catalog-only-skill", core_names)

            one = client.get("/api/skills/skill:demo")
            self.assertEqual(one.status_code, 200)
            self.assertEqual(one.json()["skill"]["skill_id"], "skill:demo")
            self.assertIn("compatibility", one.json()["skill"])
            self.assertIn("declarations", one.json()["skill"])
            self.assertNotIn("instructions", one.json()["skill"])

            tested = client.post("/api/skills/skill:demo/test")
            self.assertEqual(tested.status_code, 200)
            test_body = tested.json()
            self.assertIn("result", test_body)
            self.assertIn("checks", test_body["result"])
            self.assertTrue(test_body["result"].get("truth", {}).get("not_mocked_pass"))

            # Instruction-only execute must fail truthfully (no required caps).
            executed_skill = client.post("/api/skills/skill:demo/execute", json={})
            self.assertEqual(executed_skill.status_code, 422)
            detail = (executed_skill.json() or {}).get("detail") or ""
            self.assertIn("executable capability", str(detail).lower())

            disabled = client.post("/api/skills/skill:demo/enable", json={"enabled": False})
            self.assertEqual(disabled.status_code, 200)
            self.assertFalse(bool(disabled.json()["skill"].get("enabled")))

            enabled_only = client.get("/api/skills", params={"enabled_only": True})
            self.assertEqual(enabled_only.status_code, 200)
            enabled_names = [s.get("name") for s in enabled_only.json().get("skills") or []]
            self.assertNotIn("demo-scroll", enabled_names)

            reenabled = client.post("/api/skills/skill:demo/enable", json={"enabled": True})
            self.assertEqual(reenabled.status_code, 200)
            self.assertTrue(bool(reenabled.json()["skill"].get("enabled")))

            missing = client.get("/api/modules/does-not-exist")
            self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
