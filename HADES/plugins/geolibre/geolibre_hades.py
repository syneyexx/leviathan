#!/usr/bin/env python3
"""Offline-first GeoLibre HADES adapter for local geospatial data use.

Exposes inspect/analyze/load/list/query tools that return compact JSON on stdout
so Chat/Work Runtime can consume GeoJSON and spatial query results programmatically.
No third-party GIS libraries are required; geometry helpers are intentionally small
and deterministic. Network URLs are rejected so internet remains optional.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ADAPTER_VERSION = "0.1.0"
MAX_FEATURES_DEFAULT = 50
MAX_FEATURES_HARD = 500
MAX_BYTES_DEFAULT = 250_000
MAX_BYTES_HARD = 2_000_000
MAX_INLINE_CHARS = 2_000_000
DATASET_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")


class GeoLibreError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _parse_json_arg(raw: str, label: str) -> Any:
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GeoLibreError(f"{label} is geen geldige JSON: {exc.msg}") from exc


def data_root() -> Path:
    configured = os.environ.get("HADES_GEOLIBRE_DATA", "").strip()
    root = Path(configured) if configured else Path.cwd() / ".hades_data" / "datasets"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _safe_dataset_id(dataset_id: str) -> str:
    value = (dataset_id or "").strip()
    if not DATASET_ID_RE.fullmatch(value):
        raise GeoLibreError(
            "dataset_id mag alleen letters, cijfers, '.', '_' of '-' bevatten (max 80, geen pad)."
        )
    return value


def _dataset_paths(dataset_id: str) -> tuple[Path, Path]:
    safe = _safe_dataset_id(dataset_id)
    base = data_root() / safe
    return base.with_suffix(".geojson"), base.with_suffix(".meta.json")


def _resolve_local_path(path_text: str) -> Path:
    raw = (path_text or "").strip()
    if not raw:
        raise GeoLibreError("Pad mag niet leeg zijn.")
    if any(ch in raw for ch in ("\x00", "\r", "\n")):
        raise GeoLibreError("Pad bevat niet-toegestane tekens.")
    lowered = raw.lower()
    if lowered.startswith(("http://", "https://", "ftp://", "file://")):
        raise GeoLibreError(
            "Remote URL's zijn niet toegestaan in deze adapter (internet optioneel). "
            "Gebruik een lokaal bestandspad, inline GeoJSON, of een eerder geladen dataset_id."
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    if not path.is_file():
        raise GeoLibreError(f"Bestand niet gevonden: {path}")
    return path


def _clamp_int(value: int | None, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    return max(minimum, min(maximum, int(value)))


def _feature_collection(data: Any) -> dict[str, Any]:
    if isinstance(data, str):
        if len(data) > MAX_INLINE_CHARS:
            raise GeoLibreError("Inline GeoJSON overschrijdt de maximale grootte.")
        data = _parse_json_arg(data, "geojson")
    if not isinstance(data, dict):
        raise GeoLibreError("GeoJSON moet een JSON-object zijn (FeatureCollection, Feature of Geometry).")
    geo_type = str(data.get("type") or "")
    if geo_type == "FeatureCollection":
        features = data.get("features")
        if not isinstance(features, list):
            raise GeoLibreError("FeatureCollection.features moet een lijst zijn.")
        return {"type": "FeatureCollection", "features": features, "bbox": data.get("bbox")}
    if geo_type == "Feature":
        return {"type": "FeatureCollection", "features": [data], "bbox": data.get("bbox")}
    if geo_type in {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"}:
        return {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": data}],
            "bbox": data.get("bbox"),
        }
    raise GeoLibreError(f"Onbekend GeoJSON-type: {geo_type or '(ontbreekt)'}")


def _load_source(*, path: str | None = None, geojson: Any = None, dataset_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    sources = [bool(path), geojson is not None and geojson != "", bool(dataset_id)]
    if sum(1 for item in sources if item) != 1:
        raise GeoLibreError("Geef precies één bron: path, geojson of dataset_id.")
    provenance: dict[str, Any] = {"retrieved_at": utc_now(), "adapter_version": ADAPTER_VERSION}
    if dataset_id:
        geo_path, meta_path = _dataset_paths(dataset_id)
        if not geo_path.is_file():
            raise GeoLibreError(f"Onbekende dataset_id: {dataset_id}")
        text = geo_path.read_text(encoding="utf-8")
        collection = _feature_collection(json.loads(text))
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        provenance.update(
            {
                "source_type": "geolibre_dataset",
                "dataset_id": _safe_dataset_id(dataset_id),
                "uri": geo_path.as_uri(),
                "title": meta.get("title") or dataset_id,
                "content_sha256": meta.get("content_sha256") or hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
        return collection, provenance
    if path:
        file_path = _resolve_local_path(path)
        text = file_path.read_text(encoding="utf-8")
        if len(text) > MAX_INLINE_CHARS:
            raise GeoLibreError("Bestand overschrijdt de maximale leesgrootte.")
        collection = _feature_collection(json.loads(text))
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        provenance.update(
            {
                "source_type": "geolibre_file",
                "uri": file_path.as_uri(),
                "title": file_path.name,
                "path": str(file_path),
                "content_sha256": digest,
            }
        )
        return collection, provenance
    collection = _feature_collection(geojson)
    serialized = json.dumps(collection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    provenance.update(
        {
            "source_type": "geolibre_inline",
            "uri": "inline:geojson",
            "title": "inline GeoJSON",
            "content_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        }
    )
    return collection, provenance


def _iter_coords(geometry: Any):
    if not isinstance(geometry, dict):
        return
    geo_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if geo_type == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        yield float(coords[0]), float(coords[1])
    elif geo_type in {"MultiPoint", "LineString"} and isinstance(coords, list):
        for item in coords:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                yield float(item[0]), float(item[1])
    elif geo_type in {"MultiLineString", "Polygon"} and isinstance(coords, list):
        for ring in coords:
            if not isinstance(ring, list):
                continue
            for item in ring:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    yield float(item[0]), float(item[1])
    elif geo_type == "MultiPolygon" and isinstance(coords, list):
        for polygon in coords:
            if not isinstance(polygon, list):
                continue
            for ring in polygon:
                if not isinstance(ring, list):
                    continue
                for item in ring:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        yield float(item[0]), float(item[1])
    elif geo_type == "GeometryCollection":
        for child in geometry.get("geometries") or []:
            yield from _iter_coords(child)


def _geometry_bbox(geometry: Any) -> list[float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for x, y in _iter_coords(geometry):
        xs.append(x)
        ys.append(y)
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _collection_bbox(features: list[Any]) -> list[float] | None:
    boxes = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        box = _geometry_bbox(feature.get("geometry"))
        if box:
            boxes.append(box)
    if not boxes:
        return None
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _bboxes_intersect(a: list[float], b: list[float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _point_in_ring(point: tuple[float, float], ring: list[Any]) -> bool:
    x, y = point
    inside = False
    if len(ring) < 3:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = float(ring[i][0]), float(ring[i][1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def _point_in_polygon(point: tuple[float, float], geometry: dict[str, Any]) -> bool:
    geo_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if geo_type == "Polygon" and isinstance(coords, list) and coords:
        if not _point_in_ring(point, coords[0]):
            return False
        for hole in coords[1:]:
            if isinstance(hole, list) and _point_in_ring(point, hole):
                return False
        return True
    if geo_type == "MultiPolygon" and isinstance(coords, list):
        return any(
            _point_in_polygon(point, {"type": "Polygon", "coordinates": polygon})
            for polygon in coords
            if isinstance(polygon, list)
        )
    return False


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(h)))


def _feature_centroid(geometry: Any) -> tuple[float, float] | None:
    coords = list(_iter_coords(geometry))
    if not coords:
        return None
    return sum(x for x, _ in coords) / len(coords), sum(y for _, y in coords) / len(coords)


def _property_schema(features: list[Any], sample_limit: int = 100) -> dict[str, Any]:
    schema: dict[str, dict[str, Any]] = {}
    for feature in features[:sample_limit]:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            continue
        for key, value in props.items():
            name = str(key)
            entry = schema.setdefault(name, {"types": set(), "examples": []})
            entry["types"].add(type(value).__name__)
            if len(entry["examples"]) < 3 and value not in entry["examples"]:
                if isinstance(value, (str, int, float, bool)) or value is None:
                    entry["examples"].append(value)
    return {
        key: {"types": sorted(value["types"]), "examples": value["examples"]}
        for key, value in sorted(schema.items())
    }


def _geometry_counts(features: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for feature in features:
        if not isinstance(feature, dict):
            counts["invalid"] = counts.get("invalid", 0) + 1
            continue
        geometry = feature.get("geometry")
        name = geometry.get("type") if isinstance(geometry, dict) else "null"
        key = str(name or "null")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _match_where(properties: dict[str, Any], where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    for key, expected in where.items():
        actual = properties.get(key)
        if isinstance(expected, dict):
            if "eq" in expected and actual != expected["eq"]:
                return False
            if "ne" in expected and actual == expected["ne"]:
                return False
            if "contains" in expected:
                if not isinstance(actual, str) or str(expected["contains"]).lower() not in actual.lower():
                    return False
            if "gt" in expected:
                try:
                    if not (actual > expected["gt"]):
                        return False
                except Exception:
                    return False
            if "gte" in expected:
                try:
                    if not (actual >= expected["gte"]):
                        return False
                except Exception:
                    return False
            if "lt" in expected:
                try:
                    if not (actual < expected["lt"]):
                        return False
                except Exception:
                    return False
            if "lte" in expected:
                try:
                    if not (actual <= expected["lte"]):
                        return False
                except Exception:
                    return False
            if "in" in expected:
                options = expected["in"]
                if not isinstance(options, list) or actual not in options:
                    return False
        elif actual != expected:
            return False
    return True


def _filter_features(
    features: list[Any],
    *,
    bbox: list[float] | None = None,
    where: dict[str, Any] | None = None,
    geometry_types: list[str] | None = None,
    contains_point: list[float] | None = None,
    within_distance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if bbox is not None:
        if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox)):
            raise GeoLibreError("bbox moet [minLon, minLat, maxLon, maxLat] zijn.")
        if bbox[0] > bbox[2] or bbox[1] > bbox[3]:
            raise GeoLibreError("bbox is ongeldig: min moet <= max zijn.")
    point = None
    if contains_point is not None:
        if not (isinstance(contains_point, list) and len(contains_point) == 2):
            raise GeoLibreError("contains_point moet [lon, lat] zijn.")
        point = (float(contains_point[0]), float(contains_point[1]))
    distance_point = None
    distance_m = None
    if within_distance is not None:
        if not isinstance(within_distance, dict):
            raise GeoLibreError("within_distance moet een object zijn.")
        raw_point = within_distance.get("point")
        meters = within_distance.get("meters")
        if not (isinstance(raw_point, list) and len(raw_point) == 2 and isinstance(meters, (int, float))):
            raise GeoLibreError("within_distance vereist point=[lon,lat] en meters=number.")
        distance_point = (float(raw_point[0]), float(raw_point[1]))
        distance_m = float(meters)
        if distance_m < 0:
            raise GeoLibreError("within_distance.meters mag niet negatief zijn.")
    allowed_types = {item for item in (geometry_types or []) if isinstance(item, str)}
    matched: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            continue
        geometry = feature.get("geometry")
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        if allowed_types:
            geo_type = geometry.get("type") if isinstance(geometry, dict) else None
            if geo_type not in allowed_types:
                continue
        if not _match_where(props, where):
            continue
        feature_bbox = _geometry_bbox(geometry) if isinstance(geometry, dict) else None
        if bbox is not None:
            if not feature_bbox or not _bboxes_intersect(feature_bbox, [float(v) for v in bbox]):
                continue
        if point is not None:
            if not isinstance(geometry, dict) or not _point_in_polygon(point, geometry):
                continue
        if distance_point is not None and distance_m is not None:
            centroid = _feature_centroid(geometry)
            if centroid is None or _haversine_m(distance_point, centroid) > distance_m:
                continue
        matched.append(feature)
    return matched


def _bounded_payload(payload: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text.encode("utf-8")) <= max_bytes:
        return payload
    trimmed = dict(payload)
    features = list(trimmed.get("features") or [])
    while features and len(json.dumps(trimmed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_bytes:
        features.pop()
        trimmed["features"] = features
        trimmed["truncated"] = True
        trimmed["returned_features"] = len(features)
    if len(json.dumps(trimmed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_bytes:
        trimmed.pop("features", None)
        trimmed["truncated"] = True
        trimmed["note"] = "Payload gekapt tot metadata omdat max_bytes te klein was voor features."
    return trimmed


def _knowledge_envelope(provenance: dict[str, Any], summary: str, content: str) -> list[dict[str, Any]]:
    return [
        {
            "title": provenance.get("title") or "GeoLibre dataset",
            "uri": provenance.get("uri") or "geolibre:local",
            "source_type": provenance.get("source_type") or "geolibre",
            "content": content,
            "metadata": {
                "provider": "GeoLibre",
                "adapter_version": ADAPTER_VERSION,
                "retrieved_at": provenance.get("retrieved_at"),
                "content_sha256": provenance.get("content_sha256"),
                "dataset_id": provenance.get("dataset_id"),
                "summary": summary,
            },
        }
    ]


def command_inspect(args: argparse.Namespace) -> dict[str, Any]:
    collection, provenance = _load_source(path=args.path, geojson=args.geojson, dataset_id=args.dataset_id)
    features = [item for item in collection.get("features", []) if isinstance(item, dict)]
    sample_limit = _clamp_int(args.sample_limit, 5, 0, 25)
    samples = []
    for feature in features[:sample_limit]:
        samples.append(
            {
                "id": feature.get("id"),
                "geometry_type": (feature.get("geometry") or {}).get("type") if isinstance(feature.get("geometry"), dict) else None,
                "properties": feature.get("properties") if isinstance(feature.get("properties"), dict) else {},
                "bbox": _geometry_bbox(feature.get("geometry")),
            }
        )
    summary = {
        "ok": len(features) > 0,
        "feature_count": len(features),
        "geometry_counts": _geometry_counts(features),
        "bbox": collection.get("bbox") or _collection_bbox(features),
        "property_schema": _property_schema(features),
        "sample_features": samples,
        "provenance": provenance,
    }
    if not summary["ok"]:
        summary["error"] = "empty FeatureCollection"
    summary["hades_knowledge"] = _knowledge_envelope(
        provenance,
        summary=f"{len(features)} features; bbox={summary['bbox']}",
        content=_pretty({"feature_count": len(features), "geometry_counts": summary["geometry_counts"], "bbox": summary["bbox"], "property_schema": summary["property_schema"]}),
    )
    return summary


def command_analyze(args: argparse.Namespace) -> dict[str, Any]:
    collection, provenance = _load_source(path=args.path, geojson=args.geojson, dataset_id=args.dataset_id)
    features = [item for item in collection.get("features", []) if isinstance(item, dict)]
    numeric_stats: dict[str, dict[str, float]] = {}
    for feature in features:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        for key, value in props.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            stats = numeric_stats.setdefault(str(key), {"count": 0, "min": float(value), "max": float(value), "sum": 0.0})
            number = float(value)
            stats["count"] += 1
            stats["min"] = min(stats["min"], number)
            stats["max"] = max(stats["max"], number)
            stats["sum"] += number
    for stats in numeric_stats.values():
        stats["avg"] = stats["sum"] / stats["count"] if stats["count"] else 0.0
        del stats["sum"]
    result = {
        "ok": len(features) > 0,
        "feature_count": len(features),
        "geometry_counts": _geometry_counts(features),
        "bbox": collection.get("bbox") or _collection_bbox(features),
        "numeric_property_stats": numeric_stats,
        "property_schema": _property_schema(features),
        "provenance": provenance,
    }
    if not result["ok"]:
        result["error"] = "empty FeatureCollection"
    result["hades_knowledge"] = _knowledge_envelope(
        provenance,
        summary=f"analyze {len(features)} features",
        content=_pretty(result),
    )
    return result


def command_load(args: argparse.Namespace) -> dict[str, Any]:
    dataset_id = _safe_dataset_id(args.dataset_id)
    if not args.path and (args.geojson is None or args.geojson == ""):
        raise GeoLibreError("load vereist path of geojson plus dataset_id.")
    if args.path and args.geojson not in (None, ""):
        raise GeoLibreError("Geef path of geojson, niet beide.")
    collection, provenance = _load_source(path=args.path or None, geojson=args.geojson if args.geojson not in (None, "") else None)
    features = [item for item in collection.get("features", []) if isinstance(item, dict)]
    if not features:
        return {
            "ok": False,
            "error": "empty FeatureCollection",
            "dataset_id": dataset_id,
            "feature_count": 0,
            "provenance": provenance,
        }
    payload = {
        "type": "FeatureCollection",
        "features": features,
        "bbox": collection.get("bbox") or _collection_bbox(features),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    geo_path, meta_path = _dataset_paths(dataset_id)
    geo_path.write_text(text + "\n", encoding="utf-8")
    meta = {
        "dataset_id": dataset_id,
        "title": args.title.strip() if args.title else provenance.get("title") or dataset_id,
        "loaded_at": utc_now(),
        "feature_count": len(features),
        "bbox": payload["bbox"],
        "geometry_counts": _geometry_counts(features),
        "source": {key: provenance.get(key) for key in ("source_type", "uri", "path", "content_sha256")},
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "adapter_version": ADAPTER_VERSION,
    }
    meta_path.write_text(_pretty(meta) + "\n", encoding="utf-8")
    result = {
        "ok": True,
        "dataset_id": dataset_id,
        "path": str(geo_path),
        "feature_count": len(features),
        "bbox": payload["bbox"],
        "geometry_counts": meta["geometry_counts"],
        "provenance": {**provenance, "dataset_id": dataset_id, "uri": geo_path.as_uri(), "source_type": "geolibre_dataset"},
    }
    result["hades_knowledge"] = _knowledge_envelope(
        result["provenance"],
        summary=f"loaded dataset {dataset_id} with {len(features)} features",
        content=_pretty({"dataset_id": dataset_id, "feature_count": len(features), "bbox": payload["bbox"]}),
    )
    return result


def command_list(_args: argparse.Namespace) -> dict[str, Any]:
    root = data_root()
    datasets = []
    for meta_path in sorted(root.glob("*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        datasets.append(
            {
                "dataset_id": meta.get("dataset_id") or meta_path.stem.replace(".meta", ""),
                "title": meta.get("title"),
                "feature_count": meta.get("feature_count"),
                "bbox": meta.get("bbox"),
                "loaded_at": meta.get("loaded_at"),
                "geometry_counts": meta.get("geometry_counts"),
            }
        )
    return {"ok": True, "data_root": str(root), "datasets": datasets, "count": len(datasets)}


def command_query(args: argparse.Namespace) -> dict[str, Any]:
    collection, provenance = _load_source(path=args.path, geojson=args.geojson, dataset_id=args.dataset_id)
    features = [item for item in collection.get("features", []) if isinstance(item, dict)]
    where = _parse_json_arg(args.where, "where") if isinstance(args.where, str) else args.where
    bbox = _parse_json_arg(args.bbox, "bbox") if isinstance(args.bbox, str) else args.bbox
    geometry_types = _parse_json_arg(args.geometry_types, "geometry_types") if isinstance(args.geometry_types, str) else args.geometry_types
    contains_point = _parse_json_arg(args.contains_point, "contains_point") if isinstance(args.contains_point, str) else args.contains_point
    within_distance = _parse_json_arg(args.within_distance, "within_distance") if isinstance(args.within_distance, str) else args.within_distance
    if where is not None and not isinstance(where, dict):
        raise GeoLibreError("where moet een JSON-object zijn.")
    if geometry_types is not None and not isinstance(geometry_types, list):
        raise GeoLibreError("geometry_types moet een JSON-lijst zijn.")
    matched = _filter_features(
        features,
        bbox=bbox,
        where=where,
        geometry_types=geometry_types,
        contains_point=contains_point,
        within_distance=within_distance,
    )
    filters_applied = any(
        value not in (None, "", [], {})
        for value in (bbox, where, geometry_types, contains_point, within_distance)
    )
    limit = _clamp_int(args.limit, MAX_FEATURES_DEFAULT, 1, MAX_FEATURES_HARD)
    max_bytes = _clamp_int(args.max_bytes, MAX_BYTES_DEFAULT, 1, MAX_BYTES_HARD)
    returned = matched[:limit]
    ok = True
    error = None
    if filters_applied and len(matched) == 0:
        ok = False
        error = "no features matched filters"
    payload = {
        "ok": ok,
        "matched_features": len(matched),
        "returned_features": len(returned),
        "truncated": len(matched) > len(returned),
        "limit": limit,
        "bbox": _collection_bbox(returned),
        "features": returned,
        "query": {
            "bbox": bbox,
            "where": where,
            "geometry_types": geometry_types,
            "contains_point": contains_point,
            "within_distance": within_distance,
        },
        "provenance": provenance,
    }
    if error:
        payload["error"] = error
    payload = _bounded_payload(payload, max_bytes)
    knowledge_content = _pretty(
        {
            "matched_features": payload.get("matched_features"),
            "returned_features": payload.get("returned_features"),
            "bbox": payload.get("bbox"),
            "query": payload.get("query"),
            "features": payload.get("features", [])[:10],
        }
    )
    payload["hades_knowledge"] = _knowledge_envelope(
        provenance,
        summary=f"spatial query matched {payload.get('matched_features')} features",
        content=knowledge_content,
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HADES GeoLibre geospatial data adapter")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_source_flags(command_parser: argparse.ArgumentParser, *, require_dataset_id: bool = False) -> None:
        # nargs='?' so skipped empty HADES placeholders (flag with no value) stay valid.
        command_parser.add_argument("--path", nargs="?", default="")
        command_parser.add_argument("--geojson", nargs="?", default="")
        command_parser.add_argument("--dataset-id", nargs="?", default="", required=require_dataset_id)

    inspect_parser = sub.add_parser("inspect")
    add_source_flags(inspect_parser)
    inspect_parser.add_argument("--sample-limit", type=int, default=5)

    analyze_parser = sub.add_parser("analyze")
    add_source_flags(analyze_parser)

    load_parser = sub.add_parser("load")
    load_parser.add_argument("--dataset-id", required=True)
    load_parser.add_argument("--path", nargs="?", default="")
    load_parser.add_argument("--geojson", nargs="?", default="")
    load_parser.add_argument("--title", nargs="?", default="")

    sub.add_parser("list")

    query_parser = sub.add_parser("query")
    add_source_flags(query_parser)
    query_parser.add_argument("--bbox", nargs="?", default="")
    query_parser.add_argument("--where", nargs="?", default="")
    query_parser.add_argument("--geometry-types", nargs="?", default="")
    query_parser.add_argument("--contains-point", nargs="?", default="")
    query_parser.add_argument("--within-distance", nargs="?", default="")
    query_parser.add_argument("--limit", type=int, default=MAX_FEATURES_DEFAULT)
    query_parser.add_argument("--max-bytes", type=int, default=MAX_BYTES_DEFAULT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = command_inspect(args)
        elif args.command == "analyze":
            result = command_analyze(args)
        elif args.command == "load":
            result = command_load(args)
        elif args.command == "list":
            result = command_list(args)
        elif args.command == "query":
            result = command_query(args)
        else:
            raise GeoLibreError(f"Onbekend commando: {args.command}")
        print(_pretty(result))
        if isinstance(result, dict) and result.get("ok") is False:
            return 2
        return 0
    except GeoLibreError as exc:
        print(_pretty({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - unexpected failures stay visible
        print(_pretty({"ok": False, "error": f"Onverwachte fout: {exc}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
