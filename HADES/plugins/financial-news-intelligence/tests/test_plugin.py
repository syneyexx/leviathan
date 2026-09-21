from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import financial_news_intelligence as fni
from source_catalog import CATALOG


def test_catalog_contract():
    assert 300 <= len(CATALOG) <= 500
    assert len({x.domain for x in CATALOG}) == len(CATALOG)
    assert not any("news.google" in x.url or "google.com/news" in x.url for x in CATALOG)


def test_balanced_selection():
    selected = fni.select_sources(400)
    assert len(selected) == 400
    assert len({x.category for x in selected}) >= 6


def test_normalize_url():
    value = fni.normalize_url("https://Example.com/a?utm_source=x&id=1#frag")
    assert value == "https://example.com/a?id=1"


def test_impact_analysis():
    row = {
        "title": "Company announces acquisition after earnings beat",
        "summary": "Revenue rose and guidance increased.",
        "article_text": "",
        "source_category": "corporate_newsrooms",
    }
    result = fni.analyze(row)
    assert "earnings" in result["event_types"]
    assert "merger_acquisition_deal" in result["event_types"]
    assert result["impact_score"] >= 50


def test_manifest_defaults_match_contract():
    manifest = json.loads((ROOT / "hades-plugin.json").read_text(encoding="utf-8"))
    fetch = next(x for x in manifest["tools"] if x["name"] == "fetch_financial_news")
    max_sources = fetch["input_schema"]["properties"]["max_sources"]
    assert max_sources["minimum"] == 300
    assert max_sources["maximum"] == 500
    assert max_sources["default"] <= len(CATALOG)
