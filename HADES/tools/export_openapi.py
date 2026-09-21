#!/usr/bin/env python3
"""Export HADES OpenAPI schema and generate focused TypeScript contracts.

Reproducible (no network, no extra npm deps):

  python3 tools/export_openapi.py
  python3 tools/export_openapi.py --check   # CI drift detection

Writes:
  contracts/openapi.json
  lib/generated/api-contracts.ts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OPENAPI_PATH = ROOT / "contracts" / "openapi.json"
TS_PATH = ROOT / "lib" / "generated" / "api-contracts.ts"

# Important schemas that must stay in the committed OpenAPI subset / TS file.
FOCUS_SCHEMAS = (
    "BrainGraphResponse",
    "BrainCountsModel",
    "ModelsGatewayResponse",
    "ModelsListResponse",
    "ApiErrorBody",
    "PageMeta",
    "CodingJobsListResponse",
    "HostCapabilityStatus",
    "BrainNodeInput",
    "BrainNodeUpdate",
    "BrainLinkInput",
    "BrainLayoutPositionInput",
    "BrainViewportInput",
    "ModelProfileInput",
)


def _load_app():
    sys.path.insert(0, str(BACKEND))
    import main  # noqa: WPS433

    return main.app


def _json_schema_to_ts(name: str, schema: dict, defs: dict) -> str:
    """Minimal OpenAPI schema → TypeScript type (objects, enums, nullability)."""

    def resolve(node: dict) -> dict:
        if "$ref" in node:
            ref = node["$ref"].split("/")[-1]
            return defs.get(ref, {"type": "unknown"})
        if "anyOf" in node or "oneOf" in node:
            variants = node.get("anyOf") or node.get("oneOf") or []
            non_null = [v for v in variants if v.get("type") != "null"]
            if len(non_null) == 1 and len(variants) == 2:
                base = dict(resolve(non_null[0]))
                base["_nullable"] = True
                return base
        return node

    def ts_type(node: dict) -> str:
        node = resolve(node)
        if node.get("enum"):
            return " | ".join(json.dumps(v) for v in node["enum"])
        t = node.get("type")
        nullable = node.get("_nullable") or node.get("nullable")
        if isinstance(t, list):
            parts = [x for x in t if x != "null"]
            nullable = nullable or ("null" in t)
            t = parts[0] if parts else "null"
        if t == "string":
            out = "string"
        elif t == "integer" or t == "number":
            out = "number"
        elif t == "boolean":
            out = "boolean"
        elif t == "array":
            items = node.get("items") or {}
            out = f"Array<{ts_type(items)}>"
        elif t == "object" or "properties" in node or node.get("additionalProperties") is not None:
            props = node.get("properties") or {}
            required = set(node.get("required") or [])
            if not props and node.get("additionalProperties") is not False:
                out = "Record<string, unknown>"
            else:
                lines = []
                for key, prop in props.items():
                    optional = "?" if key not in required else ""
                    lines.append(f"  {key}{optional}: {ts_type(prop)};")
                out = "{\n" + "\n".join(lines) + "\n}"
        else:
            out = "unknown"
        if nullable:
            out = f"{out} | null"
        return out

    body = ts_type(schema)
    if body.startswith("{"):
        return f"export type {name} = {body};\n"
    return f"export type {name} = {body};\n"


def _schema_from_models() -> dict[str, dict]:
    """Collect focused Pydantic models even when not yet attached as response_model."""
    sys.path.insert(0, str(BACKEND))
    from api_contracts import ApiErrorBody, CodingJobsListResponse, HostCapabilityStatus, PageMeta
    from brain_routes import (
        BrainCountsModel,
        BrainGraphResponse,
        BrainLayoutPositionInput,
        BrainLinkInput,
        BrainNodeInput,
        BrainNodeUpdate,
        BrainViewportInput,
    )
    from models_routes import ModelProfileInput, ModelsGatewayResponse, ModelsListResponse

    models = [
        ApiErrorBody,
        PageMeta,
        CodingJobsListResponse,
        HostCapabilityStatus,
        BrainCountsModel,
        BrainGraphResponse,
        BrainLayoutPositionInput,
        BrainLinkInput,
        BrainNodeInput,
        BrainNodeUpdate,
        BrainViewportInput,
        ModelProfileInput,
        ModelsGatewayResponse,
        ModelsListResponse,
    ]
    out: dict[str, dict] = {}
    for model in models:
        schema = model.model_json_schema(mode="serialization")
        # Flatten $defs into top-level selected map.
        defs = schema.pop("$defs", {}) or schema.pop("definitions", {}) or {}
        for def_name, def_schema in defs.items():
            out.setdefault(def_name, def_schema)
        out[model.__name__] = schema
    return out


def build_openapi_document(app) -> dict:
    raw = app.openapi()
    components = dict(raw.get("components", {}).get("schemas", {}))
    components.update(_schema_from_models())
    selected: dict[str, dict] = {}

    def add(name: str) -> None:
        if name in selected or name not in components:
            return
        schema = components[name]
        selected[name] = schema
        blob = json.dumps(schema)
        for other in list(components):
            if f'"#/components/schemas/{other}"' in blob or f"/schemas/{other}" in blob or f'"#/$defs/{other}"' in blob:
                add(other)

    for name in FOCUS_SCHEMAS:
        add(name)

    paths = {}
    for path, methods in (raw.get("paths") or {}).items():
        keep = False
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            tags = op.get("tags") or []
            if any(t in {"brain", "models"} for t in tags):
                keep = True
            text = json.dumps(op)
            if any(name in text for name in FOCUS_SCHEMAS):
                keep = True
        if keep or path.startswith("/api/brain") or path.startswith("/api/models"):
            paths[path] = methods

    return {
        "openapi": raw.get("openapi", "3.1.0"),
        "info": {
            "title": raw.get("info", {}).get("title", "HADES"),
            "version": raw.get("info", {}).get("version", "0"),
            "description": "Focused HADES transport contracts (work package L). Regenerated by tools/export_openapi.py.",
        },
        "paths": dict(sorted(paths.items())),
        "components": {"schemas": dict(sorted(selected.items()))},
    }


def render_ts(doc: dict) -> str:
    schemas = doc.get("components", {}).get("schemas", {})
    parts = [
        "/**",
        " * AUTO-GENERATED by tools/export_openapi.py — do not edit by hand.",
        " * Source of truth: FastAPI / Pydantic models → contracts/openapi.json",
        " */",
        "",
        "export type IsoDateTimeString = string;",
        "",
    ]
    for name in FOCUS_SCHEMAS:
        if name not in schemas:
            continue
        parts.append(_json_schema_to_ts(name, schemas[name], schemas))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def write_outputs(doc: dict) -> None:
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    TS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    TS_PATH.write_text(render_ts(doc), encoding="utf-8")


def check_drift(doc: dict) -> int:
    expected_openapi = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    expected_ts = render_ts(doc)
    errors: list[str] = []
    if not OPENAPI_PATH.exists() or OPENAPI_PATH.read_text(encoding="utf-8") != expected_openapi:
        errors.append(f"drift: {OPENAPI_PATH.relative_to(ROOT)} (run: python3 tools/export_openapi.py)")
    if not TS_PATH.exists() or TS_PATH.read_text(encoding="utf-8") != expected_ts:
        errors.append(f"drift: {TS_PATH.relative_to(ROOT)} (run: python3 tools/export_openapi.py)")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("OpenAPI/TS contracts are up to date.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if committed contracts drift from the live app")
    args = parser.parse_args()
    app = _load_app()
    doc = build_openapi_document(app)
    if args.check:
        return check_drift(doc)
    write_outputs(doc)
    print(f"Wrote {OPENAPI_PATH.relative_to(ROOT)}")
    print(f"Wrote {TS_PATH.relative_to(ROOT)}")
    print(f"Schemas: {len(doc['components']['schemas'])}  Paths: {len(doc['paths'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
