#!/usr/bin/env python3
"""Frontier hardening baseline / after measurement (machine-readable).

Records measurable repository state without inventing PASS for unavailable hosts.
Does not mutate baseline numbers after the fact — write once with --label before|after.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 120) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(BACKEND)},
        )
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-4000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
            "duration_ms": _ms(started),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "returncode": None,
            "error": f"timeout after {timeout}s",
            "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
            "duration_ms": _ms(started),
        }
    except FileNotFoundError as exc:
        return {"cmd": cmd, "returncode": None, "error": str(exc), "duration_ms": _ms(started)}


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "UNKNOWN"


def _loc_scan() -> dict[str, Any]:
    def collect(patterns: list[str], exclude: tuple[str, ...]) -> list[tuple[int, str]]:
        files: list[Path] = []
        for pat in patterns:
            files.extend(ROOT.rglob(pat))
        rows: list[tuple[int, str]] = []
        for path in files:
            text = str(path)
            if any(part in text for part in exclude):
                continue
            try:
                n = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            rows.append((n, str(path.relative_to(ROOT))))
        rows.sort(reverse=True)
        return rows

    py = collect(["backend/**/*.py"], ("venv", ".venv", "__pycache__", "node_modules"))
    # Path.rglob with ** may not work on all Path impls — fallback
    if not py:
        py_files = [
            p
            for p in (ROOT / "backend").rglob("*.py")
            if ".venv" not in str(p) and "__pycache__" not in str(p)
        ]
        py = []
        for path in py_files:
            try:
                n = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            py.append((n, str(path.relative_to(ROOT))))
        py.sort(reverse=True)

    ts_files = [
        p
        for p in list(ROOT.rglob("*.ts")) + list(ROOT.rglob("*.tsx"))
        if "node_modules" not in str(p) and "dist" not in str(p) and ".next" not in str(p)
    ]
    ts: list[tuple[int, str]] = []
    for path in ts_files:
        try:
            n = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        ts.append((n, str(path.relative_to(ROOT))))
    ts.sort(reverse=True)

    return {
        "python_loc": sum(n for n, _ in py),
        "python_files": len(py),
        "typescript_loc": sum(n for n, _ in ts),
        "typescript_files": len(ts),
        "largest_python_files": [{"path": p, "loc": n} for n, p in py[:20]],
        "largest_typescript_files": [{"path": p, "loc": n} for n, p in ts[:15]],
    }


def _count_symbols() -> dict[str, Any]:
    """AST-based counts of high-risk sites (approximate, honest)."""
    subprocess_sites = 0
    tool_entrypoints = 0
    policy_sites = 0
    completion_writers = 0
    patterns_tool = re.compile(r"\b(invoke|run_isolated|_run_command|process_run)\b")
    patterns_policy = re.compile(
        r"\b(enforce_tool_invocation_policies|enforce_plugin_permissions|require_policy)\b"
    )
    patterns_complete = re.compile(
        r"\b(decide_work_task_completion|status\s*=\s*[\"']completed[\"']|set_task_status)\b"
    )
    for path in (ROOT / "backend").rglob("*.py"):
        if ".venv" in str(path) or "__pycache__" in str(path) or "/tests/" in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "subprocess." in text or "Popen(" in text:
            subprocess_sites += text.count("subprocess.") + text.count("Popen(")
        tool_entrypoints += len(patterns_tool.findall(text))
        policy_sites += len(patterns_policy.findall(text))
        completion_writers += len(patterns_complete.findall(text))
    return {
        "subprocess_execution_sites_approx": subprocess_sites,
        "tool_execution_symbol_refs_approx": tool_entrypoints,
        "policy_enforcement_symbol_refs_approx": policy_sites,
        "completion_terminal_state_writers_approx": completion_writers,
        "note": "Approximate symbol/string counts — not unique call-graph edges.",
    }


def _count_unittest_cases(pattern: str = "test_*.py") -> dict[str, Any]:
    import unittest

    started = time.perf_counter()
    loader = unittest.defaultTestLoader
    suite = loader.discover(str(BACKEND / "tests"), pattern=pattern)
    return {"count": suite.countTestCases(), "load_ms": _ms(started), "pattern": pattern}


def _count_eval_cases() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from evals.reasoning_eval import SCENARIOS as reasoning  # type: ignore

        out["reasoning_core"] = len(reasoning)
    except Exception as exc:
        out["reasoning_core"] = {"error": str(exc)}
    try:
        from gen2.eval_lab import RED_TEAM_SCENARIOS, DOMAIN_QUALITY_SCENARIOS  # type: ignore

        out["red_team_v1"] = len(RED_TEAM_SCENARIOS)
        out["domain_quality_v1"] = len(DOMAIN_QUALITY_SCENARIOS)
    except Exception as exc:
        out["red_team_v1"] = {"error": str(exc)}
    try:
        from evals.quality_suite import QUALITY_SCENARIOS, HARD_BENCHMARK_SCENARIOS  # type: ignore

        by_layer: Counter[str] = Counter()
        for row in QUALITY_SCENARIOS:
            layer = row[3] if len(row) > 3 else "unknown"
            by_layer[str(layer)] += 1
        out["quality_suite_total"] = len(QUALITY_SCENARIOS)
        out["quality_suite_by_layer"] = dict(by_layer)
        out["hard_benchmark"] = len(HARD_BENCHMARK_SCENARIOS)
    except Exception as exc:
        out["quality_suite"] = {"error": str(exc)}
    try:
        from evals.generalization_dataset import DATASET as gen  # type: ignore

        out["generalization_v1"] = len(gen)
    except Exception:
        try:
            from evals import generalization_dataset as gd

            cases = getattr(gd, "CASES", None) or getattr(gd, "SCENARIOS", None) or getattr(gd, "HOLDINGS", None)
            if cases is None:
                # Inspect module for list-like corpora
                names = [n for n in dir(gd) if "CASE" in n.upper() or "SCENARIO" in n.upper() or "HOLD" in n.upper()]
                out["generalization_v1"] = {"symbols": names}
            else:
                out["generalization_v1"] = len(cases)
        except Exception as exc:
            out["generalization_v1"] = {"error": str(exc)}
    try:
        from evals.agent_tasks import AGENT_TASKS  # type: ignore

        out["agent_tasks_v1"] = len(AGENT_TASKS)
    except Exception:
        try:
            import evals.agent_tasks as at

            for name in ("AGENT_TASKS", "TASKS", "CASES", "SCENARIOS", "HOLDOUT"):
                if hasattr(at, name):
                    out["agent_tasks_v1"] = len(getattr(at, name))
                    break
            else:
                out["agent_tasks_v1"] = {"symbols": [n for n in dir(at) if n.isupper()]}
        except Exception as exc:
            out["agent_tasks_v1"] = {"error": str(exc)}
    # Release-gated deterministic
    try:
        r = _run(
            [sys.executable, "-m", "evals.gen2_release_gate", "--json"],
            cwd=BACKEND,
            timeout=180,
        )
        out["gen2_release_gate_run"] = {
            "returncode": r.get("returncode"),
            "duration_ms": r.get("duration_ms"),
        }
        # Parse JSON object from stdout
        text = r.get("stdout_tail") or ""
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(text[start : end + 1])
            out["gen2_release_gate"] = {
                "passed": payload.get("passed"),
                "suites": payload.get("suites") or payload.get("results"),
                "summary": payload.get("summary"),
            }
    except Exception as exc:
        out["gen2_release_gate"] = {"error": str(exc)}
    return out


def _frontend_status() -> dict[str, Any]:
    typecheck = _run(["npm", "run", "typecheck"], timeout=180)
    # Honest: lint currently aliases typecheck — record package.json truth
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = pkg.get("scripts") or {}
    return {
        "typecheck": {
            "returncode": typecheck.get("returncode"),
            "duration_ms": typecheck.get("duration_ms"),
            "status": "PASS" if typecheck.get("returncode") == 0 else "FAIL",
        },
        "lint_script": scripts.get("lint"),
        "typecheck_script": scripts.get("typecheck"),
        "lint_equals_typecheck": scripts.get("lint") == scripts.get("typecheck"),
        "lint_is_eslint": "eslint" in str(scripts.get("lint") or "").lower(),
        "note": (
            "npm run lint uses ESLint"
            if "eslint" in str(scripts.get("lint") or "").lower()
            else "npm run lint is currently identical to typecheck (tsc --noEmit), not ESLint."
        ),
    }


def _portfolio_demos() -> dict[str, Any]:
    r = _run([sys.executable, "tools/run_portfolio_demos.py"], timeout=180)
    tail = (r.get("stdout_tail") or "") + "\n" + (r.get("stderr_tail") or "")
    passed = None
    m = re.search(r"(\d+)\s*/\s*(\d+)", tail)
    if m:
        passed = {"passed": int(m.group(1)), "total": int(m.group(2))}
    return {
        "returncode": r.get("returncode"),
        "duration_ms": r.get("duration_ms"),
        "counts": passed,
        "status": "PASS" if r.get("returncode") == 0 else "FAIL",
        "stdout_tail": (r.get("stdout_tail") or "")[-1500:],
    }


def _lm_studio_probe() -> dict[str, Any]:
    try:
        import httpx

        base = os.environ.get("HADES_LM_STUDIO_URL") or "http://127.0.0.1:1234/v1"
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{base.rstrip('/')}/models")
            return {
                "status": "PASS" if resp.status_code == 200 else "UNAVAILABLE",
                "endpoint": base,
                "http_status": resp.status_code,
            }
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "reason": str(exc),
            "endpoint": os.environ.get("HADES_LM_STUDIO_URL") or "http://127.0.0.1:1234/v1",
        }


def _import_timings() -> dict[str, float]:
    mods = [
        "run_lifecycle",
        "policy_enforcement",
        "execution_isolation",
        "artifacts",
        "approvals",
    ]
    out: dict[str, float] = {}
    for name in mods:
        t0 = time.perf_counter()
        try:
            __import__(name)
            out[name] = _ms(t0)
        except Exception as exc:
            out[name] = -1.0
            out[f"{name}_error"] = str(exc)  # type: ignore[assignment]
    return out


def _deps() -> dict[str, Any]:
    req = (BACKEND / "requirements.txt").read_text(encoding="utf-8").strip().splitlines()
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    return {
        "python_requirements": [line.strip() for line in req if line.strip() and not line.startswith("#")],
        "node_dependencies": sorted((pkg.get("dependencies") or {}).keys()),
        "node_devDependencies": sorted((pkg.get("devDependencies") or {}).keys()),
    }


def measure(label: str) -> dict[str, Any]:
    py = sys.version.split()[0]
    try:
        node = subprocess.check_output(["node", "--version"], text=True).strip()
    except Exception:
        node = "UNKNOWN"
    try:
        npm = subprocess.check_output(["npm", "--version"], text=True).strip()
    except Exception:
        npm = "UNKNOWN"

    results: dict[str, Any] = {
        "kind": "hades_frontier_hardening_baseline",
        "label": label,
        "honesty": {
            "do_not_mutate_historical_baselines": True,
            "unknown_stays_unknown": True,
            "live_lm_studio_not_required_for_software_gate": True,
        },
        "fingerprint": {
            "git_commit_sha": _git_sha(),
            "python_version": py,
            "node_version": node,
            "npm_version": npm,
            "os": platform.platform(),
            "system": platform.system(),
            "machine": platform.machine(),
            "measured_at_unix": int(time.time()),
        },
        "repository_size": _loc_scan(),
        "risk_symbol_counts": _count_symbols(),
        "imports_ms": _import_timings(),
        "dependencies": _deps(),
        "live_provider": {"lm_studio": _lm_studio_probe()},
        "windows_secured_isolation": {
            "status": "UNVERIFIED_ON_HOST" if platform.system() != "Windows" else "UNMEASURED",
            "note": "Job Objects alone are not full FS/network isolation; claim only with operational host evidence.",
        },
    }

    results["backend_tests"] = _count_unittest_cases("test_*.py")
    results["gen2_tests"] = _count_unittest_cases("test_gen2*.py")
    results["frontend_tests_approx"] = {
        "note": "Approximate count of test()/it() calls in tests/*.test.mjs",
        "count": sum(
            len(re.findall(r"\b(?:test|it)\s*\(", p.read_text(encoding="utf-8", errors="ignore")))
            for p in (ROOT / "tests").glob("*.test.mjs")
        ),
    }
    results["evals"] = _count_eval_cases()
    results["frontend"] = _frontend_status()
    # Production build is expensive; measure presence of script + optional quick probe
    results["production_build"] = {
        "status": "UNMEASURED",
        "note": "Run npm run build separately for full release evidence; omitted from cheap baseline by default.",
    }
    results["portfolio_demos"] = _portfolio_demos()
    return results


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    def dig(d: dict, *keys: str) -> Any:
        cur: Any = d
        for k in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur

    return {
        "kind": "hades_frontier_hardening_comparison",
        "before_sha": dig(before, "fingerprint", "git_commit_sha"),
        "after_sha": dig(after, "fingerprint", "git_commit_sha"),
        "backend_test_count_delta": (dig(after, "backend_tests", "count") or 0)
        - (dig(before, "backend_tests", "count") or 0),
        "gen2_test_count_delta": (dig(after, "gen2_tests", "count") or 0)
        - (dig(before, "gen2_tests", "count") or 0),
        "python_loc_delta": (dig(after, "repository_size", "python_loc") or 0)
        - (dig(before, "repository_size", "python_loc") or 0),
        "lint_is_eslint_before": dig(before, "frontend", "lint_is_eslint"),
        "lint_is_eslint_after": dig(after, "frontend", "lint_is_eslint"),
        "portfolio_demos_before": dig(before, "portfolio_demos"),
        "portfolio_demos_after": dig(after, "portfolio_demos"),
        "lm_studio_before": dig(before, "live_provider", "lm_studio", "status"),
        "lm_studio_after": dig(after, "live_provider", "lm_studio", "status"),
        "note": "Deltas are descriptive; do not treat growth alone as quality.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", choices=["before", "after"], default="before")
    parser.add_argument("--compare", action="store_true", help="Write comparison if both baselines exist")
    parser.add_argument("--include-build", action="store_true")
    args = parser.parse_args()

    out_dir = ROOT / "artifacts" / "baselines"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = measure(args.label)
    if args.include_build:
        build = _run(["npm", "run", "build"], timeout=300)
        results["production_build"] = {
            "status": "PASS" if build.get("returncode") == 0 else "FAIL",
            "returncode": build.get("returncode"),
            "duration_ms": build.get("duration_ms"),
        }

    out_path = out_dir / f"frontier_hardening_{args.label}.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(out_path), "label": args.label, "sha": results["fingerprint"]["git_commit_sha"]}, indent=2))

    if args.compare or args.label == "after":
        before_path = out_dir / "frontier_hardening_before.json"
        after_path = out_dir / "frontier_hardening_after.json"
        if before_path.exists() and (args.label == "after" or after_path.exists()):
            before = json.loads(before_path.read_text(encoding="utf-8"))
            after = results if args.label == "after" else json.loads(after_path.read_text(encoding="utf-8"))
            cmp = compare(before, after)
            cmp_path = out_dir / "frontier_hardening_comparison.json"
            cmp_path.write_text(json.dumps(cmp, indent=2), encoding="utf-8")
            print(json.dumps({"wrote_comparison": str(cmp_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
