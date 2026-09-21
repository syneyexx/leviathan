#!/usr/bin/env python3
"""Focused checks for the batch-4 HADES plugins (no live LM Studio / ffmpeg required)."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
sys.path.insert(0, str(PLUGINS / "_shared"))
sys.path.insert(0, str(ROOT / "backend"))

from pack_lib import pack_local
from platform_db import PlatformDatabase
from platform_services import PluginManager

BATCH4 = {
    "codebase-memory",
    "open-code-review",
    "worktrunk",
    "openai-skills",
    "no-ai-slop",
    "diagram-design",
    "trading-agents",
    "ruview",
    "data-formulator",
    "eli5",
    "graft",
    "openmontage",
    "autoclip",
    "ui-ux-pro-max",
    "superpowers",
    "frontend-design-toolkit",
    "karpathy-skills",
    "anthropic-agent-skills",
    "massgen",
    "context-engineering-skills",
    "omniroute",
    "knowledge-work-plugins",
    "claude-plugins-official",
    "firm-protocol",
}


class Batch4PluginTests(unittest.TestCase):
    def test_manifests_and_skills_present(self) -> None:
        for plugin_id in sorted(BATCH4):
            folder = PLUGINS / plugin_id
            manifest_path = folder / "hades-plugin.json"
            self.assertTrue(manifest_path.is_file(), plugin_id)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["id"], plugin_id)
            self.assertTrue(manifest.get("tools"))
            self.assertIn("marketplace", manifest)
            self.assertTrue((folder / "pack_hadesplugin.py").is_file())
            skills = list((folder / "skills").rglob("SKILL.md")) if (folder / "skills").is_dir() else []
            self.assertTrue(skills, plugin_id)

    def test_skill_bridge_lists_real_content(self) -> None:
        for plugin_id in ("anthropic-agent-skills", "no-ai-slop", "superpowers", "eli5"):
            listed = subprocess.run(
                [sys.executable, "skill_bridge.py", "list", "--limit", "50"],
                cwd=str(PLUGINS / plugin_id),
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            self.assertEqual(listed.returncode, 0, listed.stderr or listed.stdout)
            payload = json.loads(listed.stdout)
            self.assertGreaterEqual(payload["count"], 1, plugin_id)
            search = subprocess.run(
                [sys.executable, "skill_bridge.py", "search", "--query", "skill", "--limit", "5"],
                cwd=str(PLUGINS / plugin_id),
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            self.assertEqual(search.returncode, 0, search.stderr)
            self.assertGreaterEqual(json.loads(search.stdout)["count"], 1)

    def test_no_ai_slop_clean_rewrites_text(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "hades_bridge.py",
                "clean",
                "--text",
                "Furthermore, we should delve into the tapestry of robust solutions.",
            ],
            cwd=str(PLUGINS / "no-ai-slop"),
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["changed"])
        self.assertNotIn("delve", payload["text"].lower())

    def test_eli5_and_diagram_tools(self) -> None:
        eli5 = subprocess.run(
            [sys.executable, "hades_bridge.py", "eli5", "--topic", "SQLite FTS", "--audience", "kid"],
            cwd=str(PLUGINS / "eli5"),
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        self.assertEqual(eli5.returncode, 0, eli5.stderr)
        self.assertIn("SQLite FTS", json.loads(eli5.stdout)["topic"])
        with tempfile.TemporaryDirectory() as td:
            diagram = subprocess.run(
                [sys.executable, str(PLUGINS / "diagram-design" / "hades_bridge.py"), "diagram", "--title", "Flow", "--items", "A;B;C"],
                cwd=td,
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            self.assertEqual(diagram.returncode, 0, diagram.stderr)
            payload = json.loads(diagram.stdout)
            self.assertTrue(Path(payload["output"]).is_file())

    def test_codebase_memory_index_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sample.py").write_text("def hello_hades():\n    return 1\n", encoding="utf-8")
            db = root / "mem.sqlite"
            indexed = subprocess.run(
                [
                    sys.executable,
                    str(PLUGINS / "codebase-memory" / "hades_bridge.py"),
                    "index",
                    "--root",
                    str(root),
                    "--db",
                    str(db),
                    "--limit",
                    "50",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            self.assertEqual(indexed.returncode, 0, indexed.stderr)
            self.assertTrue(json.loads(indexed.stdout)["ok"])
            queried = subprocess.run(
                [
                    sys.executable,
                    str(PLUGINS / "codebase-memory" / "hades_bridge.py"),
                    "query",
                    "--query",
                    "hello_hades",
                    "--db",
                    str(db),
                    "--limit",
                    "10",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            self.assertEqual(queried.returncode, 0, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["hits"])

    def test_open_code_review_static_and_model_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "risky.py"
            target.write_text("password = 'hunter2'\neval('1')\n", encoding="utf-8")
            static = subprocess.run(
                [sys.executable, str(PLUGINS / "open-code-review" / "hades_bridge.py"), "review_file", "--path", str(target)],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            self.assertEqual(static.returncode, 0, static.stderr)
            findings = {item["rule"] for item in json.loads(static.stdout)["findings"]}
            self.assertIn("possible_secret", findings)
            self.assertIn("dangerous_eval", findings)
            modeled = subprocess.run(
                [
                    sys.executable,
                    str(PLUGINS / "open-code-review" / "hades_bridge.py"),
                    "review_with_model",
                    "--path",
                    str(target),
                    "--model",
                    "local-test-model",
                    "--base-url",
                    "http://127.0.0.1:1",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            self.assertNotEqual(modeled.returncode, 0)
            self.assertFalse(json.loads(modeled.stdout).get("ok"))

    def test_worktrunk_list_this_repo(self) -> None:
        listed = subprocess.run(
            [sys.executable, str(PLUGINS / "worktrunk" / "hades_bridge.py"), "list", "--repo", str(ROOT)],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        self.assertEqual(listed.returncode, 0, listed.stderr)
        payload = json.loads(listed.stdout)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["count"], 1)

    def test_data_formulator_csv_chart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "data.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["name", "value"])
                writer.writerow(["a", "1"])
                writer.writerow(["b", "3"])
            out = Path(td) / "chart.html"
            charted = subprocess.run(
                [
                    sys.executable,
                    str(PLUGINS / "data-formulator" / "hades_bridge.py"),
                    "chart",
                    "--path",
                    str(csv_path),
                    "--x",
                    "name",
                    "--y",
                    "value",
                    "--type",
                    "bar",
                    "--output",
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            self.assertEqual(charted.returncode, 0, charted.stderr)
            self.assertTrue(out.is_file())
            self.assertIn("<svg", out.read_text(encoding="utf-8"))

    def test_graft_index_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("import b\n", encoding="utf-8")
            (root / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
            graph = root / "graph.json"
            indexed = subprocess.run(
                [
                    sys.executable,
                    str(PLUGINS / "graft" / "hades_bridge.py"),
                    "index",
                    "--root",
                    str(root),
                    "--output",
                    str(graph),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            self.assertEqual(indexed.returncode, 0, indexed.stderr)
            neighbors = subprocess.run(
                [
                    sys.executable,
                    str(PLUGINS / "graft" / "hades_bridge.py"),
                    "neighbors",
                    "--graph",
                    str(graph),
                    "--file",
                    "a.py",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            self.assertEqual(neighbors.returncode, 0, neighbors.stderr)
            self.assertIn("b", json.loads(neighbors.stdout)["imports"])

    def test_ffmpeg_tools_fail_closed_without_file(self) -> None:
        missing = subprocess.run(
            [sys.executable, str(PLUGINS / "autoclip" / "hades_bridge.py"), "probe", "--path", "definitely-missing.mp4"],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        payload = json.loads(missing.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "file_not_found")

    def test_trading_and_massgen_and_omniroute_fail_closed_without_model(self) -> None:
        trading = subprocess.run(
            [
                sys.executable,
                str(PLUGINS / "trading-agents" / "hades_bridge.py"),
                "run_round",
                "--ticker",
                "AAPL",
                "--model",
                "local-test-model",
                "--base-url",
                "http://127.0.0.1:1",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        self.assertNotEqual(trading.returncode, 0)
        self.assertIn("PAPER", json.loads(trading.stdout).get("disclaimer", "SIMULATION/PAPER ONLY"))
        committee = subprocess.run(
            [
                sys.executable,
                str(PLUGINS / "massgen" / "hades_bridge.py"),
                "run_committee",
                "--prompt",
                "ping",
                "--model",
                "local-test-model",
                "--base-url",
                "http://127.0.0.1:1",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        self.assertNotEqual(committee.returncode, 0)
        complete = subprocess.run(
            [
                sys.executable,
                str(PLUGINS / "omniroute" / "hades_bridge.py"),
                "complete",
                "--prompt",
                "hi",
                "--model",
                "local-test-model",
                "--base-url",
                "http://127.0.0.1:1",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        self.assertNotEqual(complete.returncode, 0)

    def test_ruview_parse_csi_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dump = Path(td) / "csi.json"
            dump.write_text(json.dumps([{"amp": "1.5", "ts": "1"}, {"amp": "2.5", "ts": "2"}]), encoding="utf-8")
            parsed = subprocess.run(
                [sys.executable, str(PLUGINS / "ruview" / "hades_bridge.py"), "parse_csi", "--path", str(dump)],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            payload = json.loads(parsed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["samples"], 2)
            self.assertIn("amp", payload["numeric"])

    def test_import_ready_and_invoke_skill_search(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = PlatformDatabase(str(root / "platform.db"))
        db.initialize()
        manager = PluginManager(db, root / "data")
        source = root / "anthropic-agent-skills"
        shutil.copytree(
            PLUGINS / "anthropic-agent-skills",
            source,
            ignore=shutil.ignore_patterns("dist", "overlay", "pack_hadesplugin.py"),
        )
        converted = manager.import_local_folder(source, install_dependencies=False)
        plugin = converted["plugin"]
        self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
        db.set_plugin_state(plugin["id"], enabled=True)
        listed = manager.invoke(plugin["id"], "list_skills", {"limit": 20}, approved_by_user=True)
        self.assertEqual(listed["status"], "completed", listed.get("error"))
        searched = manager.invoke(plugin["id"], "search_skills", {"query": "frontend", "limit": 5}, approved_by_user=True)
        self.assertEqual(searched["status"], "completed", searched.get("error"))
        blob = (searched.get("stdout") or "") + (searched.get("output") or "")
        self.assertIn("SKILL.md", blob)

    def test_local_pack_roundtrip(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "out"
        package = pack_local(plugin_dir=PLUGINS / "codebase-memory", out_dir=out)
        self.assertTrue(package.is_file())
        db = PlatformDatabase(str(Path(tmp.name) / "platform.db"))
        db.initialize()
        manager = PluginManager(db, Path(tmp.name) / "data")
        imported = manager.import_zip(package, install_dependencies=False)
        self.assertEqual(imported["plugin"]["status"], "ready")
        self.assertEqual(imported["plugin"]["id"], "codebase-memory")


if __name__ == "__main__":
    unittest.main()
