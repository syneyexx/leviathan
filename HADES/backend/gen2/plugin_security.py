"""Plugin security checklist scanner + content-hash integrity (G7/G9).

Static only — no network. Findings are advisory severity unless marked blocking.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


REQUIRED_MANIFEST_FIELDS = (
    "id",
    "name",
    "version",
    "permissions",
    "runtime_type",
)

RECOMMENDED_MANIFEST_FIELDS = (
    "description",
    "tools",
    "plugin_type",
    "hades_api",
    "entrypoint",
)

HIGH_RISK_PERMISSIONS = frozenset({"network", "subprocess", "filesystem", "env", "secret"})

BLOCKING_FINDING_CODES = frozenset(
    {
        "empty_manifest",
        "missing_required_field",
        "invalid_permissions_type",
        "empty_id",
        "command_shell_metachar",
        "hash_mismatch",
        "archive_unreadable",
    }
)


def _finding(
    code: str,
    *,
    severity: str,
    message: str,
    path: str | None = None,
    blocking: bool | None = None,
) -> dict[str, Any]:
    is_blocking = bool(BLOCKING_FINDING_CODES.__contains__(code) if blocking is None else blocking)
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "path": path,
        "blocking": is_blocking,
    }


def scan_plugin_manifest(manifest: dict[str, Any] | None, *, source: str = "manifest") -> dict[str, Any]:
    """Static security checklist against a hades-plugin.json-shaped dict."""
    findings: list[dict[str, Any]] = []
    data = dict(manifest or {})

    if not data:
        findings.append(
            _finding("empty_manifest", severity="error", message="Manifest is empty", path=source)
        )
        return _scan_result(findings, manifest=data, source=source)

    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in data or data.get(field) in (None, "", []):
            findings.append(
                _finding(
                    "missing_required_field",
                    severity="error",
                    message=f"Required field missing: {field}",
                    path=f"{source}.{field}",
                )
            )

    plugin_id = str(data.get("id") or "").strip()
    if "id" in data and not plugin_id:
        findings.append(_finding("empty_id", severity="error", message="id must be non-empty", path=f"{source}.id"))

    for field in RECOMMENDED_MANIFEST_FIELDS:
        if field not in data or data.get(field) in (None, "", []):
            findings.append(
                _finding(
                    "missing_recommended_field",
                    severity="warning",
                    message=f"Recommended field missing: {field}",
                    path=f"{source}.{field}",
                    blocking=False,
                )
            )

    perms = data.get("permissions")
    if perms is not None and not isinstance(perms, list):
        findings.append(
            _finding(
                "invalid_permissions_type",
                severity="error",
                message="permissions must be a list",
                path=f"{source}.permissions",
            )
        )
    elif isinstance(perms, list):
        risky = [p for p in perms if str(p).lower() in HIGH_RISK_PERMISSIONS]
        if risky and not data.get("autonomous") is False and data.get("autonomous") is True:
            findings.append(
                _finding(
                    "autonomous_high_risk_permissions",
                    severity="warning",
                    message=f"Autonomous plugin requests high-risk permissions: {risky}",
                    path=f"{source}.permissions",
                    blocking=False,
                )
            )
        if "network" in [str(p).lower() for p in perms] and not data.get("network_policy"):
            findings.append(
                _finding(
                    "network_without_policy_note",
                    severity="info",
                    message="Network permission present — ensure policy profile / ask path is configured",
                    path=f"{source}.permissions",
                    blocking=False,
                )
            )

    tools = data.get("tools")
    if isinstance(tools, list):
        for idx, tool in enumerate(tools):
            if not isinstance(tool, dict):
                findings.append(
                    _finding(
                        "invalid_tool_entry",
                        severity="error",
                        message="tools[] entries must be objects",
                        path=f"{source}.tools[{idx}]",
                        blocking=False,
                    )
                )
                continue
            if not tool.get("name"):
                findings.append(
                    _finding(
                        "tool_missing_name",
                        severity="warning",
                        message="Tool missing name",
                        path=f"{source}.tools[{idx}]",
                        blocking=False,
                    )
                )
            cmd = tool.get("command")
            if isinstance(cmd, list):
                joined = " ".join(str(c) for c in cmd)
                if any(ch in joined for ch in ("|", ";", "`", "&&", "||")):
                    findings.append(
                        _finding(
                            "command_shell_metachar",
                            severity="error",
                            message="Tool command appears to embed shell metacharacters",
                            path=f"{source}.tools[{idx}].command",
                        )
                    )
            schema = tool.get("input_schema")
            if schema is not None and not isinstance(schema, dict):
                findings.append(
                    _finding(
                        "invalid_input_schema",
                        severity="warning",
                        message="input_schema should be an object",
                        path=f"{source}.tools[{idx}].input_schema",
                        blocking=False,
                    )
                )
            elif isinstance(schema, dict) and schema.get("additionalProperties") is not False:
                findings.append(
                    _finding(
                        "schema_additional_properties_open",
                        severity="info",
                        message="Prefer additionalProperties=false on tool input_schema",
                        path=f"{source}.tools[{idx}].input_schema",
                        blocking=False,
                    )
                )

    if data.get("runtime_type") in {"node", "python"} and not data.get("entrypoint") and not tools:
        findings.append(
            _finding(
                "no_entrypoint_or_tools",
                severity="warning",
                message="No entrypoint and no tools declared",
                path=source,
                blocking=False,
            )
        )

    return _scan_result(findings, manifest=data, source=source)


def _scan_result(findings: list[dict[str, Any]], *, manifest: dict[str, Any], source: str) -> dict[str, Any]:
    blocking = [f for f in findings if f.get("blocking")]
    return {
        "ok": len(blocking) == 0,
        "source": source,
        "plugin_id": str(manifest.get("id") or "") or None,
        "finding_count": len(findings),
        "blocking_count": len(blocking),
        "findings": findings,
        "checklist_version": "plugin_security_checklist_v1",
        "network_required": False,
        "note": "Static checklist only — not a substitute for runtime permission enforcement.",
    }


def scan_plugin_path(path: str | Path) -> dict[str, Any]:
    """Load hades-plugin.json from a directory or .HadesPlugin zip and scan."""
    target = Path(path)
    if not target.exists():
        return _scan_result(
            [_finding("path_missing", severity="error", message=f"Path not found: {target}", path=str(target))],
            manifest={},
            source=str(target),
        )
    try:
        manifest, content_hash = load_manifest_and_hash(target)
    except Exception as exc:
        return _scan_result(
            [
                _finding(
                    "archive_unreadable",
                    severity="error",
                    message=f"Failed to read plugin: {exc}",
                    path=str(target),
                )
            ],
            manifest={},
            source=str(target),
        )
    result = scan_plugin_manifest(manifest, source=str(target))
    result["content_hash"] = content_hash
    return result


def compute_content_hash(material: bytes | str) -> str:
    if isinstance(material, str):
        material = material.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def hash_plugin_files(files: dict[str, bytes]) -> str:
    """Deterministic hash over sorted relative paths + contents."""
    h = hashlib.sha256()
    for name in sorted(files.keys()):
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(files[name])
        h.update(b"\0")
    return h.hexdigest()


def load_manifest_and_hash(path: Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    files: dict[str, bytes] = {}
    if path.is_dir():
        manifest_path = path / "hades-plugin.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("hades-plugin.json missing")
        for child in sorted(path.rglob("*")):
            if child.is_file() and child.name != ".DS_Store":
                rel = child.relative_to(path).as_posix()
                files[rel] = child.read_bytes()
        manifest = json.loads(files.get("hades-plugin.json", b"{}"))
        return manifest, hash_plugin_files(files)
    if path.suffix.lower() in {".hadesplugin", ".zip"} or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                files[info.filename] = zf.read(info)
        raw = files.get("hades-plugin.json") or files.get("manifest.json")
        if not raw:
            raise FileNotFoundError("hades-plugin.json missing in archive")
        manifest = json.loads(raw.decode("utf-8"))
        return manifest, hash_plugin_files(files)
    # Single JSON manifest file
    raw = path.read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    return manifest, compute_content_hash(raw)


def verify_plugin_integrity(
    *,
    expected_hash: str,
    path: str | Path | None = None,
    files: dict[str, bytes] | None = None,
    actual_hash: str | None = None,
) -> dict[str, Any]:
    """Verify content hash matches expected. Fail closed on mismatch."""
    expected = (expected_hash or "").strip().lower()
    if not expected:
        return {
            "ok": False,
            "verified": False,
            "reason": "expected_hash_required",
            "expected_hash": None,
            "actual_hash": None,
        }
    if actual_hash is None:
        if files is not None:
            actual_hash = hash_plugin_files(files)
        elif path is not None:
            _manifest, actual_hash = load_manifest_and_hash(Path(path))
        else:
            return {
                "ok": False,
                "verified": False,
                "reason": "path_or_files_or_actual_hash_required",
                "expected_hash": expected,
                "actual_hash": None,
            }
    actual = (actual_hash or "").strip().lower()
    match = actual == expected
    return {
        "ok": match,
        "verified": match,
        "reason": "match" if match else "hash_mismatch",
        "expected_hash": expected,
        "actual_hash": actual,
        "algorithm": "sha256",
    }
