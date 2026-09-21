#!/usr/bin/env python3
"""Canonical cross-platform HADES release verification entrypoint.

Windows operators should prefer VERIFY_HADES.bat (which calls this script via
the prepared venv). Cursor/CI/Linux use this module directly:

  python verify_hades.py
  python verify_hades.py --quick
  python verify_hades.py --host
  python verify_hades.py --host --lm-studio --browser --voice --sandbox

Deterministic release gates never fail because optional hardware/providers are
missing. Host probes are recorded separately as UNVERIFIED_ON_HOST / DEGRADED.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def _resolve_cmd(name: str) -> str:
    """Resolve a CLI on PATH, including Windows .cmd/.exe shims."""
    resolved = shutil.which(name) or shutil.which(f"{name}.cmd") or shutil.which(f"{name}.exe")
    return resolved or name


def _run(label: str, argv: list[str], *, cwd: Path | None = None) -> None:
    print(f"\n=== {label} ===", flush=True)
    resolved = list(argv)
    if resolved:
        resolved[0] = _resolve_cmd(resolved[0])
    print("+", " ".join(resolved), flush=True)
    completed = subprocess.run(resolved, cwd=str(cwd or ROOT))
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _native_build_and_ctest() -> None:
    """Compile/test native runtime and install binary used by backend tests."""
    build_dir = ROOT / "native" / "build-release-gate"
    _run("Native CMake configure", ["cmake", "-S", str(ROOT / "native"), "-B", str(build_dir)])
    build_cmd = ["cmake", "--build", str(build_dir)]
    if os.name == "nt":
        build_cmd.extend(["--config", "Release"])
    _run("Native build", build_cmd)
    ctest_cmd = ["ctest", "--test-dir", str(build_dir), "--output-on-failure"]
    if os.name == "nt":
        ctest_cmd.extend(["--build-config", "Release"])
    _run("Native CTest", ctest_cmd)
    install_cmd = ["cmake", "--install", str(build_dir), "--prefix", str(ROOT)]
    if os.name == "nt":
        install_cmd.extend(["--config", "Release"])
    _run("Native install runtime binary", install_cmd)


def _python() -> str:
    venv = ROOT / "backend" / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    if venv.exists():
        return str(venv)
    return sys.executable


def _host_row(
    capability: str,
    *,
    implemented: bool,
    available_on_host: bool,
    simulated: bool,
    operationally_tested: bool,
    quality_evaluated: bool,
    evidence: Any = None,
    failure_reason: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    from host_probes import host_row

    return host_row(
        capability,
        implemented=implemented,
        available_on_host=available_on_host,
        simulated=simulated,
        operationally_tested=operationally_tested,
        quality_evaluated=quality_evaluated,
        evidence=evidence,
        failure_reason=failure_reason,
        status=status,
    )


def run_host_probes(args: argparse.Namespace) -> dict[str, Any]:
    """Optional host integration matrix. Never mutates release-gate pass/fail."""
    sys.path.insert(0, str(ROOT / "backend"))
    rows: list[dict[str, Any]] = []
    want_all = bool(args.host) and not any([args.lm_studio, args.browser, args.voice, args.sandbox])

    if args.host or args.sandbox or want_all:
        from gen2.sandbox import detect_host_sandbox_capabilities, spawn_in_job_object
        from gen2.sandbox_job import run_tier2_selftest

        caps = detect_host_sandbox_capabilities()
        tier2 = run_tier2_selftest()
        rows.append(
            _host_row(
                "sandbox_tier0_1",
                implemented=True,
                available_on_host=True,
                simulated=False,
                operationally_tested=True,
                quality_evaluated=False,
                evidence={"available_tiers": caps.get("available_tiers")},
                status="PASS",
            )
        )
        rows.append(
            _host_row(
                "sandbox_tier2_job_object",
                implemented=True,
                available_on_host=bool(caps.get("job_objects")),
                simulated=False,
                operationally_tested=bool(tier2.get("operationally_tested")),
                quality_evaluated=False,
                evidence=tier2,
                failure_reason=tier2.get("failure_reason"),
                status=str(tier2.get("status") or "UNVERIFIED_ON_HOST"),
            )
        )
        # API-present-but-enforcement-failed must not count as ready.
        if caps.get("job_objects") and not tier2.get("operationally_tested"):
            rows[-1]["status"] = "UNVERIFIED_ON_HOST"
            rows[-1]["failure_reason"] = rows[-1].get("failure_reason") or "api_present_enforcement_unproven"

    if args.host or args.lm_studio or want_all:
        from host_probes import probe_lm_studio

        rows.append(probe_lm_studio())

    if args.host or args.browser or want_all:
        from host_probes import probe_browser

        rows.append(probe_browser(repo_root=ROOT))

    if args.host or args.voice or want_all:
        from host_probes import probe_voice

        rows.append(probe_voice())

    # Compute fabric honesty always recorded when --host.
    if args.host or want_all:
        from gen2.compute_fabric import distributed_fabric_status

        dist = distributed_fabric_status()
        rows.append(
            _host_row(
                "compute_fabric",
                implemented=True,
                available_on_host=True,
                simulated=False,
                operationally_tested=bool(dist.get("implemented_local")),
                quality_evaluated=False,
                evidence=dist,
                status="PASS" if dist.get("mode") == "local_only" else "FAIL",
            )
        )
        rows.append(
            _host_row(
                "compute_fabric_distributed",
                implemented=False,
                available_on_host=False,
                simulated=False,
                operationally_tested=False,
                quality_evaluated=False,
                evidence=dist,
                failure_reason="remote_dispatch_not_implemented",
                status="UNVERIFIED_ON_HOST",
            )
        )

    matrix = {
        "generated_at": time.time(),
        "platform": os.name,
        "rows": rows,
        "status_vocabulary": [
            "PASS",
            "FAIL",
            "SKIPPED",
            "UNAVAILABLE",
            "UNVERIFIED_ON_HOST",
            "DEGRADED",
            "SIMULATED_ONLY",
        ],
    }
    out = Path(args.host_report) if args.host_report else ROOT / "host_capability_matrix.json"
    out.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    print("\n=== Host capability matrix ===")
    print(json.dumps(matrix, indent=2))
    print(f"\nWrote {out}")
    return matrix


def _probe_lm_studio() -> dict[str, Any]:
    from host_probes import probe_lm_studio

    return probe_lm_studio()


def _probe_browser() -> dict[str, Any]:
    from host_probes import probe_browser

    return probe_browser(repo_root=ROOT)


def _probe_voice() -> dict[str, Any]:
    from host_probes import probe_voice

    return probe_voice()


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES release verification")
    parser.add_argument("--quick", action="store_true", help="Skip production build")
    parser.add_argument("--python-only", action="store_true", help="Only backend unittest suite")
    parser.add_argument("--host", action="store_true", help="Run optional host capability matrix probes")
    parser.add_argument("--lm-studio", action="store_true", help="Probe live LM Studio")
    parser.add_argument("--browser", action="store_true", help="Probe Puppeteer/browser readiness honestly")
    parser.add_argument("--voice", action="store_true", help="Probe voice config/deps/ASR-TTS fixtures (not physical mic PASS alone)")
    parser.add_argument("--sandbox", action="store_true", help="Probe sandbox Tier-2 Job Object selftest")
    parser.add_argument(
        "--host-report",
        default="",
        help="Path for machine-readable host matrix JSON (default: ./host_capability_matrix.json)",
    )
    parser.add_argument(
        "--host-only",
        action="store_true",
        help="Skip deterministic gates; only run selected host probes",
    )
    args = parser.parse_args()
    py = _python()

    def _backend_unittest() -> None:
        # Install Windows-safe TemporaryDirectory before discovery. discover -s tests
        # imports modules as top-level test_*.py and skips tests/__init__.py.
        runner = (
            "import sys; "
            "sys.path.insert(0, 'tests'); "
            "import win_temp_patch; "  # noqa: intentional side-effect install
            "import unittest; "
            "raise SystemExit(unittest.main(module=None, exit=False, "
            "argv=['unittest', 'discover', '-s', 'tests', '-v']).result.wasSuccessful() is False)"
        )
        _run(
            "Backend unit/integration suite (incl. gen2, control, contracts, agents)",
            [py, "-c", runner],
            cwd=ROOT / "backend",
        )

    if not args.host_only:
        if args.python_only:
            _run(
                "Backend unittest suite",
                [
                    py,
                    "-c",
                    "import sys; sys.path.insert(0, 'tests'); import win_temp_patch; "
                    "import unittest; "
                    "raise SystemExit(unittest.main(module=None, exit=False, "
                    "argv=['unittest', 'discover', '-s', 'tests', '-v']).result.wasSuccessful() is False)",
                ],
                cwd=ROOT / "backend",
            )
            print("\n[OK] Python-only verification passed.")
        else:
            _run("TypeScript typecheck", ["npm", "run", "typecheck"])
            _run("ESLint", ["npm", "run", "lint"])
            if not args.quick:
                _run("Production frontend build", ["npm", "run", "build"])

            _run(
                "Canonical frontend release tests",
                ["node", "tools/run_frontend_release_tests.mjs"],
            )

            _native_build_and_ctest()

            _backend_unittest()

            _run(
                "Ruff security-boundary lint",
                [
                    py,
                    "-m",
                    "ruff",
                    "check",
                    "runtime/execution_gateway.py",
                    "runtime/effect_ledger.py",
                    "policy_enforcement.py",
                    "execution_isolation.py",
                    "approvals.py",
                    "artifacts.py",
                    "claim_register.py",
                    "--config",
                    "ruff.toml",
                ],
                cwd=ROOT / "backend",
            )

            _run(
                "Gen2 offline eval release gate",
                [py, "-m", "evals.gen2_release_gate"],
                cwd=ROOT / "backend",
            )

            _run(
                "OpenAPI/TS contract drift check",
                [py, str(ROOT / "tools" / "export_openapi.py"), "--check"],
            )

            # Informational sandbox capability dump (never claims PASS for missing hardware).
            probe = subprocess.run(
                [
                    py,
                    "-c",
                    "from gen2.sandbox import detect_host_sandbox_capabilities; "
                    "import json; print(json.dumps(detect_host_sandbox_capabilities(), indent=2))",
                ],
                cwd=str(ROOT / "backend"),
                capture_output=True,
                text=True,
            )
            print("\n=== Host sandbox capabilities (informational) ===")
            print(probe.stdout or probe.stderr)
            if probe.returncode != 0:
                print("[WARN] Host capability probe failed — reported as UNVERIFIED_ON_HOST, not PASS.")

            print("\n[OK] HADES release verification stages completed.")
            print(
                "Note: physical Windows / live LM Studio / live Puppeteer / live VoiceStudio "
                "are UNVERIFIED unless probed via --host / --lm-studio / --browser / --voice / --sandbox."
            )

    if args.host or args.lm_studio or args.browser or args.voice or args.sandbox or args.host_only:
        run_host_probes(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
