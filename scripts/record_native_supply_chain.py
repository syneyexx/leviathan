#!/usr/bin/env python3
"""Record Cargo supply-chain inventory for leviathan-data-plane (W195).

Writes Data/backend/tests/native_cargo_supply_chain.json with direct-crate
justifications and an honest cargo-audit AVAILABLE/UNAVAILABLE status.
Never records a silent PASS for a missing audit tool.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "Data" / "native"
CRATE = NATIVE / "leviathan_data_plane"
OUT = ROOT / "Data" / "backend" / "tests" / "native_cargo_supply_chain.json"

JUSTIFICATIONS: dict[str, str] = {
    "serde": "Task/receipt/capabilities JSON protocol — derive Serialize/Deserialize only.",
    "serde_json": "Machine handshake and task documents are JSON file I/O.",
    "thiserror": "Typed fail-closed error codes for protocol/path/limit violations.",
    "sha2": "Deterministic content hashing for native receipts (dataset.hash / parquet_hash).",
    "hex": "Encode digests for receipt contentHash fields.",
    "tempfile": "Scratch/temp paths for atomic publish; not a business authority store.",
    "clap": "CLI for --capabilities/--task only; no shell interpolation.",
    "arrow-array": "Parquet batch arrays (W165)",
    "arrow-schema": "Parquet schema (W165)",
    "parquet": "native Parquet scan/validate/hash (W165)",
}

DEV_JUSTIFICATIONS: dict[str, str] = {
    "tempfile": "Unit tests for ops I/O.",
    "serde_json": "Test fixtures for protocol documents.",
    "arrow-array": "Build Parquet fixtures in tests.",
    "arrow-schema": "Test schema construction.",
    "parquet": "Write test Parquet files.",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_direct_deps(cargo_toml: Path) -> tuple[list[str], list[str]]:
    text = cargo_toml.read_text(encoding="utf-8")
    section: str | None = None
    direct: list[str] = []
    dev: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip().strip('"')
        if section == "[dependencies]":
            direct.append(name)
        elif section == "[dev-dependencies]":
            dev.append(name)
    return direct, dev


def _cargo_audit() -> dict[str, Any]:
    cargo = shutil.which("cargo")
    if not cargo:
        return {
            "status": "UNAVAILABLE",
            "detail": "cargo not found on PATH — audit not run; no false PASS.",
        }
    try:
        proc = subprocess.run(
            [cargo, "audit", "--version"],
            cwd=str(NATIVE),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "UNAVAILABLE",
            "detail": f"cargo audit probe failed: {type(exc).__name__}: {exc}",
        }
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:400]
        return {
            "status": "UNAVAILABLE",
            "detail": (
                "cargo-audit subcommand not installed in this environment "
                f"(cargo audit → {err or 'non-zero'}). No false PASS recorded."
            ),
        }
    try:
        audit = subprocess.run(
            [cargo, "audit", "-q"],
            cwd=str(CRATE),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "UNAVAILABLE",
            "detail": f"cargo audit run failed: {type(exc).__name__}: {exc}",
        }
    return {
        "status": "AVAILABLE",
        "exitCode": audit.returncode,
        "stdoutTail": (audit.stdout or "")[-800:],
        "stderrTail": (audit.stderr or "")[-400:],
        "clean": audit.returncode == 0,
    }


def _try_cargo_tree() -> str | None:
    cargo = shutil.which("cargo")
    if not cargo:
        return None
    try:
        proc = subprocess.run(
            [cargo, "tree", "-p", "leviathan_data_plane", "--depth", "1"],
            cwd=str(NATIVE),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "")[:4000]


def main() -> int:
    cargo_toml = CRATE / "Cargo.toml"
    if not cargo_toml.is_file():
        print(f"missing {cargo_toml}", file=sys.stderr)
        return 1
    direct, dev = _parse_direct_deps(cargo_toml)
    tree = _try_cargo_tree()
    payload = {
        "schemaVersion": 1,
        "package": "leviathan_data_plane",
        "workspace": "Data/native",
        "generatedAt": _utcnow(),
        "method": "cargo tree -p leviathan_data_plane" if tree else "Cargo.toml [dependencies] parse",
        "cargoTreeDepth1": tree,
        "cargoAudit": _cargo_audit(),
        "policy": {
            "noUnnecessaryCrates": True,
            "notes": (
                "Direct deps are protocol (serde/clap), hashing (sha2/hex), atomic temp publish "
                "(tempfile), errors (thiserror), and minimal Arrow/Parquet readers "
                "(default-features=false; snap enabled for common Snappy Parquet)."
            ),
        },
        "directDependencies": [
            {"crate": name, "justification": JUSTIFICATIONS.get(name, "see Cargo.toml")}
            for name in direct
        ],
        "devDependencies": [
            {"crate": name, "justification": DEV_JUSTIFICATIONS.get(name, "dev/test only")}
            for name in dev
        ],
        "transitiveHighlights": [
            {
                "crate": "snap",
                "via": "parquet",
                "justification": "Snappy decompression for common Parquet corpora; no extra codec stack enabled.",
            },
            {
                "crate": "arrow-buffer / arrow-data / arrow-ipc / arrow-select",
                "via": "parquet/arrow-array",
                "justification": "Arrow crate graph pulled by parquet arrow feature — kept minimal via default-features=false.",
            },
            {
                "crate": "digest / crypto-common / block-buffer",
                "via": "sha2",
                "justification": "RustCrypto digest stack for SHA-256.",
            },
        ],
        "explicitlyAvoided": [
            "tokio / async runtime — sync CLI only",
            "reqwest / networking — no outbound I/O from native binary",
            "full arrow / parquet default features — compression/IPC stack trimmed",
            "sqlite / sled — no competing domain DB inside native binary",
        ],
        "truth": {
            "auditNotRunAsPass": True,
            "treeCapturedHonestly": True,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "directDeps": len(direct), "cargoAudit": payload["cargoAudit"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
