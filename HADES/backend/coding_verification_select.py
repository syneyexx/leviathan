"""Automatic verification suite selection from repository evidence.

Extends the existing allowlisted subprocess model — never shell=True,
never model-generated arbitrary commands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Suites must exist in build_agent.ALLOWED_TEST_COMMANDS (extended there).
AUTO_SUITE_PRIORITY = (
    "npm_test",
    "pytest",
    "unittest",
    "go_test",
    "cargo_test",
    "ctest",
)


def _read_package_scripts(root: Path) -> dict[str, str]:
    pkg = root / "package.json"
    if not pkg.is_file():
        return {}
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return {}
    return {str(k): str(v) for k, v in scripts.items() if isinstance(k, str)}


def select_verification_suite(
    root: Path | str,
    *,
    requested: str | None = None,
    changed_files: list[str] | None = None,
    languages: list[str] | None = None,
    build_systems: list[str] | None = None,
) -> dict[str, Any]:
    """Choose a safe allowlisted test suite and optional targeted args."""
    source = Path(root).expanduser().resolve()
    req = (requested or "auto").strip().lower() or "auto"
    changed = [c.replace("\\", "/") for c in (changed_files or [])]
    langs = set(languages or [])
    builds = set(build_systems or [])

    # Detect markers when not provided.
    if not langs or not builds:
        try:
            from repo_intelligence import detect_languages_and_build

            detected = detect_languages_and_build(source)
            langs = langs or set(detected.get("languages") or [])
            builds = builds or set(detected.get("build_systems") or [])
        except Exception:
            pass

    if req != "auto":
        return {
            "suite": req,
            "test_args": [],
            "reason": "explicit_request",
            "auto": False,
            "candidates": [req],
        }

    scripts = _read_package_scripts(source)
    candidates: list[str] = []
    reasons: list[str] = []

    has_ts = bool(langs & {"typescript", "javascript"}) or any(
        c.endswith((".ts", ".tsx", ".js", ".jsx", ".css", ".scss")) for c in changed
    )
    has_py = "python" in langs or any(c.endswith(".py") for c in changed)
    has_go = "go" in langs or (source / "go.mod").exists()
    has_rust = "rust" in langs or (source / "Cargo.toml").exists()
    has_cmake = "cmake" in builds or (source / "CMakeLists.txt").exists()

    # Prefer targeted checks from impacted files.
    if has_ts and ("npm" in builds or scripts or (source / "package.json").exists()):
        candidates.append("npm_test")
        reasons.append("node_package_present")
    if has_py:
        if "pytest" in builds or (source / "pytest.ini").exists() or (
            source / "pyproject.toml"
        ).exists():
            # Prefer pytest when configured.
            candidates.append("pytest")
            reasons.append("pytest_project")
        candidates.append("unittest")
        reasons.append("python_sources")
    if has_go:
        candidates.append("go_test")
        reasons.append("go_mod")
    if has_rust:
        candidates.append("cargo_test")
        reasons.append("cargo_toml")
    if has_cmake:
        candidates.append("ctest")
        reasons.append("cmake")

    # Deduplicate preserving order.
    ordered: list[str] = []
    for suite in candidates:
        if suite not in ordered:
            ordered.append(suite)
    if not ordered:
        ordered = ["unittest"]
        reasons.append("default_unittest_fallback")

    suite = ordered[0]
    test_args: list[str] = []

    # Targeted args from changed files (path-contained by run_tests).
    if suite in {"unittest", "pytest"}:
        py_tests = [
            c
            for c in changed
            if c.endswith(".py") and ("test" in Path(c).name.lower() or c.startswith("tests/"))
        ]
        if py_tests:
            test_args = py_tests[:8]
    elif suite == "npm_test":
        # Keep args empty — npm test script is allowlisted; targeting via extra paths
        # is only safe for explicit relative test files when provided by caller later.
        pass

    return {
        "suite": suite,
        "test_args": test_args,
        "reason": ",".join(dict.fromkeys(reasons)) or "auto",
        "auto": True,
        "candidates": ordered,
        "package_scripts": sorted(scripts.keys())[:20],
        "languages": sorted(langs),
        "build_systems": sorted(builds),
    }
