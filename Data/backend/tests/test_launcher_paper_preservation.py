"""Launcher start must not regress PR #189 paper / A4 architecture.

These tests prove the launcher/bootstrap output-pipeline fix stays independent
of MarketSim ownership: MARKET domain v2 + market_paper_deployments survive
startup/restart, Worker Fabric can still service market_sim jobs, the host does
not create PaperDeployments, and live money remains BLOCKED.
"""

from __future__ import annotations

import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path

from Data.backend.db_upgrade import (
    DOMAIN_MIGRATIONS,
    CutoverPhase,
    domain_schema_version,
    upgrade_all_databases,
)
from Data.backend.table_ownership import ownership_for
from Data.modules.common.database_domains import DatabaseDomain, DatabasePaths
from Data.modules.market_sim.capabilities import build_mode_capability_matrix
from Data.modules.market_sim.trading_action_matrix import trading_action_matrix
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


REPO_ROOT = Path(__file__).resolve().parents[3]


def _fresh_paths(root: Path) -> DatabasePaths:
    return DatabasePaths(
        control=root / "control.db",
        knowledge=root / "knowledge.db",
        market=root / "market.db",
    )


def _table_exists(path: Path, name: str) -> bool:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    return row is not None


def _insert_paper_deployment(market_db: Path, deployment_id: str = "dep-preserve-1") -> None:
    now = "2026-09-27T12:00:00+00:00"
    with sqlite3.connect(market_db) as conn:
        conn.execute(
            """
            INSERT INTO market_paper_deployments(
                deployment_id, strategy_asset_id, strategy_version, status, mode,
                feed_id, universe_json, risk_config_json, sizing_config_json,
                cadence, env_fingerprint, kill_switch, session_id,
                compatibility_json, feed_health_json, metadata_json, payload_json,
                loop_state_json, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                deployment_id,
                "strat-a4",
                1,
                "ACTIVE",
                "shadow",
                "binance_public",
                '["BTCUSDT"]',
                "{}",
                "{}",
                "every_n_bars",
                "fp-test",
                0,
                None,
                "{}",
                None,
                "{}",
                "{}",
                "{}",
                now,
                now,
            ),
        )
        conn.commit()


def _count_deployments(market_db: Path) -> int:
    with sqlite3.connect(market_db) as conn:
        row = conn.execute("SELECT COUNT(*) FROM market_paper_deployments").fetchone()
    return int(row[0]) if row else 0


class LauncherPaperPreservationTests(unittest.TestCase):
    def test_launcher_start_preserves_market_domain_v2(self) -> None:
        """Simulated normal-mode start upgrade leaves MARKET domain v2 in place."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fresh_paths(Path(tmp))
            report = upgrade_all_databases(paths)
            self.assertTrue(report.completed)
            self.assertEqual(report.phase, CutoverPhase.COMPLETE)
            market_ver = domain_schema_version(paths.market)
            self.assertGreaterEqual(market_ver, 2, msg=f"MARKET domain version={market_ver}")
            self.assertTrue(_table_exists(paths.market, "market_paper_deployments"))
            # Domain migration catalog still owns v2 for MARKET only.
            names = {m.name for m in DOMAIN_MIGRATIONS}
            self.assertIn("market_paper_deployments", names)
            self.assertEqual(ownership_for("market_paper_deployments"), DatabaseDomain.MARKET)
            # CONTROL/KNOWLEDGE must not become a second persistence home.
            self.assertFalse(_table_exists(paths.control, "market_paper_deployments"))
            self.assertFalse(_table_exists(paths.knowledge, "market_paper_deployments"))

    def test_launcher_start_does_not_reset_paper_deployments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fresh_paths(Path(tmp))
            upgrade_all_databases(paths)
            _insert_paper_deployment(paths.market, "dep-no-reset")
            self.assertEqual(_count_deployments(paths.market), 1)
            # Second start / upgrade cycle (API lifespan path) must not wipe rows.
            again = upgrade_all_databases(paths)
            self.assertTrue(again.completed)
            self.assertEqual(_count_deployments(paths.market), 1)
            with sqlite3.connect(paths.market) as conn:
                row = conn.execute(
                    "SELECT status, mode FROM market_paper_deployments WHERE deployment_id=?",
                    ("dep-no-reset",),
                ).fetchone()
            self.assertEqual(row[0], "ACTIVE")
            self.assertEqual(row[1], "shadow")

    def test_launcher_restart_preserves_paper_deployments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fresh_paths(Path(tmp))
            upgrade_all_databases(paths)
            _insert_paper_deployment(paths.market, "dep-restart")
            # Restart = stop + start: upgrade + ensure schema again.
            upgrade_all_databases(paths)
            from Data.backend.db_upgrade import ensure_domain_schema

            ensure_domain_schema(paths.market, DatabaseDomain.MARKET)
            self.assertEqual(_count_deployments(paths.market), 1)
            with sqlite3.connect(paths.market) as conn:
                row = conn.execute(
                    "SELECT deployment_id FROM market_paper_deployments"
                ).fetchone()
            self.assertEqual(row[0], "dep-restart")

    def test_worker_fabric_available_for_autonomous_paper_jobs(self) -> None:
        self.assertIn("market_sim", POOL_CATALOG)
        pool = POOL_CATALOG["market_sim"]
        self.assertEqual(pool.entrypoint, "Data.modules.workers.entrypoints.market_sim")
        self.assertTrue(
            any(str(k).startswith("market_sim") for k in pool.job_kinds),
            msg=f"market_sim job_kinds={pool.job_kinds}",
        )
        self.assertEqual(pool_for_capability("market_sim.gym_episode"), "market_sim")
        self.assertEqual(pool_for_capability("market_sim.research_campaign"), "market_sim")
        # Entry module remains the Worker Fabric owner for market jobs.
        entry = REPO_ROOT / "Data/modules/workers/entrypoints/market_sim.py"
        self.assertTrue(entry.is_file())
        text = entry.read_text(encoding="utf-8")
        self.assertIn("MarketSimControlPlane", text)
        self.assertIn("executed_via", text)

    def test_launcher_does_not_create_paper_deployment(self) -> None:
        launcher_roots = [
            REPO_ROOT / "Data/launcher/host-core/src",
            REPO_ROOT / "Data/launcher/src-tauri/src",
            REPO_ROOT / "leviathan.py",
            REPO_ROOT / "Data/modules/workers/bootstrap.py",
            REPO_ROOT / "Data/modules/common/process_stdio.py",
        ]
        forbidden = (
            "create_and_persist_paper_deployment",
            "create_paper_deployment",
            "upsert_paper_deployment",
            "autonomous_paper_step",
            "PaperDeployment",
            "market_paper_deployments",
        )
        offenders: list[str] = []
        for root in launcher_roots:
            if root.is_file():
                files = [root]
            else:
                files = [
                    p
                    for p in root.rglob("*")
                    if p.suffix in {".rs", ".py", ".ts", ".tsx"} and p.is_file()
                ]
            for path in files:
                text = path.read_text(encoding="utf-8", errors="replace")
                for needle in forbidden:
                    if needle in text:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{needle}")
        self.assertEqual(
            offenders,
            [],
            msg="launcher/bootstrap must not own PaperDeployment lifecycle: "
            + ", ".join(offenders),
        )

    def test_launcher_does_not_bypass_market_sim_owner(self) -> None:
        # Static owner check: MarketSim service remains the create/persist authority.
        service = REPO_ROOT / "Data/modules/market_sim/service.py"
        self.assertTrue(service.is_file())
        text = service.read_text(encoding="utf-8")
        self.assertIn("def create_and_persist_paper_deployment", text)
        self.assertIn("market_paper_deployments", text)
        self.assertIn("live_money", text)

        # Host controller only spawns leviathan.py — never MarketSim constructors.
        controller = REPO_ROOT / "Data/launcher/host-core/src/controller.rs"
        ctrl = controller.read_text(encoding="utf-8")
        self.assertIn('args: vec!["leviathan.py".into()]', ctrl)
        self.assertNotIn("MarketSim", ctrl)
        self.assertNotIn("PaperDeployment", ctrl)
        self.assertNotIn("autonomous_paper", ctrl)

        # Bootstrap AST: no direct MarketSim / paper imports.
        bootstrap = REPO_ROOT / "Data/modules/workers/bootstrap.py"
        tree = ast.parse(bootstrap.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
        self.assertFalse(any("market_sim" in name for name in imported))
        self.assertFalse(any("paper_deployment" in name for name in imported))

    def test_live_money_remains_blocked_after_launcher_start(self) -> None:
        matrix = trading_action_matrix()
        self.assertTrue(matrix["truth"]["live_money_always_blocked"])
        for action in matrix["actions"]:
            self.assertEqual(
                action["live_money"],
                "BLOCKED",
                msg=f"{action['action']} must keep live_money BLOCKED",
            )
        modes = build_mode_capability_matrix(feature_enabled=True)
        for mode in modes:
            self.assertEqual(mode.get("live_trading"), "BLOCKED")
        from Data.modules.market_sim.capabilities import build_market_capabilities

        caps = build_market_capabilities(feature_enabled=True)
        self.assertEqual(caps.get("live_trading_default"), "BLOCKED")
        for market in caps.get("markets") or []:
            self.assertEqual(market.get("LIVE_TRADING_AVAILABLE"), "BLOCKED")


if __name__ == "__main__":
    unittest.main()
