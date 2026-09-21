from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geolibre_hades as gh


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "demo-cities.geojson"


class GeoLibreAdapterTests(unittest.TestCase):
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

    def test_remote_urls_are_rejected(self) -> None:
        with self.assertRaises(gh.GeoLibreError):
            gh._resolve_local_path("https://example.com/data.geojson")

    def test_inspect_fixture_and_knowledge_envelope(self) -> None:
        args = SimpleNamespace(path=str(FIXTURE), geojson="", dataset_id="", sample_limit=2)
        result = gh.command_inspect(args)
        self.assertTrue(result["ok"])
        self.assertEqual(result["feature_count"], 3)
        self.assertIn("Point", result["geometry_counts"])
        self.assertIn("Polygon", result["geometry_counts"])
        self.assertTrue(result["hades_knowledge"])
        self.assertEqual(result["hades_knowledge"][0]["metadata"]["provider"], "GeoLibre")

    def test_load_list_and_spatial_query(self) -> None:
        load_args = SimpleNamespace(dataset_id="demo-cities", path=str(FIXTURE), geojson="", title="Demo")
        loaded = gh.command_load(load_args)
        self.assertEqual(loaded["dataset_id"], "demo-cities")
        self.assertEqual(loaded["feature_count"], 3)

        listed = gh.command_list(SimpleNamespace())
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["datasets"][0]["dataset_id"], "demo-cities")

        query_args = SimpleNamespace(
            path="",
            geojson="",
            dataset_id="demo-cities",
            bbox=json.dumps([4.7, 52.2, 5.1, 52.5]),
            where=json.dumps({"name": {"contains": "Amster"}}),
            geometry_types=json.dumps(["Point"]),
            contains_point="",
            within_distance="",
            limit=10,
            max_bytes=100_000,
        )
        queried = gh.command_query(query_args)
        self.assertEqual(queried["matched_features"], 1)
        self.assertEqual(queried["features"][0]["properties"]["name"], "Amsterdam")
        self.assertTrue(queried["hades_knowledge"])

    def test_polygon_contains_point(self) -> None:
        args = SimpleNamespace(
            path=str(FIXTURE),
            geojson="",
            dataset_id="",
            bbox="",
            where="",
            geometry_types=json.dumps(["Polygon"]),
            contains_point=json.dumps([4.9, 52.37]),
            within_distance="",
            limit=10,
            max_bytes=100_000,
        )
        result = gh.command_query(args)
        self.assertEqual(result["matched_features"], 1)
        self.assertEqual(result["features"][0]["properties"]["name"], "Randstad-box")

    def test_analyze_numeric_stats(self) -> None:
        args = SimpleNamespace(path="", geojson=FIXTURE.read_text(encoding="utf-8"), dataset_id="")
        result = gh.command_analyze(args)
        self.assertEqual(result["numeric_property_stats"]["pop"]["max"], 900000)
        self.assertEqual(result["numeric_property_stats"]["pop"]["count"], 3)


if __name__ == "__main__":
    unittest.main()
