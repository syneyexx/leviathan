#!/usr/bin/env python3
"""Focused checks for the upstream plugin batch (no live LM / browsers required)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"


class UpstreamPluginBatchTests(unittest.TestCase):
    EXPECTED = {
        "impeccable",
        "gsap-skills",
        "design-dna",
        "patchright",
        "dspy",
        "moneyprinter-turbo",
        "vibe-trading",
    }

    def test_manifests_present_and_well_formed(self) -> None:
        for plugin_id in sorted(self.EXPECTED):
            manifest_path = PLUGINS / plugin_id / "hades-plugin.json"
            self.assertTrue(manifest_path.is_file(), plugin_id)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["id"], plugin_id)
            self.assertTrue(manifest.get("tools"))
            self.assertIn("marketplace", manifest)
            self.assertTrue((PLUGINS / plugin_id / "pack_hadesplugin.py").is_file())

    def test_local_pack_patchright_and_skill_search(self) -> None:
        packer = PLUGINS / "gsap-skills" / "pack_hadesplugin.py"
        out = Path(tempfile.mkdtemp())
        process = subprocess.run(
            [sys.executable, str(packer), "--out", str(out)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
            shell=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr or process.stdout)
        packages = list(out.glob("*.HadesPlugin"))
        self.assertEqual(len(packages), 1)
        with tempfile.TemporaryDirectory() as td:
            zipfile.ZipFile(packages[0]).extractall(td)
            source = Path(td) / "source"
            listed = subprocess.run(
                [sys.executable, "skill_bridge.py", "list", "--limit", "20"],
                cwd=str(source),
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            payload = json.loads(listed.stdout)
            self.assertGreaterEqual(payload["count"], 5)
            search = subprocess.run(
                [sys.executable, "skill_bridge.py", "search", "--query", "ScrollTrigger", "--limit", "5"],
                cwd=str(source),
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            self.assertEqual(search.returncode, 0, search.stderr)
            hits = json.loads(search.stdout)["hits"]
            self.assertTrue(hits)

    def test_moneyprinter_seed_lm_studio(self) -> None:
        bridge = (PLUGINS / "moneyprinter-turbo" / "hades_bridge.py").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "hades_bridge.py").write_text(bridge, encoding="utf-8")
            (root / "main.py").write_text("# stub\n", encoding="utf-8")
            (root / "webui").mkdir()
            (root / "webui" / "Main.py").write_text("# stub\n", encoding="utf-8")
            (root / "config.example.toml").write_text(
                'llm_provider = "moonshot"\nopenai_api_key = ""\nopenai_base_url = ""\nopenai_model_name = ""\nlisten_host = "0.0.0.0"\n',
                encoding="utf-8",
            )
            seeded = subprocess.run(
                [
                    sys.executable,
                    "hades_bridge.py",
                    "seed_lm_studio",
                    "--model",
                    "local-test-model",
                    "--base-url",
                    "http://127.0.0.1:1234/v1",
                ],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            self.assertEqual(seeded.returncode, 0, seeded.stderr)
            config = (root / "config.toml").read_text(encoding="utf-8")
            self.assertIn('llm_provider = "openai"', config)
            self.assertIn('openai_model_name = "local-test-model"', config)
            self.assertIn('openai_base_url = "http://127.0.0.1:1234/v1"', config)

    def test_dspy_and_patchright_doctor_import_paths(self) -> None:
        for plugin_id in ("dspy", "patchright"):
            bridge = PLUGINS / plugin_id / "hades_bridge.py"
            process = subprocess.run(
                [sys.executable, str(bridge), "doctor"],
                cwd=str(PLUGINS / plugin_id),
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr or process.stdout)
            payload = json.loads(process.stdout)
            self.assertIn("modules", payload)


if __name__ == "__main__":
    unittest.main()
