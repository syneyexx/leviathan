"""Regression tests for shipped HADES plugin manifests under plugins/."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "_shared"))

from pack_lib import pack_local
from platform_db import PlatformDatabase
from platform_services import PluginManager

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "plugins"
EXPECTED_PLUGIN_IDS = {
    "gods-eye-view",
    "unsloth",
    "graphrag",
    "gpt-crawler",
    "awesome-llm-apps",
    "activepieces",
    "awesome-claude-code",
    "awesome-claude-code-toolkit",
    "ponytail",
    "markitdown",
    "composio",
    "voicestudio",
    "chrome-devtools-mcp",
    "antigravity-awesome-skills",
    "ecc",
    "desktop-commander-mcp",
    "design-dna",
    "project-nomad",
    # Batch 2 curated upstream wrappers
    "anthropic-cybersecurity-skills",
    "searxng",
    "scrapling",
    "puppeteer",
    "rtk",
    "agent-reach",
    "agentic-awesome-skills",
    "headroom",
    "claude-code-best-practice",
    "claude-osint",
    "humanizer",
    "kotaemon",
    "local-stt-paste",
    "ghosttrack",
    "hypit",
    "deep-web-downloader",
    "sinwindie-osint",
    "netstriker-ai",
}


class PluginCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "platform.db"))
        self.db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_expected_plugin_manifests_exist(self) -> None:
        found = {
            path.parent.name
            for path in PLUGINS_ROOT.glob("*/hades-plugin.json")
        }
        self.assertTrue(EXPECTED_PLUGIN_IDS.issubset(found), sorted(EXPECTED_PLUGIN_IDS - found))

    def test_each_manifest_imports_ready_and_exposes_tools(self) -> None:
        manager = PluginManager(self.db, self.root / "data")
        for plugin_id in sorted(EXPECTED_PLUGIN_IDS):
            with self.subTest(plugin_id=plugin_id):
                manifest_path = PLUGINS_ROOT / plugin_id / "hades-plugin.json"
                self.assertTrue(manifest_path.is_file(), plugin_id)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest.get("format"), 1)
                self.assertEqual(manifest.get("id"), plugin_id)
                self.assertIsInstance(manifest.get("tools"), list)
                self.assertGreaterEqual(len(manifest["tools"]), 1)
                for tool in manifest["tools"]:
                    self.assertTrue(str(tool.get("name", "")).strip())
                    self.assertIn("input_schema", tool)

                source = self.root / f"fixture-{plugin_id}"
                if source.exists():
                    shutil.rmtree(source)
                source.mkdir()
                for item in (PLUGINS_ROOT / plugin_id).iterdir():
                    if item.name in {"dist", "overlay", "pack_hadesplugin.py", "README.md"}:
                        continue
                    target = source / item.name
                    if item.is_dir():
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)
                (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

                runtime = str(manifest.get("runtime_type", "python"))
                if runtime == "node" and not (source / "package.json").exists():
                    (source / "package.json").write_text(
                        json.dumps({"name": plugin_id, "private": True, "scripts": {"start": "node -e \"console.log('ok')\""}}),
                        encoding="utf-8",
                    )
                if runtime == "python" and not (source / "requirements.txt").exists() and not (source / "pyproject.toml").exists():
                    (source / "requirements.txt").write_text("# test stub\n", encoding="utf-8")

                converted = manager.import_local_folder(source, install_dependencies=False)
                plugin = converted["plugin"]
                self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
                self.assertFalse(plugin["enabled"])
                tool_names = {tool["name"] for tool in converted["tools"]}
                expected_names = {tool["name"] for tool in manifest["tools"]}
                self.assertTrue(expected_names <= tool_names, sorted(expected_names - tool_names))

    def test_catalog_bridge_search_invokes_through_plugin_manager(self) -> None:
        source = self.root / "awesome-llm-apps-runtime"
        if source.exists():
            shutil.rmtree(source)
        shutil.copytree(
            PLUGINS_ROOT / "awesome-llm-apps",
            source,
            ignore=shutil.ignore_patterns("dist", "overlay", "pack_hadesplugin.py"),
        )
        (source / "SAMPLE.md").write_text(
            "# Demo App\n\nAn example RAG chatbot for HADES plugin tests.\n",
            encoding="utf-8",
        )
        manager = PluginManager(self.db, self.root / "data")
        plugin = manager.import_local_folder(source, install_dependencies=False)["plugin"]
        self.db.set_plugin_state(plugin["id"], enabled=True)
        plugin = self.db.get_plugin(plugin["id"])
        listed = manager.invoke(plugin["id"], "list_entries", {"limit": 20}, approved_by_user=True)
        self.assertEqual(listed["status"], "completed", listed.get("error"))
        self.assertIn("SAMPLE.md", listed.get("stdout", "") + listed.get("output", ""))
        searched = manager.invoke(plugin["id"], "search", {"query": "RAG chatbot", "limit": 5}, approved_by_user=True)
        self.assertEqual(searched["status"], "completed", searched.get("error"))
        self.assertIn("SAMPLE.md", searched.get("stdout", "") + searched.get("output", ""))

    def test_markitdown_doctor_tool_runs(self) -> None:
        source = self.root / "markitdown-runtime"
        if source.exists():
            shutil.rmtree(source)
        shutil.copytree(
            PLUGINS_ROOT / "markitdown",
            source,
            ignore=shutil.ignore_patterns("dist", "pack_hadesplugin.py"),
        )
        manager = PluginManager(self.db, self.root / "data")
        plugin = manager.import_local_folder(source, install_dependencies=False)["plugin"]
        self.db.set_plugin_state(plugin["id"], enabled=True)
        plugin = self.db.get_plugin(plugin["id"])
        result = manager.invoke(plugin["id"], "doctor", {}, approved_by_user=True)
        out = (result.get("stdout") or result.get("output") or "")
        self.assertIn("markitdown", out.lower())
        # Without the markitdown package, doctor must fail closed (not fake completed success).
        if result["status"] == "completed":
            payload = json.loads(out)
            self.assertTrue(payload.get("ok"))
        else:
            self.assertEqual(result["status"], "failed", result.get("error"))
            payload = json.loads(out)
            self.assertFalse(payload.get("ok"))

    def test_scrapling_doctor_tool_runs(self) -> None:
        source = self.root / "scrapling-runtime"
        if source.exists():
            shutil.rmtree(source)
        shutil.copytree(
            PLUGINS_ROOT / "scrapling",
            source,
            ignore=shutil.ignore_patterns("dist", "pack_hadesplugin.py"),
        )
        manager = PluginManager(self.db, self.root / "data")
        plugin = manager.import_local_folder(source, install_dependencies=False)["plugin"]
        self.db.set_plugin_state(plugin["id"], enabled=True)
        plugin = self.db.get_plugin(plugin["id"])
        result = manager.invoke(plugin["id"], "doctor", {}, approved_by_user=True)
        out = (result.get("stdout") or result.get("output") or "")
        self.assertIn("scrapling", out.lower())
        # Without the scrapling package, doctor must fail closed (not fake completed success).
        if result["status"] == "completed":
            payload = json.loads(out)
            self.assertTrue(payload.get("ok"))
        else:
            self.assertEqual(result["status"], "failed", result.get("error"))
            payload = json.loads(out)
            self.assertFalse(payload.get("ok"))

    def test_humanizer_skill_bridge_search(self) -> None:
        source = self.root / "humanizer-runtime"
        if source.exists():
            shutil.rmtree(source)
        shutil.copytree(
            PLUGINS_ROOT / "humanizer",
            source,
            ignore=shutil.ignore_patterns("dist", "overlay", "pack_hadesplugin.py"),
        )
        (source / "SKILL.md").write_text(
            "# Humanizer\n\nRewrite AI-sounding text so it reads naturally.\n",
            encoding="utf-8",
        )
        manager = PluginManager(self.db, self.root / "data")
        plugin = manager.import_local_folder(source, install_dependencies=False)["plugin"]
        self.db.set_plugin_state(plugin["id"], enabled=True)
        plugin = self.db.get_plugin(plugin["id"])
        listed = manager.invoke(plugin["id"], "list_skills", {"limit": 20}, approved_by_user=True)
        self.assertEqual(listed["status"], "completed", listed.get("error"))
        searched = manager.invoke(
            plugin["id"],
            "search_skills",
            {"query": "AI-sounding", "limit": 5},
            approved_by_user=True,
        )
        self.assertEqual(searched["status"], "completed", searched.get("error"))
        blob = (searched.get("stdout") or "") + (searched.get("output") or "")
        self.assertIn("SKILL.md", blob)

    def test_netstriker_ai_remediation_tools(self) -> None:
        source = self.root / "netstriker-ai-runtime"
        if source.exists():
            shutil.rmtree(source)
        shutil.copytree(
            PLUGINS_ROOT / "netstriker-ai",
            source,
            ignore=shutil.ignore_patterns("dist", "overlay", "pack_hadesplugin.py", "tests"),
        )
        backend = source / "backend"
        backend.mkdir(parents=True)
        (backend / "remediation.py").write_text(
            'REMEDIATION_GUIDE = {443: ("HTTPS open", "Verify TLS and enable HSTS.")}\n'
            "GENERIC_REMEDIATION = (\"Unknown\", \"Restrict and patch.\")\n"
            "def get_remediation(port, service=\"\"):\n"
            "    return REMEDIATION_GUIDE.get(port, GENERIC_REMEDIATION)\n"
            "def get_remediation_text(port, service=\"\"):\n"
            "    return get_remediation(port, service)[1]\n",
            encoding="utf-8",
        )
        (backend / "compliance.py").write_text(
            "DPDP_MAPPING = {\n"
            "  'high': {'section': 'S8', 'summary': 'high', 'obligation': 'fix'},\n"
            "  'medium': {'section': 'S8', 'summary': 'medium', 'obligation': 'plan'},\n"
            "  'low': {'section': 'S4', 'summary': 'low', 'obligation': 'monitor'},\n"
            "}\n"
            "DPDP_DISCLAIMER = 'guidance only'\n"
            "def add_dpdp_section(risk_label):\n"
            "    info = DPDP_MAPPING.get(risk_label, DPDP_MAPPING['low'])\n"
            "    return {**info, 'disclaimer': DPDP_DISCLAIMER}\n",
            encoding="utf-8",
        )
        (backend / "scanner.py").write_text("# stub\n", encoding="utf-8")
        (backend / "server.py").write_text("# stub\n", encoding="utf-8")
        manager = PluginManager(self.db, self.root / "data")
        plugin = manager.import_local_folder(source, install_dependencies=False)["plugin"]
        self.db.set_plugin_state(plugin["id"], enabled=True)
        plugin = self.db.get_plugin(plugin["id"])
        self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
        listed = manager.invoke(plugin["id"], "list_remediation", {"limit": 20}, approved_by_user=True)
        self.assertEqual(listed["status"], "completed", listed.get("error"))
        blob = (listed.get("stdout") or "") + (listed.get("output") or "")
        self.assertIn("443", blob)
        mapped = manager.invoke(plugin["id"], "dpdp_map", {"risk": "high"}, approved_by_user=True)
        self.assertEqual(mapped["status"], "completed", mapped.get("error"))
        refused = manager.invoke(
            plugin["id"],
            "scan_local",
            {"target": "8.8.8.8", "authorized": "true"},
            approved_by_user=True,
        )
        self.assertNotEqual(refused["status"], "completed")

    def test_claude_osint_skill_bridge_search(self) -> None:
        source = self.root / "claude-osint-runtime"
        if source.exists():
            shutil.rmtree(source)
        shutil.copytree(
            PLUGINS_ROOT / "claude-osint",
            source,
            ignore=shutil.ignore_patterns("dist", "overlay", "pack_hadesplugin.py"),
        )
        skill_dir = source / "skills" / "osint-methodology"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "# OSINT Methodology\n\nAuthorized attack-surface mapping and recon playbooks.\n",
            encoding="utf-8",
        )
        manager = PluginManager(self.db, self.root / "data")
        plugin = manager.import_local_folder(source, install_dependencies=False)["plugin"]
        self.db.set_plugin_state(plugin["id"], enabled=True)
        plugin = self.db.get_plugin(plugin["id"])
        self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
        listed = manager.invoke(plugin["id"], "list_skills", {"limit": 20}, approved_by_user=True)
        self.assertEqual(listed["status"], "completed", listed.get("error"))
        list_blob = (listed.get("stdout") or "") + (listed.get("output") or "")
        self.assertIn("SKILL.md", list_blob)
        searched = manager.invoke(
            plugin["id"],
            "search_skills",
            {"query": "attack-surface", "limit": 5},
            approved_by_user=True,
        )
        self.assertEqual(searched["status"], "completed", searched.get("error"))
        search_blob = (searched.get("stdout") or "") + (searched.get("output") or "")
        self.assertIn("SKILL.md", search_blob)
        loaded = manager.invoke(
            plugin["id"],
            "get_skill",
            {"skill": "osint-methodology", "max_chars": 4000},
            approved_by_user=True,
        )
        self.assertEqual(loaded["status"], "completed", loaded.get("error"))
        get_blob = (loaded.get("stdout") or "") + (loaded.get("output") or "")
        self.assertIn("OSINT Methodology", get_blob)

    def test_local_pack_produces_hadesplugin_zip(self) -> None:
        out = self.root / "out"
        package = pack_local(plugin_dir=PLUGINS_ROOT / "markitdown", out_dir=out)
        self.assertTrue(package.is_file())
        self.assertEqual(package.suffix, ".HadesPlugin")
        manager = PluginManager(self.db, self.root / "data")
        imported = manager.import_zip(package, install_dependencies=False)
        self.assertEqual(imported["plugin"]["status"], "ready")
        self.assertEqual(imported["plugin"]["id"], "markitdown")


if __name__ == "__main__":
    unittest.main()
