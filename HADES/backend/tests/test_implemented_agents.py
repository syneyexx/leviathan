"""Tests for formerly planned agents that now have real runtimes + contracts."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from agent_ops import PLANNED_AGENT_IDS, is_planned_agent
from agent_runtimes import AgentRuntimeDeps, try_run_agent_step
from platform_db import PlatformDatabase
from reasoning.specialists import SPECIALISTS, get_specialist, route_specialist


IMPLEMENTED = (
    "web_scout",
    "evidence_auditor",
    "tool_orchestrator",
    "trading_specialist",
    "voice_specialist",
)


class ImplementedAgentContractTests(unittest.TestCase):
    def test_contracts_exist_and_not_planned(self) -> None:
        for agent_id in IMPLEMENTED:
            contract = get_specialist(agent_id)
            self.assertIsNotNone(contract, agent_id)
            assert contract is not None
            self.assertFalse(contract.planned_only, agent_id)
            self.assertNotIn(agent_id, PLANNED_AGENT_IDS)
            self.assertFalse(is_planned_agent(agent_id, f"{contract.name} (*)"))
            self.assertIn(agent_id, SPECIALISTS)

    def test_routing_keywords(self) -> None:
        enabled = set(SPECIALISTS.keys())
        self.assertEqual(
            route_specialist("audit provenance contradictie entity:ACME", enabled_ids=enabled),
            "evidence_auditor",
        )
        self.assertEqual(
            route_specialist("PAPER trading backtest strategie", enabled_ids=enabled),
            "trading_specialist",
        )
        self.assertEqual(
            route_specialist("maak een taak van dit transcript", enabled_ids=enabled, kind="voice"),
            "voice_specialist",
        )
        self.assertEqual(
            route_specialist("https://example.com/docs", enabled_ids=enabled),
            "web_scout",
        )


class AgentRuntimeTests(unittest.TestCase):
    def test_web_scout_respects_network_block(self) -> None:
        deps = AgentRuntimeDeps(settings={"network_policy": "block"}, web_research=MagicMock())
        result = asyncio.run(try_run_agent_step("web_scout", "https://example.com", deps=deps))
        assert result is not None
        self.assertEqual(result.mode, "blocked")
        self.assertFalse(result.ok)
        deps.web_research.ingest_url.assert_not_called()

    def test_evidence_auditor_deterministic(self) -> None:
        gen2 = MagicMock()
        gen2.find_contradictions.return_value = [
            {"a": "claim1", "b": "claim2", "relation": "contradicts"},
        ]
        knowledge = MagicMock()
        knowledge.search.return_value = {
            "matches": [{"title": "Doc", "source_id": "src_1", "content": "ACME evidence text"}]
        }
        platform_db = MagicMock()
        platform_db.search_knowledge.return_value = [
            {"title": "Doc", "source_id": "src_1", "content": "ACME evidence text"}
        ]
        deps = AgentRuntimeDeps(settings={}, gen2=gen2, knowledge=knowledge, platform_db=platform_db)
        result = asyncio.run(try_run_agent_step("evidence_auditor", "entity:ACME audit", deps=deps))
        assert result is not None
        self.assertTrue(result.ok)
        self.assertEqual(result.mode, "deterministic")
        self.assertIn("contradictions", result.output)
        self.assertIn("src_1", result.evidence_refs)

    def test_tool_orchestrator_shortlist(self) -> None:
        def shortlist(query: str, limit: int = 5) -> list[dict]:
            return [{"plugin_id": "hades.demo", "name": "echo", "status": "Ready"}]

        deps = AgentRuntimeDeps(settings={"network_policy": "block"}, shortlist_tools=shortlist)
        result = asyncio.run(try_run_agent_step("tool_orchestrator", "run multi-plugin workflow", deps=deps))
        assert result is not None
        self.assertTrue(result.ok)
        self.assertIn("eligible_tools", result.output)

    def test_trading_specialist_paper_only(self) -> None:
        paper = MagicMock()
        paper.state.return_value = {
            "settings": {"enabled": True, "kill_switch": False},
            "wallets": [{"asset": "USDT", "balance": 10000}],
            "positions": [],
            "orders": [],
        }
        deps = AgentRuntimeDeps(settings={}, paper_trading=paper)
        result = asyncio.run(try_run_agent_step("trading_specialist", "toon paper status", deps=deps))
        assert result is not None
        self.assertTrue(result.ok)
        self.assertIn("PAPER_ONLY", result.output)

    def test_voice_specialist_transcript(self) -> None:
        deps = AgentRuntimeDeps(settings={})
        result = asyncio.run(
            try_run_agent_step("voice_specialist", "Maak een onderzoek naar lokale embeddings", deps=deps)
        )
        assert result is not None
        self.assertTrue(result.ok)
        self.assertIn("task_draft", result.output)


class AgentPromotionMigrationTests(unittest.TestCase):
    def test_seed_enables_implemented_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "hades.db"
            pdb = PlatformDatabase(str(db_path))
            pdb.initialize()
            agents = {row["id"]: row for row in pdb.list_agents()}
            for agent_id in IMPLEMENTED:
                self.assertIn(agent_id, agents)
                self.assertTrue(agents[agent_id]["enabled"], agent_id)
                self.assertNotIn("(*)", agents[agent_id]["name"])


if __name__ == "__main__":
    unittest.main()
