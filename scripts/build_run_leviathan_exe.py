#!/usr/bin/env python3
"""Build the LEVIATHAN backend host.

On Windows this produces run_leviathan.exe and copies it to dist/run_leviathan.exe
at the install root. On other operating systems the canonical Windows executable
cannot be produced; the script fails loudly after the portable host-core tests
unless --allow-host-binary is passed to build the current OS binary for inspection.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "Data" / "launcher"
DIST = ROOT / "dist"


def run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-host-binary",
        action="store_true",
        help="On non-Windows hosts, build the native binary for this OS and still exit 0.",
    )
    args = parser.parse_args()
    npm = shutil.which("npm")
    cargo = shutil.which("cargo")
    if not npm or not cargo:
        print("ERROR: npm and cargo are required to build run_leviathan.", file=sys.stderr)
        return 2
    run([npm, "ci"], LAUNCHER)
    run([npm, "test"], LAUNCHER)
    run([npm, "run", "typecheck"], LAUNCHER)
    run([cargo, "test", "--manifest-path", str(LAUNCHER / "host-core" / "Cargo.toml")], ROOT)
    if platform.system() != "Windows" and not args.allow_host_binary:
        print(
            "ERROR: run_leviathan.exe was NOT produced. "
            "The canonical executable is a Windows Tauri build (WebView2). "
            "This host is not Windows. Compatibility launcher remains run_leviathan.bat.",
            file=sys.stderr,
        )
        return 3
    run([npm, "run", "tauri", "--", "build"], LAUNCHER)
    suffix = ".exe" if platform.system() == "Windows" else ""
    candidates = list((LAUNCHER / "src-tauri" / "target" / "release").glob(f"run_leviathan{suffix}"))
    bundle = LAUNCHER / "src-tauri" / "target" / "release" / "bundle"
    candidates.extend(bundle.rglob(f"run_leviathan{suffix}"))
    if not candidates:
        print("ERROR: Tauri build finished without a run_leviathan binary.", file=sys.stderr)
        return 4
    DIST.mkdir(parents=True, exist_ok=True)
    dest = DIST / f"run_leviathan{suffix}"
    shutil.copy2(candidates[0], dest)
    print(f"Published {dest}")
    if platform.system() != "Windows":
        print("NOTE: this is not run_leviathan.exe. Windows WebView2 builds produce the canonical name.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: build command failed with exit {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode or 1)
