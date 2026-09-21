"""Regressions for research rounds/agents controls and expert coverage."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from platform_db import PlatformDatabase
from platform_services_core import ResearchRunner


class ResearchConfigResolveTests(unittest.TestCase):
    def test_expert_cycles_map_to_rounds_not_times_three(self) -> None:
        runner = ResearchRunner(
            db=None,  # type: ignore[arg-type]
            knowledge=None,  # type: ignore[arg-type]
            web=None,  # type: ignore[arg-type]
            lm_resolver=None,
            lm_client_factory=None,
            payload_builder=None,
            network_policy=lambda: "block",
            runtime_settings=lambda: {"expert_max_cycles": 6, "expert_sources_per_cycle": 30},
        )
        config = runner._resolve_run_config({"depth": "expert", "max_rounds": None, "agent_count": None}, runner.runtime_settings())
        self.assertEqual(config["rounds"], 6)
        self.assertEqual(config["agents"], 3)
        self.assertGreaterEqual(config["max_sources"], 180)

    def test_project_overrides_rounds_and_agents(self) -> None:
        runner = ResearchRunner(
            db=None,  # type: ignore[arg-type]
            knowledge=None,  # type: ignore[arg-type]
            web=None,  # type: ignore[arg-type]
            lm_resolver=None,
            lm_client_factory=None,
            payload_builder=None,
            network_policy=lambda: "allow",
            runtime_settings=lambda: {"expert_max_cycles": 6},
        )
        config = runner._resolve_run_config(
            {"depth": "expert", "max_rounds": 12, "agent_count": 5},
            runner.runtime_settings(),
        )
        self.assertEqual(config["rounds"], 12)
        self.assertEqual(config["agents"], 5)

    def test_local_diversity_can_reach_expert_threshold(self) -> None:
        evidence = [
            {"uri": f"/data/docs/topic-{index}.txt", "source_type": "document"}
            for index in range(24)
        ]
        diversity, domains, local_count = ResearchRunner._coverage_diversity(evidence)
        self.assertEqual(domains, 0)
        self.assertEqual(local_count, 24)
        source_score = 100
        coverage = round(source_score * 0.65 + diversity * 0.35)
        self.assertGreaterEqual(coverage, 90)


class ResearchProjectPersistenceTests(unittest.TestCase):
    def test_create_persists_rounds_and_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = PlatformDatabase(str(Path(tmp) / "platform.db"))
            db.initialize()
            project = db.create_research_project(
                "Diep onderzoek",
                "Kernfusie",
                "expert",
                False,
                [],
                False,
                max_rounds=9,
                agent_count=4,
            )
            self.assertEqual(project["max_rounds"], 9)
            self.assertEqual(project["agent_count"], 4)
            reloaded = db.get_research_project(project["id"])
            assert reloaded is not None
            self.assertEqual(reloaded["max_rounds"], 9)
            self.assertEqual(reloaded["agent_count"], 4)

    def test_create_api_accepts_rounds_and_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main.database = Database(str(root / "core.db"))
            main.database.initialize()
            main.platform_db = PlatformDatabase(str(root / "platform.db"))
            main.ensure_platform_services()
            main.platform_db.initialize()
            main.research_runner = None
            with TestClient(main.app) as client:
                response = client.post(
                    "/api/research",
                    json={
                        "topic": "Expert control test",
                        "depth": "expert",
                        "allow_web": False,
                        "sources": [],
                        "auto_start": False,
                        "approved_network": False,
                        "approved_file_read": True,
                        "authorized_downloads": False,
                        "max_rounds": 8,
                        "agent_count": 3,
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)
                body = response.json()
                self.assertEqual(body["depth"], "expert")
                self.assertEqual(body["max_rounds"], 8)
                self.assertEqual(body["agent_count"], 3)


class ExpertLocalCompletionTests(unittest.TestCase):
    def test_expert_local_run_can_complete_with_enough_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDatabase(str(root / "platform.db"))
            db.initialize()
            from platform_services_core import KnowledgeService, WebResearchService

            knowledge = KnowledgeService(db, root)
            docs = []
            for index in range(24):
                path = root / f"evidence-{index}.txt"
                path.write_text(
                    f"Expert evidence over quantum optics en fotonica nummer {index}. "
                    f"Belangrijke claims over interferometrie en bronnenverzameling.\n" * 20,
                    encoding="utf-8",
                )
                docs.append(str(path))

            async def _resolver(_model):
                return "local-test", {"temperature": 0.2, "max_tokens": 800}

            class _Client:
                async def chat(self, payload):
                    content = payload["messages"][0]["content"]
                    if "zoekqueries" in content.lower() or "zoekqueries" in content or "invalshoeken" in content.lower():
                        return {
                            "choices": [
                                {
                                    "message": {
                                        "content": "\n".join(
                                            [
                                                "quantum optics interferometry",
                                                "photonics primary sources",
                                                "quantum optics critique",
                                            ]
                                        )
                                    }
                                }
                            ]
                        }
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": "Brongebonden rapport.\n\nKennishiaten\n- geen\n\nVolgende onderzoeksvragen\n- geen"
                                }
                            }
                        ]
                    }

            runner = ResearchRunner(
                db,
                knowledge,
                WebResearchService(knowledge),
                _resolver,
                lambda: _Client(),
                lambda model_id, profile, messages: {"model": model_id, "messages": messages, **profile},
                lambda: "block",
                lambda: {"expert_mastery_target": 90, "expert_max_cycles": 2},
            )
            project = db.create_research_project(
                "Expert local",
                "quantum optics",
                "expert",
                False,
                docs,
                False,
                max_rounds=2,
                agent_count=2,
            )
            asyncio.run(runner._run(project["id"]))
            finished = db.get_research_project(project["id"])
            assert finished is not None
            metrics = finished.get("metrics") or {}
            self.assertEqual(finished["status"], "completed", finished)
            self.assertGreaterEqual(int(metrics.get("coverage_score") or 0), 90)
            self.assertEqual(int(metrics.get("configured_rounds") or 0), 2)
            self.assertEqual(int(metrics.get("agent_count") or 0), 2)
            self.assertGreaterEqual(int(metrics.get("research_rounds") or 0), 1)


if __name__ == "__main__":
    unittest.main()
