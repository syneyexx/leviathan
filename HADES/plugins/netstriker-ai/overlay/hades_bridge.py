#!/usr/bin/env python3
"""HADES bridge for TechXplorevo/Netstriker.ai.

Exposes offline remediation / DPDP helpers plus an authorized local-only Nmap
scan path. Public-internet scanning stays gated: this bridge only scans
loopback/private targets (same safety rule as upstream is_safe_auto_target).
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
if BACKEND.is_dir() and str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IP_RE = re.compile(
    r"^(25[0-5]|2[0-4]\d|[01]?\d?\d)(\.(25[0-5]|2[0-4]\d|[01]?\d?\d)){3}$"
)
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)


def emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def resolve_target(raw: str) -> tuple[str, str]:
    if not raw or not isinstance(raw, str):
        raise ValueError("Target is required")
    s = raw.strip()
    if "://" in s:
        parsed = urlparse(s)
        s = parsed.netloc or parsed.path
    s = s.split("/")[0].split(":")[0].strip().lower()
    if not s:
        raise ValueError("Could not parse target")
    if IP_RE.match(s):
        return s, s
    if not DOMAIN_RE.match(s):
        raise ValueError("Invalid IP address or domain name")
    try:
        ip = socket.gethostbyname(s)
    except socket.gaierror as exc:
        raise ValueError("Could not resolve this domain") from exc
    return s, ip


def is_safe_auto_target(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_loopback or addr.is_private or addr.is_link_local
    except ValueError:
        return False


def doctor() -> dict[str, Any]:
    try:
        import cli_bridge

        payload = cli_bridge.doctor(
            ["nmap", "pydantic", "email_validator"],
            ["python", "python3", "nmap"],
        )
    except Exception as exc:  # noqa: BLE001 - doctor must still report layout honesty
        payload = {"cli_bridge_error": str(exc)}
    layout = {
        "backend": BACKEND.is_dir(),
        "scanner": (BACKEND / "scanner.py").is_file(),
        "remediation": (BACKEND / "remediation.py").is_file(),
        "compliance": (BACKEND / "compliance.py").is_file(),
        "server": (BACKEND / "server.py").is_file(),
    }
    payload["layout"] = layout
    layout_ok = all(bool(v) for v in layout.values())
    # Layout presence must not overwrite module/binary honesty from cli_bridge.doctor.
    modules_ok = bool(payload.get("ok", True)) and "cli_bridge_error" not in payload
    payload["ok"] = layout_ok and modules_ok
    if not layout_ok:
        missing = [name for name, present in layout.items() if not present]
        payload["error"] = "missing_required_layout:" + ",".join(missing)
    elif not modules_ok and not payload.get("error"):
        payload["error"] = payload.get("cli_bridge_error") or "cli_bridge_modules_unavailable"
    payload["notes"] = [
        "Remediation and DPDP tools work offline from upstream guides.",
        "scan_local requires the nmap binary + python-nmap and only allows private/loopback targets.",
        "Public-target scanning needs domain ownership verification in the full NetStrikerAI UI/API.",
    ]
    return payload


def list_remediation(limit: int = 200) -> dict[str, Any]:
    from remediation import REMEDIATION_GUIDE

    rows = []
    for port, (label, steps) in sorted(REMEDIATION_GUIDE.items()):
        rows.append({"port": port, "label": label, "steps": steps})
        if len(rows) >= limit:
            break
    return {
        "ok": len(rows) > 0,
        "count": len(rows),
        "remediations": rows,
        "error": None if rows else "empty_remediation_guide",
    }


def get_remediation(port: int, service: str = "") -> dict[str, Any]:
    from remediation import get_remediation as upstream_get

    label, steps = upstream_get(int(port), service or "")
    ok = bool(steps)
    return {
        "ok": ok,
        "port": int(port),
        "service": service or "",
        "label": label,
        "steps": steps,
        "error": None if ok else "empty_remediation",
    }


def dpdp_map(risk: str = "medium") -> dict[str, Any]:
    from compliance import DPDP_MAPPING, add_dpdp_section

    risk_label = (risk or "medium").strip().lower()
    if risk_label not in DPDP_MAPPING:
        raise ValueError("risk must be one of: high, medium, low")
    section = add_dpdp_section(risk_label)
    return {
        "ok": bool(section),
        "risk": risk_label,
        "dpdp": section,
        "error": None if section else "empty_dpdp_section",
    }


def cmd_resolve(target: str) -> dict[str, Any]:
    hostname, ip = resolve_target(target)
    return {
        "ok": True,
        "target": target,
        "hostname": hostname,
        "ip": ip,
        "safe_auto_target": is_safe_auto_target(ip),
    }


def _finding_to_dict(finding: Any) -> dict[str, Any]:
    vulns = []
    for vuln in getattr(finding, "vulnerabilities", []) or []:
        vulns.append(
            {
                "id": getattr(vuln, "id", ""),
                "title": getattr(vuln, "title", ""),
                "severity": getattr(vuln, "severity", ""),
                "source": getattr(vuln, "source", ""),
                "detail": getattr(vuln, "detail", ""),
            }
        )
    return {
        "port": getattr(finding, "port", None),
        "protocol": getattr(finding, "protocol", ""),
        "state": getattr(finding, "state", ""),
        "service": getattr(finding, "service", ""),
        "product": getattr(finding, "product", ""),
        "version": getattr(finding, "version", ""),
        "risk_level": getattr(finding, "risk_level", ""),
        "risk_note": getattr(finding, "risk_note", ""),
        "remediation": getattr(finding, "remediation", ""),
        "vulnerabilities": vulns,
    }


def scan_local(target: str, authorized: str | bool) -> dict[str, Any]:
    if not truthy(authorized):
        raise ValueError(
            "scan_local requires authorized=true for targets you own or control "
            "(private/loopback only in this bridge)."
        )

    hostname, ip = resolve_target(target)
    if not is_safe_auto_target(ip):
        raise ValueError(
            f"Refusing public target {hostname}/{ip}. "
            "This HADES bridge only scans loopback/private addresses; "
            "use NetStrikerAI domain verification for public hosts."
        )
    if not shutil.which("nmap") and not shutil.which("nmap.exe"):
        raise RuntimeError("nmap binary not found on PATH")

    from compliance import add_dpdp_section
    from scanner import calculate_risk_score, run_scan

    findings, raw = run_scan(ip)
    score, label = calculate_risk_score(findings)
    return {
        "ok": True,
        "hostname": hostname,
        "ip": ip,
        "risk_score": score,
        "risk_label": label,
        "dpdp": add_dpdp_section(label),
        "open_ports": [_finding_to_dict(item) for item in findings],
        "open_port_count": len(findings),
        "raw_csv_preview": (raw or "")[:2000],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES NetStrikerAI bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor")

    p_list = sub.add_parser("list_remediation")
    p_list.add_argument("--limit", type=int, default=200)

    p_get = sub.add_parser("get_remediation")
    p_get.add_argument("--port", type=int, required=True)
    p_get.add_argument("--service", default="")

    p_dpdp = sub.add_parser("dpdp_map")
    p_dpdp.add_argument("--risk", default="medium")

    p_resolve = sub.add_parser("resolve_target")
    p_resolve.add_argument("--target", required=True)

    p_scan = sub.add_parser("scan_local")
    p_scan.add_argument("--target", required=True)
    p_scan.add_argument("--authorized", required=True)

    args = parser.parse_args()
    try:
        if args.cmd == "doctor":
            payload = doctor()
            return emit(payload, exit_code=0 if payload.get("ok", True) else 2)
        elif args.cmd == "list_remediation":
            payload = list_remediation(args.limit)
        elif args.cmd == "get_remediation":
            payload = get_remediation(args.port, args.service)
        elif args.cmd == "dpdp_map":
            payload = dpdp_map(args.risk)
        elif args.cmd == "resolve_target":
            payload = cmd_resolve(args.target)
        else:
            payload = scan_local(args.target, args.authorized)
    except Exception as exc:  # noqa: BLE001 - surface structured tool failures
        return emit({"ok": False, "error": str(exc)}, exit_code=1)
    ok = payload.get("ok", True) is not False
    return emit(payload, exit_code=0 if ok else 2)


if __name__ == "__main__":
    raise SystemExit(main())
