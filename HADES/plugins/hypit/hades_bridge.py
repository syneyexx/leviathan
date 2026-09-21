#!/usr/bin/env python3
"""Non-interactive HADES bridge for hypit-ai/hypit.

Knowledge tools (skills, catalog, SVML inspect) work from packaged files without
Node. CLI tools invoke the real `hypit` executable (PATH, packed source, or
`.hades-vendor` npm install of @hypit/hypit). prepare installs that executable.
Internet is optional: missing CLI stays a visible failure, not a fake Ready.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
VENDOR_DIR = ROOT / ".hades-vendor"
HYPIT_NPM_PACKAGE = "@hypit/hypit"
HYPIT_PIN = "0.1.9"
MIN_NODE = (22, 15, 0)
SOURCE_SUFFIXES = {".svml", ".svs", ".svrun"}
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".hades-vendor",
}


def emit(payload: dict[str, Any], *, exit_code: int | None = None) -> int:
    ok = bool(payload.get("ok"))
    if exit_code is None:
        exit_code = 0 if ok else 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".exe") or shutil.which(name + ".cmd")


def _parse_semver(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def node_binary() -> dict[str, Any]:
    path = which("node")
    if not path:
        return {"ok": False, "error": "node_missing", "hint": "Install Node.js 22.15+ (HADES uses Node 22)."}
    try:
        proc = subprocess.run(
            [path, "-p", "process.versions.node"],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "path": path, "error": f"node_probe_failed:{exc}"}
    version = (proc.stdout or proc.stderr or "").strip()
    parsed = _parse_semver(version)
    meets = bool(parsed and parsed >= MIN_NODE)
    payload: dict[str, Any] = {
        "ok": proc.returncode == 0 and bool(version),
        "path": path,
        "version": version or None,
        "meets_engine": meets,
        "required": ">=22.15.0",
    }
    if proc.returncode != 0:
        payload["ok"] = False
        payload["error"] = (proc.stderr or proc.stdout or "node_probe_failed").strip()
    elif not version:
        payload["ok"] = False
        payload["error"] = "empty_node_version"
    elif not meets:
        payload["warning"] = "hypit_engine_wants_node_22_15_or_newer"
    return payload


def npm_binary() -> str | None:
    return which("npm")


def hypit_launcher() -> dict[str, Any]:
    env_root = str(os.environ.get("HYPIT_DISTRIBUTION_ROOT") or "").strip()
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root) / "bin" / "hypit.mjs")
    candidates.extend(
        [
            ROOT / "bin" / "hypit.mjs",
            VENDOR_DIR / "node_modules" / "@hypit" / "hypit" / "bin" / "hypit.mjs",
            ROOT / "node_modules" / "@hypit" / "hypit" / "bin" / "hypit.mjs",
        ]
    )
    for launcher in candidates:
        if launcher.is_file():
            distribution = launcher.parent.parent
            package_json = distribution / "package.json"
            version = None
            if package_json.is_file():
                try:
                    version = json.loads(package_json.read_text(encoding="utf-8")).get("version")
                except (OSError, json.JSONDecodeError):
                    version = None
            return {
                "ok": True,
                "kind": "mjs",
                "launcher": str(launcher),
                "distribution": str(distribution),
                "version": version,
            }
    path = which("hypit")
    if path:
        return {"ok": True, "kind": "path", "launcher": path, "distribution": None, "version": None}
    return {
        "ok": False,
        "error": "hypit_cli_missing",
        "hint": "Run the prepare tool to install @hypit/hypit, or pack the GitHub repo so bin/hypit.mjs is present.",
    }


def _argv_for_hypit(launcher: dict[str, Any], args: list[str], node: dict[str, Any]) -> list[str]:
    if launcher.get("kind") == "path":
        return [str(launcher["launcher"]), *args]
    node_path = node.get("path")
    if not node_path:
        raise RuntimeError("node_missing")
    return [str(node_path), str(launcher["launcher"]), *args]


def run_hypit(
    args: list[str],
    *,
    workspace: str | None = None,
    timeout: int = 90,
    json_mode: bool = True,
) -> dict[str, Any]:
    node = node_binary()
    launcher = hypit_launcher()
    if not launcher.get("ok"):
        return {"ok": False, **launcher, "args": args}
    if launcher.get("kind") != "path" and not node.get("ok"):
        return {"ok": False, "error": node.get("error") or "node_missing", "node": node, "args": args}

    argv = list(args)
    if json_mode and "--json" not in argv:
        argv.append("--json")
    if "--no-color" not in argv:
        argv.append("--no-color")
    if workspace and "--workspace" not in argv:
        argv.extend(["--workspace", workspace])

    command = _argv_for_hypit(launcher, argv, node)
    env = os.environ.copy()
    distribution = launcher.get("distribution")
    if distribution:
        env.setdefault("HYPIT_DISTRIBUTION_ROOT", str(distribution))
    env.setdefault("HYPIT_CLI_LAUNCHER", str(launcher.get("launcher") or ""))
    cwd = Path(workspace).expanduser().resolve() if workspace else Path.cwd()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd if cwd.is_dir() else ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "hypit_timeout",
            "command": command,
            "timeout_seconds": timeout,
        }
    except OSError as exc:
        return {"ok": False, "error": f"hypit_spawn_failed:{exc}", "command": command}

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    payload: dict[str, Any] = {
        "exit_code": proc.returncode,
        "command": command,
        "distribution": launcher.get("distribution"),
        "launcher": launcher.get("launcher"),
    }
    text = stdout.strip()
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            payload.update(parsed)
            if parsed.get("ok") is False:
                payload["ok"] = False
                payload["error"] = payload.get("error") or (parsed.get("error") or parsed)
                if isinstance(payload["error"], dict):
                    payload["error"] = payload["error"].get("message") or json.dumps(payload["error"])
            else:
                payload["ok"] = proc.returncode == 0
            if stderr.strip():
                payload["stderr"] = stderr[-4000:]
            if payload.get("ok"):
                return payload
            payload.setdefault("error", stderr.strip() or "hypit_failed")
            return payload

    ok = proc.returncode == 0 and bool(text)
    payload["ok"] = ok
    payload["stdout"] = stdout[-8000:]
    if stderr.strip():
        payload["stderr"] = stderr[-4000:]
    if not ok:
        payload["error"] = (stderr.strip() or text or "hypit_empty_output")[:2000]
    return payload


def skill_root() -> Path:
    return ROOT / "skills" / "hypit"


def count_skills() -> int:
    root = skill_root()
    if not root.is_dir():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".md", ".svml", ".svs", ".svrun", ".yaml", ".yml"})


def doctor() -> dict[str, Any]:
    node = node_binary()
    launcher = hypit_launcher()
    skills = count_skills()
    fixture = ROOT / "fixtures" / "chat.svml"
    skill_ok = skills > 0 and (skill_root() / "SKILL.md").is_file()
    cli_probe: dict[str, Any] | None = None
    cli_ready = False
    if launcher.get("ok") and node.get("ok"):
        cli_probe = run_hypit(["version"], timeout=20)
        cli_ready = bool(cli_probe.get("ok"))
    payload: dict[str, Any] = {
        "ok": skill_ok,
        "plugin": "hypit",
        "source": "https://github.com/hypit-ai/hypit",
        "npm_package": HYPIT_NPM_PACKAGE,
        "pinned_version": HYPIT_PIN,
        "python": sys.executable,
        "platform": sys.platform,
        "cwd": str(Path.cwd()),
        "plugin_root": str(ROOT),
        "node": node,
        "npm": npm_binary(),
        "cli": launcher,
        "cli_ready": cli_ready,
        "cli_probe": cli_probe,
        "skills": {"present": skill_ok, "file_count": skills, "path": str(skill_root())},
        "fixture": {"present": fixture.is_file(), "path": str(fixture)},
        "notes": [
            "Skill/inspect tools work from packaged files without Node.",
            "CLI tools need a working hypit executable: run prepare (npm @hypit/hypit) so version succeeds.",
            "A packed Git tree with only bin/hypit.mjs is not enough until Node dependencies exist.",
            "Hypit generation/build may need model credentials (HypiHub or your own provider). Missing credentials are reported by hypit doctor, not faked.",
        ],
    }
    if not skill_ok:
        payload["error"] = "hypit_skill_missing"
        payload["hint"] = "Pack from github.com/hypit-ai/hypit or keep plugins/hypit/skills/hypit in the marketplace folder."
    elif not cli_ready:
        payload["next"] = "prepare"
        payload["cli_error"] = (cli_probe or launcher).get("error") or launcher.get("error")
    return payload


def prepare(*, pin: str = HYPIT_PIN, timeout: int = 110) -> dict[str, Any]:
    existing = hypit_launcher()
    node = node_binary()
    if existing.get("ok") and node.get("ok"):
        probed = run_hypit(["version"], json_mode=True, timeout=30)
        if probed.get("ok"):
            return {
                "ok": True,
                "already_prepared": True,
                "cli": existing,
                "node": node,
                "version": probed.get("version") or probed.get("stdout"),
            }

    npm = npm_binary()
    if not npm:
        return {"ok": False, "error": "npm_missing", "hint": "Install Node.js/npm, then rerun prepare."}
    if not node.get("ok"):
        return {"ok": False, "error": node.get("error") or "node_missing", "node": node}

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    spec = pin.strip() or HYPIT_PIN
    package = {
        "name": "hades-hypit-vendor",
        "private": True,
        "version": "0.1.0",
        "dependencies": {HYPIT_NPM_PACKAGE: spec},
    }
    (VENDOR_DIR / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    env = os.environ.copy()
    env["PUPPETEER_SKIP_DOWNLOAD"] = "1"
    env["PUPPETEER_SKIP_CHROMIUM_DOWNLOAD"] = "1"
    env["NPM_CONFIG_AUDIT"] = "false"
    env["NPM_CONFIG_FUND"] = "false"
    try:
        proc = subprocess.run(
            [npm, "install", "--no-fund", "--no-audit"],
            cwd=str(VENDOR_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "npm_install_timeout",
            "timeout_seconds": timeout,
            "hint": "Increase Plugins invoke timeout and rerun prepare. Network is required for the first install.",
        }
    except OSError as exc:
        return {"ok": False, "error": f"npm_spawn_failed:{exc}"}

    install_log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-4000:]
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": "npm_install_failed",
            "exit_code": proc.returncode,
            "log": install_log,
            "hint": "HADES is offline-first: prepare needs network once to fetch @hypit/hypit from npm.",
        }

    launcher = hypit_launcher()
    if not launcher.get("ok"):
        return {
            "ok": False,
            "error": "hypit_missing_after_npm_install",
            "log": install_log,
            "cli": launcher,
        }
    probed = run_hypit(["version", "--json"], json_mode=False, timeout=40)
    if not probed.get("ok"):
        return {
            "ok": False,
            "error": "hypit_version_failed_after_install",
            "install_log": install_log,
            "probe": probed,
        }
    return {
        "ok": True,
        "already_prepared": False,
        "cli": launcher,
        "node": node,
        "version": probed.get("version") or probed.get("stdout"),
        "npm_spec": f"{HYPIT_NPM_PACKAGE}@{spec}",
        "vendor": str(VENDOR_DIR),
    }


def list_examples(*, limit: int = 50) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        rel = path.relative_to(ROOT).as_posix()
        rows.append({"path": rel, "bytes": path.stat().st_size, "kind": path.suffix.lower().lstrip(".")})
        if len(rows) >= limit:
            break
    payload: dict[str, Any] = {"ok": bool(rows), "count": len(rows), "examples": rows}
    if not rows:
        payload["error"] = "no_svml_examples"
        payload["hint"] = "Pack the hypit GitHub repo or keep plugins/hypit/fixtures/*.svml."
    return payload


def inspect_source(path: str, *, max_chars: int = 8000) -> dict[str, Any]:
    raw = str(path or "").strip()
    if not raw or "\x00" in raw:
        return {"ok": False, "error": "path_required"}
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        for base in (Path.cwd(), ROOT):
            probe = (base / candidate).resolve()
            if probe.is_file():
                candidate = probe
                break
        else:
            candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.is_file():
        return {"ok": False, "error": "source_not_found", "path": str(candidate)}
    suffix = candidate.suffix.lower()
    if suffix not in SOURCE_SUFFIXES | {".md", ".json", ".ts"}:
        return {"ok": False, "error": "unsupported_source_suffix", "suffix": suffix}

    text = candidate.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return {"ok": False, "error": "empty_source", "path": str(candidate)}

    pi = re.search(r"<\?svml\s+using=\"([^\"]+)\"\s*\?>", text)
    tags = sorted({match.group(1) for match in re.finditer(r"<([A-Za-z][\w:-]*)", text)})
    imports = re.findall(r"<import\b([^>]*)/?>", text, flags=re.I)
    texts = re.findall(r"\b(?:text|title)=\"([^\"]+)\"", text)
    kind = {".svml": "author", ".svs": "recipe", ".svrun": "run"}.get(suffix, suffix.lstrip("."))
    payload: dict[str, Any] = {
        "ok": True,
        "path": str(candidate),
        "kind": kind,
        "bytes": len(text.encode("utf-8", errors="replace")),
        "using": pi.group(1) if pi else None,
        "tag_count": len(tags),
        "tags": tags[:80],
        "imports": [item.strip() for item in imports[:40]],
        "sample_text": texts[:20],
        "truncated": len(text) > max_chars,
        "preview": text[:max_chars],
        "compiled": False,
        "note": "Structural read only. Use check/plan after prepare to compile with the hypit executable.",
    }
    if suffix in SOURCE_SUFFIXES and not pi:
        payload["warning"] = "missing_svml_processing_instruction"
    return payload


def hypit_help(topic: str = "") -> dict[str, Any]:
    args = ["help"]
    if topic.strip():
        args.append(topic.strip())
    return run_hypit(args, json_mode=False, timeout=30)


def hypit_version(*, check: bool = False) -> dict[str, Any]:
    args = ["version", "--json"]
    if check:
        args.append("--check")
    return run_hypit(args, json_mode=False, timeout=25 if not check else 40)


def hypit_paths(workspace: str) -> dict[str, Any]:
    return run_hypit(["paths"], workspace=workspace or None, timeout=40)


def hypit_check(source: str, workspace: str) -> dict[str, Any]:
    if not str(source or "").strip():
        return {"ok": False, "error": "source_required"}
    return run_hypit(["check", source], workspace=workspace or None, timeout=90)


def hypit_plan(source: str, workspace: str) -> dict[str, Any]:
    if not str(source or "").strip():
        return {"ok": False, "error": "source_required"}
    return run_hypit(["plan", source], workspace=workspace or None, timeout=90)


def hypit_runtime_init(workspace: str) -> dict[str, Any]:
    ws = str(workspace or "").strip() or str(Path.cwd())
    Path(ws).mkdir(parents=True, exist_ok=True)
    pkg = Path(ws) / "package.json"
    if not pkg.is_file():
        pkg.write_text(json.dumps({"name": "hades-hypit-project", "private": True}, indent=2) + "\n", encoding="utf-8")
    return run_hypit(["runtime", "init"], workspace=ws, timeout=60)


def hypit_doctor_runtime(workspace: str) -> dict[str, Any]:
    return run_hypit(["doctor"], workspace=workspace or None, timeout=60)


def hypit_media_probe(path: str) -> dict[str, Any]:
    if not str(path or "").strip():
        return {"ok": False, "error": "path_required"}
    return run_hypit(["media", "probe", path], json_mode=True, timeout=90)


def hypit_media_cut(path: str, start: str, end: str, to: str) -> dict[str, Any]:
    if not str(path or "").strip() or not str(to or "").strip():
        return {"ok": False, "error": "path_and_to_required"}
    return run_hypit(
        ["media", "cut", path, "--start", str(start), "--end", str(end), "--to", to],
        json_mode=True,
        timeout=90,
    )


def hypit_media_fetch(url: str, to: str) -> dict[str, Any]:
    if not str(url or "").strip().startswith(("http://", "https://")):
        return {"ok": False, "error": "http_url_required"}
    if not str(to or "").strip():
        return {"ok": False, "error": "to_required"}
    return run_hypit(["media", "fetch", url, "--to", to], json_mode=True, timeout=110)


def hypit_build(source: str, workspace: str, follow: bool = False) -> dict[str, Any]:
    if not str(source or "").strip():
        return {"ok": False, "error": "source_required"}
    args = ["build", source]
    if follow:
        args.append("--follow")
    return run_hypit(args, workspace=workspace or None, timeout=110)


def hypit_status(build_id: str, workspace: str) -> dict[str, Any]:
    if not str(build_id or "").strip():
        return {"ok": False, "error": "build_id_required"}
    return run_hypit(["status", build_id], workspace=workspace or None, timeout=40)


def hypit_logs(build_id: str, workspace: str, lines: int = 80) -> dict[str, Any]:
    if not str(build_id or "").strip():
        return {"ok": False, "error": "build_id_required"}
    return run_hypit(["logs", build_id, "--lines", str(int(lines))], workspace=workspace or None, timeout=40)


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES Hypit bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor")

    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("--pin", default=HYPIT_PIN)

    p_ex = sub.add_parser("list_examples")
    p_ex.add_argument("--limit", type=int, default=50)

    p_ins = sub.add_parser("inspect_source")
    p_ins.add_argument("--path", required=True)
    p_ins.add_argument("--max-chars", type=int, default=8000)

    p_help = sub.add_parser("help")
    p_help.add_argument("--topic", default="")

    p_ver = sub.add_parser("version")
    p_ver.add_argument("--check", action="store_true")

    p_paths = sub.add_parser("paths")
    p_paths.add_argument("--workspace", default=".")

    p_check = sub.add_parser("check")
    p_check.add_argument("--source", required=True)
    p_check.add_argument("--workspace", default=".")

    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--source", required=True)
    p_plan.add_argument("--workspace", default=".")

    p_rt = sub.add_parser("runtime_init")
    p_rt.add_argument("--workspace", default=".")

    p_doc = sub.add_parser("doctor_runtime")
    p_doc.add_argument("--workspace", default=".")

    p_probe = sub.add_parser("media_probe")
    p_probe.add_argument("--path", required=True)

    p_cut = sub.add_parser("media_cut")
    p_cut.add_argument("--path", required=True)
    p_cut.add_argument("--start", default="0")
    p_cut.add_argument("--end", default="3")
    p_cut.add_argument("--to", required=True)

    p_fetch = sub.add_parser("media_fetch")
    p_fetch.add_argument("--url", required=True)
    p_fetch.add_argument("--to", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--source", required=True)
    p_build.add_argument("--workspace", default=".")
    p_build.add_argument("--follow", default="false")

    p_st = sub.add_parser("status")
    p_st.add_argument("--build-id", required=True)
    p_st.add_argument("--workspace", default=".")

    p_logs = sub.add_parser("logs")
    p_logs.add_argument("--build-id", required=True)
    p_logs.add_argument("--workspace", default=".")
    p_logs.add_argument("--lines", type=int, default=80)

    args = parser.parse_args()
    cmd = args.cmd
    if cmd == "doctor":
        return emit(doctor())
    if cmd == "prepare":
        return emit(prepare(pin=args.pin))
    if cmd == "list_examples":
        return emit(list_examples(limit=args.limit))
    if cmd == "inspect_source":
        return emit(inspect_source(args.path, max_chars=args.max_chars))
    if cmd == "help":
        return emit(hypit_help(args.topic))
    if cmd == "version":
        return emit(hypit_version(check=bool(args.check)))
    if cmd == "paths":
        return emit(hypit_paths(args.workspace))
    if cmd == "check":
        return emit(hypit_check(args.source, args.workspace))
    if cmd == "plan":
        return emit(hypit_plan(args.source, args.workspace))
    if cmd == "runtime_init":
        return emit(hypit_runtime_init(args.workspace))
    if cmd == "doctor_runtime":
        return emit(hypit_doctor_runtime(args.workspace))
    if cmd == "media_probe":
        return emit(hypit_media_probe(args.path))
    if cmd == "media_cut":
        return emit(hypit_media_cut(args.path, args.start, args.end, args.to))
    if cmd == "media_fetch":
        return emit(hypit_media_fetch(args.url, args.to))
    if cmd == "build":
        follow = str(args.follow).strip().lower() in {"1", "true", "yes", "on"}
        return emit(hypit_build(args.source, args.workspace, follow=follow))
    if cmd == "status":
        return emit(hypit_status(args.build_id, args.workspace))
    if cmd == "logs":
        return emit(hypit_logs(args.build_id, args.workspace, args.lines))
    return emit({"ok": False, "error": f"unknown_command:{cmd}"})


if __name__ == "__main__":
    raise SystemExit(main())
