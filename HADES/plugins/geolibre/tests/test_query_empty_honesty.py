#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import geolibre_hades as gh  # noqa: E402

FIXTURE = ROOT / "fixtures" / "demo-cities.geojson"


class GeoLibreQueryEmptyHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmp.name) / "datasets"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._env = os.environ.copy()
        os.environ["HADES_GEOLIBRE_DATA"] = str(self.data_root)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def test_filtered_empty_query_is_not_ok(self) -> None:
        args = Namespace(
            path=str(FIXTURE),
            geojson="",
            dataset_id="",
            bbox="",
            where=json.dumps({"name": {"contains": "zzz-no-match"}}),
            geometry_types="",
            contains_point="",
            within_distance="",
            limit=10,
            max_bytes=100_000,
        )
        result = gh.command_query(args)
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("matched_features"), 0)
        self.assertIn("no features matched filters", str(result.get("error") or ""))

    def test_main_exits_nonzero_when_ok_false(self) -> None:
        code = gh.main(
            [
                "query",
                "--path",
                str(FIXTURE),
                "--where",
                json.dumps({"name": {"contains": "zzz-no-match"}}),
            ]
        )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
