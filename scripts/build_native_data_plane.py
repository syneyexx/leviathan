#!/usr/bin/env python3
"""Build the Leviathan native data-plane binary and place it under Data/native/bin/."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _data_root() -> Path:
    # scripts/build_native_data_plane.py → repo root; Data/ is sibling of scripts/
    return Path(__file__).resolve().parents[1] / "Data"


def detect_cargo() -> str | None:
    cargo = shutil.which("cargo")
    if cargo:
        return cargo
    # Common rustup locations
    for candidate in (
        Path.home() / ".cargo" / "bin" / "cargo",
        Path("/usr/local/cargo/bin/cargo"),
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def build(release: bool = True, locked: bool = True) -> Path:
    data = _data_root()
    native = data / "native"
    if not (native / "Cargo.toml").is_file():
        raise SystemExit(f"missing native workspace at {native}")

    cargo = detect_cargo()
    if cargo is None:
        raise SystemExit("cargo not found on PATH; install Rust toolchain to build native data-plane")

    argv = [cargo, "build", "--workspace"]
    if release:
        argv.append("--release")
    if locked:
        argv.append("--locked")
    print("+", " ".join(argv), flush=True)
    proc = subprocess.run(argv, cwd=str(native), shell=False, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"cargo build failed with exit {proc.returncode}")

    profile = "release" if release else "debug"
    built = native / "target" / profile / "leviathan-data-plane"
    if not built.is_file():
        raise SystemExit(f"built binary missing: {built}")

    dest_dir = native / "bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "leviathan-data-plane"
    shutil.copy2(built, dest)
    dest.chmod(dest.stat().st_mode | 0o111)
    return dest


def verify_handshake(binary: Path) -> dict:
    proc = subprocess.run(  # noqa: S603
        [str(binary), "--capabilities", "--json"],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        raise SystemExit(f"capabilities handshake failed: {proc.stderr or proc.stdout}")
    doc = json.loads(proc.stdout)
    if int(doc.get("protocolVersion") or 0) != 1:
        raise SystemExit(f"unexpected protocolVersion: {doc.get('protocolVersion')}")
    ops = set(doc.get("operations") or [])
    required = {
        "dataset.validate",
        "dataset.hash",
        "dataset.transform",
        "dataset.split",
        "dataset.export",
        "dataset.dedupe",
    }
    missing = sorted(required - ops)
    if missing:
        raise SystemExit(f"capabilities missing operations: {missing}")
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug", action="store_true", help="build debug profile instead of release")
    parser.add_argument("--unlocked", action="store_true", help="omit --locked")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args(argv)

    dest = build(release=not args.debug, locked=not args.unlocked)
    print(f"installed: {dest}")
    if not args.skip_verify:
        doc = verify_handshake(dest)
        print(json.dumps({"ok": True, "binary": str(dest), "capabilities": doc}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
