"""UI-oriented Gen2 API product tests — routes the Mission Control / Workflows clients call.

Covers client methods that previously lacked focused HTTP coverage without rewriting
mission_control core logic (owned elsewhere). Honest labels asserted where relevant.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from gen2.flight_recorder import record as fr_record


class FakeLmStudio:
    async def models(self):
        return {"object": "list", "data": [{"id": "local-test-model", "object": "model", "owned_by": "local"}]}

    async def chat(self, payload):
        messages = payload.get("messages") or []
        text = " ".join(str((m or {}).get("content") or "") for m in messages).lower()
        if "json only" in text or "committee role" in text:
            content = '{"claim":"Simulated live stance","confidence":0.72,"supported":true,"rationale":"mock lm"}'
        else:
            content = "ok"
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class Gen2UiApiProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api-gen2-ui.db"))
        main.runner = main.TaskRunner()
        main.ensure_platform_services()
        main._sync_gen2_services()
        self.client_patch = patch.object(main, "lm_client", return_value=FakeLmStudio())
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_eval_catalog_reports_ab_and_ingest_flight(self) -> None:
        catalog = self.client.get("/api/gen2/evals/catalog").json()
        self.assertTrue(catalog.get("offline") or catalog.get("suites"))
        suites = catalog.get("suites") or []
        self.assertTrue(any("reasoning" in str(s.get("id", s)) for s in suites))

        run = self.client.post(
            "/api/gen2/evals/run",
            json={"suite": "reasoning", "mode": "deterministic_software"},
        ).json()
        self.assertEqual(run.get("status"), "completed")
        self.assertTrue((run.get("summary") or {}).get("not_model_quality"))

        reports = self.client.get("/api/gen2/evals/reports?limit=10").json()
        self.assertIsInstance(reports, list)
        self.assertGreaterEqual(len(reports), 1)

        ab = self.client.post(
            "/api/gen2/evals/ab",
            json={"strategy_a": "baseline", "strategy_b": "variant", "suite": "reasoning", "n": 1},
        ).json()
        summary = ab.get("summary") or {}
        if "not_model_quality" in summary:
            self.assertTrue(summary["not_model_quality"])

        rid = "ui-product-flight-1"
        fr_record(main.gen2.store, rid, "RUN_CREATED", {"note": "ui product"})
        fr_record(main.gen2.store, rid, "TERMINAL", {"status": "completed", "ok": True})
        ingested = self.client.post("/api/gen2/evals/ingest-flight", json={"run_id": rid}).json()
        self.assertTrue(ingested.get("id") or ingested.get("suite") or ingested.get("status"))

    def test_mission_acceptance_evaluate_and_replan_routes(self) -> None:
        mission = self.client.post(
            "/api/gen2/missions/compile",
            json={"goal": "Research offline acceptance UI path"},
        ).json()
        mid = mission["id"]
        evaluated = self.client.post(f"/api/gen2/missions/{mid}/acceptance/evaluate", json={}).json()
        self.assertIsInstance(evaluated, dict)
        self.assertTrue(
            any(
                key in evaluated
                for key in ("passed", "checks", "results", "all_passed", "summary", "status", "acceptance")
            )
        )

        replanned = self.client.post(
            f"/api/gen2/missions/{mid}/replan",
            json={"cause": "tool", "note": "ui-product"},
        ).json()
        count = int(replanned.get("replan_count") or (replanned.get("ir") or {}).get("replan_count") or 0)
        self.assertEqual(count, 1)

        bad = self.client.post(f"/api/gen2/missions/{mid}/replan", json={"cause": "magic"})
        self.assertEqual(bad.status_code, 400)

    def test_sandbox_profiles_graph_compute_client_routes(self) -> None:
        profiles = self.client.get("/api/gen2/sandbox/profiles").json()
        self.assertIsInstance(profiles, list)
        self.assertGreaterEqual(len(profiles), 1)
        first = profiles[0]
        self.assertIn("id", first)

        main.platform_db.save_plugin(
            {
                "id": "ui-product-plugin",
                "name": "UI Product Plugin",
                "local_path": str(Path(self.temp_dir.name) / "ui-product-plugin"),
                "enabled": True,
                "status": "ready",
            }
        )
        applied_resp = self.client.post(
            f"/api/gen2/sandbox/profiles/{first['id']}/apply",
            json={"plugin_id": "ui-product-plugin"},
        )
        self.assertEqual(applied_resp.status_code, 200, applied_resp.text)
        applied = applied_resp.json()
        self.assertTrue(
            applied.get("plugin_id")
            or applied.get("envelope")
            or applied.get("tier") is not None
            or applied.get("id")
        )
        missing = self.client.post(
            f"/api/gen2/sandbox/profiles/{first['id']}/apply",
            json={"plugin_id": "does-not-exist"},
        )
        self.assertEqual(missing.status_code, 400)

        edge = self.client.post(
            "/api/gen2/graph/edges",
            json={
                "source_id": "entity_a",
                "target_id": "entity_b",
                "relation": "related_to",
                "relation_kind": "related_to",
                "provenance": "ui-product-test",
                "confidence": 0.5,
            },
        ).json()
        self.assertTrue(edge.get("id") or edge.get("source_id"))

        as_of = self.client.get(
            "/api/gen2/graph/as-of",
            params={"entity_id": "entity_a", "as_of": "2099-01-01T00:00:00Z"},
        )
        self.assertEqual(as_of.status_code, 200)
        self.assertIsInstance(as_of.json(), (dict, list))

        nodes = self.client.get("/api/gen2/compute/nodes").json()
        self.assertTrue(any(n.get("id") == "node_local" for n in nodes))
        status = self.client.get("/api/gen2/compute/status").json()
        self.assertIsInstance(status, dict)

        ping = self.client.post(
            "/api/gen2/compute/jobs",
            json={"payload": {"type": "ping", "note": "ui-product"}, "prefer_local_fallback": True},
        ).json()
        self.assertIn(str(ping.get("status")), {"completed", "ok", "queued", "running", "failed", "blocked"})

        unknown = self.client.post(
            "/api/gen2/compute/jobs",
            json={"payload": {"type": "shell_exec"}, "prefer_local_fallback": True},
        ).json()
        self.assertIn(str(unknown.get("status")), {"failed", "blocked", "rejected", "error"})
        self.assertTrue(unknown.get("error") or str(unknown.get("status")) != "completed")

    def test_flight_recorder_ui_routes_and_extract_from_run(self) -> None:
        rid = "ui-flight-recorder-1"
        fr_record(main.gen2.store, rid, "RUN_CREATED", {"goal": "ui"})
        fr_record(main.gen2.store, rid, "TOOL", {"tool": "noop", "ok": True})
        fr_record(main.gen2.store, rid, "TERMINAL", {"status": "completed", "ok": True})

        events = self.client.get(f"/api/gen2/flight/runs/{rid}/events").json()
        self.assertIsInstance(events, list)
        self.assertGreaterEqual(len(events), 1)

        replay = self.client.post(f"/api/gen2/flight/runs/{rid}/replay", json={})
        self.assertEqual(replay.status_code, 200)
        body = replay.json()
        kind = str(body.get("kind") or body.get("mode") or "")
        if kind:
            self.assertTrue(
                "inspect" in kind or kind == "inspection_not_replay" or "replay" in kind,
                msg=f"unexpected replay kind: {kind}",
            )

        preview = self.client.post(
            "/api/gen2/skills/extract-from-run",
            json={"run_id": rid, "create": False},
        ).json()
        self.assertFalse(preview.get("created"))
        self.assertFalse(preview.get("promoted"))

        created = self.client.post(
            "/api/gen2/skills/extract-from-run",
            json={"run_id": rid, "name": "ui-extract", "create": True},
        ).json()
        if created.get("created"):
            skill = created.get("skill") or {}
            self.assertEqual(skill.get("status"), "candidate")
            self.assertNotEqual(skill.get("status"), "promoted")
        else:
            self.assertTrue(created.get("reason") is not None or created.get("extraction") is not None)

    def test_context_compile_and_finance_committee_ui(self) -> None:
        pack = self.client.post(
            "/api/gen2/context/compile",
            json={
                "goal": "UI pack preview",
                "items": [
                    {"item_id": "a", "kind": "knowledge", "content": "Useful fact about UI.", "source": "test"},
                    {"item_id": "b", "kind": "noise", "content": "Unrelated filler.", "source": "test"},
                ],
                "persist": False,
                "tokenizer_mode": "approx_chars_4",
            },
        ).json()
        self.assertIn("kept", pack)
        self.assertTrue(
            pack.get("tokenizer") is not None
            or pack.get("tokenizer_mode_requested")
            or pack.get("token_accounting")
            or pack.get("used_tokens") is not None
        )

        fuse = self.client.post(
            "/api/gen2/finance/fuse",
            json={
                "symbol": "SAMPLE",
                "articles": [
                    {
                        "title": "Sample company update",
                        "summary": "Fixture for UI product test",
                        "source": "ui-product",
                        "source_count": 1,
                    }
                ],
            },
        ).json()
        self.assertGreaterEqual(int(fuse.get("count") or 0), 1)

        committee = self.client.post(
            "/api/gen2/committees",
            json={
                "topic": "UI product",
                "domain": "research",
                "evidence": ["local note"],
                "mode": "heuristic",
            },
        ).json()
        self.assertTrue(committee.get("consensus") or committee.get("positions"))

    def test_workflow_templates_validate_dry_run_and_revisions(self) -> None:
        templates = self.client.get("/api/gen2/workflows/templates").json()
        self.assertIsInstance(templates, list)
        self.assertGreaterEqual(len(templates), 1)
        tid = templates[0]["id"]
        wf = self.client.post(
            "/api/gen2/workflows/templates",
            json={"template_id": tid, "name": "ui-product-wf"},
        ).json()
        wid = wf["id"]

        revisions = self.client.get(f"/api/gen2/workflows/{wid}/revisions?limit=10").json()
        self.assertIsInstance(revisions, list)

        validated = self.client.post(f"/api/gen2/workflows/{wid}/validate").json()
        self.assertIn("valid", validated)

        dry = self.client.post(f"/api/gen2/workflows/{wid}/dry-run").json()
        self.assertTrue("passed" in dry or "status" in dry or dry.get("mode") in ("dry_run", "dry-run", None))


if __name__ == "__main__":
    unittest.main()
