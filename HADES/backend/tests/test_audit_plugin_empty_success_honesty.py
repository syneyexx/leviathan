"""Gate-visible honesty regressions for plugin empty-success sinks."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class PluginEmptySuccessHonestyTests(unittest.TestCase):
    def test_voicestudio_api_probe_empty_not_ok(self) -> None:
        bridge = _load("vs_bridge_honesty", REPO / "plugins" / "voicestudio" / "hades_bridge.py")
        body = json.dumps({"voices": [], "engines": []}).encode("utf-8")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return body

        with mock.patch.object(bridge.urllib.request, "urlopen", return_value=_Resp()):
            payload = bridge.api_probe("http://127.0.0.1:3900/v1")
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "empty_voices_and_engines")

    def test_ghosttrack_show_ip_empty_not_ok(self) -> None:
        bridge = _load("gt_bridge_honesty", REPO / "plugins" / "ghosttrack" / "hades_bridge.py")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"  \n"

        with mock.patch.object(bridge, "urlopen", return_value=_Resp()):
            payload = bridge.show_ip()
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "empty_ip_response")

    def test_geolibre_empty_featurecollection_not_ok(self) -> None:
        gh = _load("geolibre_honesty", REPO / "plugins" / "geolibre" / "geolibre_hades.py")
        empty = json.dumps({"type": "FeatureCollection", "features": []})
        with tempfile.TemporaryDirectory() as td:
            os.environ["HADES_GEOLIBRE_DATA"] = str(Path(td) / "datasets")
            try:
                inspect_result = gh.command_inspect(
                    Namespace(path="", geojson=empty, dataset_id="", sample_limit=2)
                )
                analyze_result = gh.command_analyze(Namespace(path="", geojson=empty, dataset_id=""))
                load_result = gh.command_load(
                    Namespace(dataset_id="empty-set", path="", geojson=empty, title="Empty")
                )
            finally:
                os.environ.pop("HADES_GEOLIBRE_DATA", None)
        self.assertFalse(inspect_result.get("ok"))
        self.assertFalse(analyze_result.get("ok"))
        self.assertFalse(load_result.get("ok"))
        self.assertEqual(load_result.get("error"), "empty FeatureCollection")

    def test_moneyprinter_seed_rejects_blank_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = (REPO / "plugins" / "moneyprinter-turbo" / "hades_bridge.py").read_text(encoding="utf-8")
            (root / "hades_bridge.py").write_text(src, encoding="utf-8")
            (root / "config.example.toml").write_text(
                'llm_provider = "moonshot"\nopenai_api_key = ""\nopenai_base_url = ""\n'
                'openai_model_name = ""\nlisten_host = "0.0.0.0"\n',
                encoding="utf-8",
            )
            bridge = _load("mp_bridge_honesty", root / "hades_bridge.py")
            blank_model = bridge.seed_lm_studio("http://127.0.0.1:1234/v1", "  ", "lm-studio")
            blank_base = bridge.seed_lm_studio(" ", "local-model", "lm-studio")
            ok = bridge.seed_lm_studio("http://127.0.0.1:1234/v1", "local-test-model", "lm-studio")
        self.assertFalse(blank_model.get("ok"))
        self.assertEqual(blank_model.get("error"), "model_required")
        self.assertFalse(blank_base.get("ok"))
        self.assertEqual(blank_base.get("error"), "base_url_required")
        self.assertTrue(ok.get("ok"), ok)

    def test_hypit_empty_source_not_ok(self) -> None:
        bridge = _load("hypit_bridge_honesty", REPO / "plugins" / "hypit" / "hades_bridge.py")
        missing = bridge.inspect_source("/no/such/hypit-source.svml")
        self.assertFalse(missing.get("ok"))
        self.assertEqual(missing.get("error"), "source_not_found")
        with tempfile.TemporaryDirectory() as td:
            blank = Path(td) / "blank.svml"
            blank.write_text("\n", encoding="utf-8")
            empty = bridge.inspect_source(str(blank))
        self.assertFalse(empty.get("ok"))
        self.assertEqual(empty.get("error"), "empty_source")
        fetch = bridge.hypit_media_fetch("not-a-url", "out.mp4")
        self.assertFalse(fetch.get("ok"))
        self.assertEqual(fetch.get("error"), "http_url_required")


if __name__ == "__main__":
    unittest.main()
