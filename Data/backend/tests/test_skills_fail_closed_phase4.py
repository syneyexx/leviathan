"""Phase 4 — skills fail-closed test + execute gateway status mapping."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.skills import build_skills_router
from Data.modules.cognition.skills import SkillLibrary, stable_skill_id
from Data.modules.execution import CapabilityStatus
from Data.modules.module_manager.external.skills import SkillImporter, _split_frontmatter


class _FakeStore:
    def __init__(self, skills: dict[str, dict[str, Any]]) -> None:
        self._skills = skills

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        return self._skills.get(skill_id)

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> dict[str, Any] | None:
        skill = self._skills.get(skill_id)
        if skill is None:
            return None
        skill = dict(skill)
        skill["enabled"] = enabled
        self._skills[skill_id] = skill
        return skill

    def count_skills(self, catalog_only: bool = False) -> int:
        return sum(1 for s in self._skills.values() if bool(s.get("catalog_only")) is catalog_only)

    def search_skills(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self._skills.values())

    def skill_totals_projection(self) -> dict[str, Any]:
        return {"installed": 1, "catalog": 0, "total": 1, "available": 1}


class _FakeCatalog:
    def __init__(self, items: dict[str, Any]) -> None:
        self._items = items

    def __contains__(self, capability_id: str) -> bool:
        return capability_id in self._items

    def get(self, capability_id: str) -> Any:
        return self._items.get(capability_id)

    def search(self, query: str, limit: int = 500) -> list[Any]:
        return list(self._items.values())[:limit]


class _Cap:
    def __init__(self, id: str, *, available: bool = True, enabled: bool = True) -> None:
        self.id = id
        self.available = available
        self.enabled = enabled


class _FakeResult:
    def __init__(self, status: CapabilityStatus, telemetry: dict[str, Any] | None = None) -> None:
        self.status = status
        self.telemetry = telemetry or {}
        self.request_id = "req-1"

    def public_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "request_id": self.request_id, "telemetry": self.telemetry}


class _FakeGateway:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.last_request = None

    def execute(self, request: Any) -> _FakeResult:
        self.last_request = request
        return self._result

    def list_capabilities(self) -> list[Any]:
        return []


class SkillsFailClosedTests(unittest.TestCase):
    def _client(
        self,
        *,
        skill: dict[str, Any],
        catalog: _FakeCatalog | None = None,
        gateway: _FakeGateway | None = None,
        module_manager: Any = None,
    ) -> TestClient:
        app = FastAPI()
        app.include_router(
            build_skills_router(
                external_store=_FakeStore({skill["skill_id"]: skill}),
                capability_catalog=catalog,
                execution_gateway=gateway,
                module_manager=module_manager,
            )
        )
        return TestClient(app)

    def test_unmeasured_compatibility_is_not_pass(self) -> None:
        skill = {
            "skill_id": "skill:demo",
            "name": "demo",
            "content_hash": "abc",
            "enabled": True,
            "catalog_only": False,
            "source_path": "",
            "required_capabilities": [],
        }
        client = self._client(skill=skill)
        resp = client.post("/api/skills/skill:demo/test")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["result"]
        self.assertFalse(body["ok"])
        self.assertTrue(body["truth"]["fail_closed"])

    def test_partial_compatibility_is_not_pass(self) -> None:
        skill = {
            "skill_id": "skill:partial",
            "name": "partial",
            "content_hash": "abc",
            "enabled": True,
            "required_capabilities": ["cap.a", "cap.b"],
            "source_path": "",
        }
        catalog = _FakeCatalog({"cap.a": _Cap("cap.a")})
        client = self._client(skill=skill, catalog=catalog)
        resp = client.post("/api/skills/skill:partial/test")
        self.assertFalse(resp.json()["result"]["ok"])

    def test_module_manager_unavailable_not_pass(self) -> None:
        skill = {
            "skill_id": "skill:mod",
            "name": "mod",
            "content_hash": "abc",
            "enabled": True,
            "required_capabilities": ["cap.a"],
            "module_id": "ext.mod",
            "source_path": "",
        }
        catalog = _FakeCatalog({"cap.a": _Cap("cap.a")})
        client = self._client(skill=skill, catalog=catalog, module_manager=None)
        resp = client.post("/api/skills/skill:mod/test")
        self.assertFalse(resp.json()["result"]["ok"])
        names = [c["name"] for c in resp.json()["result"]["checks"]]
        self.assertIn("owning_module_available", names)

    def test_disabled_skill_execute_forbidden(self) -> None:
        skill = {
            "skill_id": "skill:off",
            "name": "off",
            "content_hash": "abc",
            "enabled": False,
            "required_capabilities": ["cap.a"],
        }
        catalog = _FakeCatalog({"cap.a": _Cap("cap.a")})
        gateway = _FakeGateway(_FakeResult(CapabilityStatus.COMPLETED))
        client = self._client(skill=skill, catalog=catalog, gateway=gateway)
        resp = client.post("/api/skills/skill:off/execute", json={"capability_id": "cap.a"})
        self.assertEqual(resp.status_code, 403)

    def test_rejected_execute_is_not_http_200(self) -> None:
        skill = {
            "skill_id": "skill:rej",
            "name": "rej",
            "content_hash": "abc",
            "enabled": True,
            "required_capabilities": ["cap.a"],
        }
        catalog = _FakeCatalog({"cap.a": _Cap("cap.a")})
        gateway = _FakeGateway(
            _FakeResult(CapabilityStatus.REJECTED, telemetry={"reason": "policy"})
        )
        client = self._client(skill=skill, catalog=catalog, gateway=gateway)
        resp = client.post(
            "/api/skills/skill:rej/execute",
            json={
                "capability_id": "cap.a",
                "approval_id": "a1",
                "idempotency_key": "idem-1",
                "requested_by": "skills_page",
            },
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(gateway.last_request.idempotency_key, "idem-1")
        self.assertEqual(gateway.last_request.approval_id, "a1")

    def test_approval_required_execute_is_http_403(self) -> None:
        skill = {
            "skill_id": "skill:apr",
            "name": "apr",
            "content_hash": "abc",
            "enabled": True,
            "required_capabilities": ["cap.a"],
        }
        catalog = _FakeCatalog({"cap.a": _Cap("cap.a")})
        gateway = _FakeGateway(
            _FakeResult(
                CapabilityStatus.APPROVAL_REQUIRED,
                telemetry={"reason": "approval_required"},
            )
        )
        client = self._client(skill=skill, catalog=catalog, gateway=gateway)
        resp = client.post(
            "/api/skills/skill:apr/execute",
            json={"capability_id": "cap.a", "requested_by": "skills_page"},
        )
        self.assertEqual(resp.status_code, 403)
        detail = resp.json()["detail"]
        self.assertEqual(detail["result"]["status"], CapabilityStatus.APPROVAL_REQUIRED.value)

    def test_timeout_maps_504(self) -> None:
        skill = {
            "skill_id": "skill:to",
            "name": "to",
            "content_hash": "abc",
            "enabled": True,
            "required_capabilities": ["cap.a"],
        }
        catalog = _FakeCatalog({"cap.a": _Cap("cap.a")})
        gateway = _FakeGateway(_FakeResult(CapabilityStatus.TIMEOUT))
        client = self._client(skill=skill, catalog=catalog, gateway=gateway)
        resp = client.post("/api/skills/skill:to/execute", json={"capability_id": "cap.a"})
        self.assertEqual(resp.status_code, 504)


class SkillLibraryIdStabilityTests(unittest.TestCase):
    def test_stable_skill_id_not_builtin_hash(self) -> None:
        a = stable_skill_id("coding::add unit test")
        b = stable_skill_id("coding::add unit test")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("skill:"))
        lib = SkillLibrary()
        derived = lib.derive_from_verified_runs(
            [
                {
                    "run_id": "r1",
                    "verification_status": "VERIFIED",
                    "domain": "coding",
                    "goal": "add unit test",
                    "success": True,
                    "steps": ["a"],
                },
                {
                    "run_id": "r2",
                    "verification_status": "VERIFIED",
                    "domain": "coding",
                    "goal": "add unit test",
                    "success": True,
                    "steps": ["a"],
                },
            ],
            min_repeats=2,
        )
        self.assertEqual(len(derived), 1)
        self.assertEqual(derived[0].skill_id, stable_skill_id("coding::add unit test"))


class SkillFrontmatterParserTests(unittest.TestCase):
    def test_safe_yaml_frontmatter(self) -> None:
        text = "---\nname: demo\nrequired_capabilities:\n  - cap.a\n  - cap.b\n---\n# Body\n"
        fm, body = _split_frontmatter(text)
        self.assertEqual(fm.get("name"), "demo")
        self.assertEqual(fm.get("required_capabilities"), ["cap.a", "cap.b"])
        self.assertIn("Body", body)

    def test_malformed_yaml_yields_diagnostic(self) -> None:
        text = "---\nname: [unclosed\n---\nbody\n"
        fm, body = _split_frontmatter(text)
        self.assertIn(fm.get("_import_diagnostic"), {"frontmatter_yaml_error", "frontmatter_not_mapping"})
        self.assertIn("body", body)

    def test_importer_records_diagnostic_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text("---\nname: [bad\n---\n# Skill\n", encoding="utf-8")
            record = SkillImporter().parse_skill_file(path)
            self.assertIn("import_diagnostic", record.metadata)


if __name__ == "__main__":
    unittest.main()
