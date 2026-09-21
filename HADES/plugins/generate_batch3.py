#!/usr/bin/env python3
"""Generate HADES plugins for the upstream batch requested by Strijder.

Skipped: bikini/exploitarium (exploit PoC archive — not packaged).
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

from generate_catalog import (
    EMPTY,
    ROOT,
    SHARED,
    copy_shared,
    lifecycle_tools,
    packer_git,
    packer_local,
    readme,
    skill_tools,
    write_json,
    write_text,
)


def _caps(
    effects: list[str],
    *,
    side: str = "process",
    cost: str = "cheap",
    latency: str = "fast",
    failures: list[str] | None = None,
) -> dict:
    return {
        "effects": effects,
        "side_effect_class": side,
        "cost_class": cost,
        "latency_class": latency,
        "failure_modes": failures
        or ["dependency", "schema", "timeout"]
        + (["network"] if "network" in effects else [])
        + (["healthcheck"] if "service" in effects else []),
    }


def _finalize_manifest(payload: dict) -> dict:
    """Ensure marketplace / isolation / capability defaults match catalog plugins."""
    effects = list(
        payload.get("capabilities", {}).get("effects")
        or payload.get("permissions")
        or ["subprocess"]
    )
    # Normalize permission names to effect names where needed.
    effect_map = {"filesystem": "read_files"}
    normalized: list[str] = []
    for item in effects:
        mapped = effect_map.get(item, item)
        if mapped == "filesystem":
            normalized.extend(["read_files", "write_files"])
        elif mapped not in normalized:
            normalized.append(mapped)
    if "filesystem" in (payload.get("permissions") or []):
        for name in ("read_files", "write_files"):
            if name not in normalized:
                normalized.append(name)
    payload.setdefault("isolation", "plugin_cwd")
    payload.setdefault("trust_default", "untrusted")
    payload.setdefault(
        "capabilities",
        _caps(
            normalized,
            cost=payload.get("capabilities", {}).get("cost_class", "cheap"),
            latency=payload.get("capabilities", {}).get("latency_class", "fast"),
        ),
    )
    market = {
        "pinned_version": payload.get("version", "0.1.0"),
        "source_url": payload.get("source", ""),
        "signed": False,
    }
    if payload.get("license"):
        market["license"] = payload["license"]
    payload.setdefault("marketplace", market)
    # Attach default capabilities on tools that lack them.
    for tool in payload.get("tools") or []:
        if "capabilities" not in tool:
            tool["capabilities"] = dict(payload["capabilities"])
    return payload


def make_skill_git(
    plugin_id: str,
    name: str,
    source: str,
    description: str,
    category: str,
    labels: list[str],
    *,
    autonomous: bool = True,
    license_id: str | None = None,
    notes: str = "Use list/get/search to load skill content into HADES tool results.",
    packer_extra: str | None = None,
) -> None:
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    copy_shared(overlay, ["skill_bridge.py"])
    copy_shared(folder, ["skill_bridge.py"])
    write_text(overlay / "requirements.txt", "# skill plugin — stdlib only\n")
    write_text(folder / "requirements.txt", "# skill plugin — stdlib only\n")
    tools = skill_tools(name)
    for tool in tools:
        tool["capabilities"] = _caps(["subprocess"])
    payload = _finalize_manifest(
        {
            "format": 1,
            "id": plugin_id,
            "name": name,
            "version": "0.1.0",
            "description": description,
            "runtime_type": "python",
            "entrypoint": "skill_bridge.py",
            "plugin_type": "tool",
            "category": category,
            "labels": labels,
            "permissions": ["subprocess"],
            "autonomous": autonomous,
            "hades_api": ">=0.4.1",
            "source": source,
            "tools": tools,
        }
    )
    if license_id:
        payload["license"] = license_id
        payload["marketplace"]["license"] = license_id
    write_json(folder / "hades-plugin.json", payload)
    write_text(folder / "pack_hadesplugin.py", packer_extra or packer_git(plugin_id, source))
    write_text(folder / "README.md", readme(name, source, [t["name"] for t in tools], notes))


def make_impeccable() -> None:
    # Exclude heavy upstream trees so the .HadesPlugin stays importable.
    packer = '''#!/usr/bin/env python3
"""Pack impeccable as a .HadesPlugin from upstream git + overlay (skills only)."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
from pack_lib import pack_git  # noqa: E402

UPSTREAM = "https://github.com/pbakaus/impeccable"
DEFAULT_REF = "main"
# Keep agent skill trees; drop build/browser/cargo noise.
EXTRA_PARTS = {
    "browser-bundle",
    ".cargo",
    "target",
    "node_modules",
    ".git",
    "dist",
    "build",
    "crates",
    "wasm",
    "fixtures",
    "screenshots",
    "tests",
    "oracle",
}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "dist")
    parser.add_argument("--ref", default=DEFAULT_REF)
    args = parser.parse_args()
    package = pack_git(
        plugin_dir=Path(__file__).resolve().parent,
        out_dir=args.out.resolve(),
        upstream=UPSTREAM,
        ref=args.ref,
        extra_parts=EXTRA_PARTS,
    )
    print(f"Wrote {package} ({package.stat().st_size / (1024 * 1024):.2f} MiB)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''
    make_skill_git(
        "impeccable",
        "Impeccable",
        "https://github.com/pbakaus/impeccable",
        "Design-language skills that make HADES better at UI/UX craft (critique, layout, color, motion).",
        "Developer",
        ["design", "ui", "skills", "impeccable"],
        license_id="Apache-2.0",
        notes=(
            "Autonomous skill lookup for design guidance. Prefer get_skill on "
            "`.agent/skills/impeccable/SKILL.md` then specific reference/*.md files."
        ),
        packer_extra=packer,
    )


def make_gsap_skills() -> None:
    make_skill_git(
        "gsap-skills",
        "GSAP Skills",
        "https://github.com/greensock/gsap-skills",
        "Official GSAP animation skills for agents: timelines, ScrollTrigger, React, plugins, performance.",
        "Developer",
        ["gsap", "animation", "skills", "frontend"],
        license_id="MIT",
        notes="Load GSAP skill docs into chat/work so HADES can write correct GreenSock animation code.",
    )


def make_design_dna() -> None:
    # Refresh existing scaffold to current catalog defaults.
    make_skill_git(
        "design-dna",
        "Design DNA",
        "https://github.com/zanwei/design-dna",
        "Extract/apply visual design identity as structured JSON guidance for HADES UI work.",
        "Developer",
        ["design", "skills", "ui", "brand"],
        license_id="MIT",
        notes="Use list/get/search over SKILL.md and references when shaping HADES UI or brand systems.",
    )


def make_patchright() -> None:
    plugin_id = "patchright"
    folder = ROOT / plugin_id
    copy_shared(folder, ["cli_bridge.py"])
    write_text(
        folder / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        """HADES bridge for Patchright (stealth Playwright drop-in)."""
        from __future__ import annotations

        import argparse
        import json
        import subprocess
        import sys
        from pathlib import Path


        def doctor() -> dict:
            import cli_bridge

            payload = cli_bridge.doctor(["patchright"], ["patchright"])
            payload["notes"] = [
                "Run install_browsers once after dependency install.",
                "Use fetch/screenshot for research pages that block vanilla Playwright.",
                "This is browser automation — not an exploit framework.",
            ]
            return payload


        def install_browsers() -> dict:
            process = subprocess.run(
                [sys.executable, "-m", "patchright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=1800,
                shell=False,
            )
            return {
                "command": [sys.executable, "-m", "patchright", "install", "chromium"],
                "exit_code": process.returncode,
                "stdout": (process.stdout or "")[-40_000:],
                "stderr": (process.stderr or "")[-40_000:],
            }


        def _launch():
            from patchright.sync_api import sync_playwright

            return sync_playwright()


        def fetch(url: str, max_chars: int) -> dict:
            with _launch() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    title = page.title()
                    text = page.inner_text("body") or ""
                    return {
                        "url": url,
                        "title": title,
                        "chars": len(text),
                        "truncated": len(text) > max_chars,
                        "text": text[:max_chars],
                    }
                finally:
                    browser.close()


        def screenshot(url: str, output: str) -> dict:
            out = Path(output)
            out.parent.mkdir(parents=True, exist_ok=True)
            with _launch() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 720})
                    page.goto(url, wait_until="networkidle", timeout=60_000)
                    page.screenshot(path=str(out), full_page=True)
                    return {"url": url, "output": str(out.resolve()), "bytes": out.stat().st_size}
                finally:
                    browser.close()


        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            sub.add_parser("install_browsers")
            f = sub.add_parser("fetch")
            f.add_argument("--url", required=True)
            f.add_argument("--max-chars", type=int, default=20000)
            s = sub.add_parser("screenshot")
            s.add_argument("--url", required=True)
            s.add_argument("--output", default="screenshot.png")
            args = parser.parse_args()
            if args.cmd == "doctor":
                payload = doctor()
            elif args.cmd == "install_browsers":
                payload = install_browsers()
            elif args.cmd == "fetch":
                payload = fetch(args.url, args.max_chars)
            else:
                payload = screenshot(args.url, args.output)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(folder / "requirements.txt", "patchright>=1.50.0\n")
    effects = ["network", "read_files", "write_files", "subprocess"]
    tools = [
        {
            "name": "doctor",
            "action": "doctor",
            "command": ["{python}", "hades_bridge.py", "doctor"],
            "description": "Check whether Patchright is importable in the plugin venv.",
            "input_schema": EMPTY,
            "capabilities": _caps(effects, cost="moderate", latency="normal"),
        },
        {
            "name": "install_browsers",
            "action": "install",
            "command": ["{python}", "hades_bridge.py", "install_browsers"],
            "description": "Download Chromium for Patchright (run once after Ready).",
            "input_schema": EMPTY,
            "capabilities": _caps(effects, cost="expensive", latency="slow"),
        },
        {
            "name": "fetch",
            "action": "fetch",
            "command": [
                "{python}",
                "hades_bridge.py",
                "fetch",
                "--url",
                "{url}",
                "--max-chars",
                "{max_chars}",
            ],
            "description": "Open a URL with stealth Chromium and return visible page text.",
            "input_schema": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2000},
                    "max_chars": {
                        "type": "integer",
                        "default": 20000,
                        "minimum": 500,
                        "maximum": 80000,
                    },
                },
                "additionalProperties": False,
            },
            "capabilities": _caps(effects, cost="moderate", latency="normal"),
        },
        {
            "name": "screenshot",
            "action": "screenshot",
            "command": [
                "{python}",
                "hades_bridge.py",
                "screenshot",
                "--url",
                "{url}",
                "--output",
                "{output}",
            ],
            "description": "Capture a full-page screenshot via Patchright Chromium.",
            "input_schema": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2000},
                    "output": {
                        "type": "string",
                        "default": "screenshot.png",
                        "maxLength": 400,
                    },
                },
                "additionalProperties": False,
            },
            "capabilities": _caps(effects, cost="moderate", latency="normal"),
        },
    ]
    write_json(
        folder / "hades-plugin.json",
        _finalize_manifest(
            {
                "format": 1,
                "id": plugin_id,
                "name": "Patchright",
                "version": "0.1.0",
                "description": (
                    "Stealth Playwright drop-in for HADES research browsing: fetch and screenshot "
                    "pages that block vanilla automation. Upstream: Kaliiiiiiiiii-Vinyzu/patchright "
                    "(Python package patchright)."
                ),
                "runtime_type": "python",
                "entrypoint": "hades_bridge.py",
                "plugin_type": "tool",
                "category": "Browser",
                "labels": ["patchright", "playwright", "browser", "stealth", "screenshot"],
                "permissions": ["subprocess", "network", "filesystem"],
                "autonomous": False,
                "hades_api": ">=0.4.1",
                "source": "https://github.com/Kaliiiiiiiiii-Vinyzu/patchright",
                "license": "Apache-2.0",
                "dependency_install": {
                    "timeout_seconds": 1800,
                    "stall_timeout_seconds": 900,
                },
                "tools": tools,
                "isolation": "restricted_env",
                "capabilities": _caps(effects, cost="moderate", latency="normal"),
            }
        ),
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(
        folder / "README.md",
        readme(
            "Patchright",
            "https://github.com/Kaliiiiiiiiii-Vinyzu/patchright",
            [t["name"] for t in tools],
            "After Ready, run install_browsers once. Prefer manual approval for network fetch/screenshot.",
        ),
    )


def make_dspy() -> None:
    plugin_id = "dspy"
    folder = ROOT / plugin_id
    copy_shared(folder, ["cli_bridge.py"])
    write_text(
        folder / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        """HADES bridge for Stanford DSPy against local OpenAI-compatible endpoints (LM Studio)."""
        from __future__ import annotations

        import argparse
        import json
        import os
        from pathlib import Path


        def doctor() -> dict:
            import cli_bridge

            payload = cli_bridge.doctor(["dspy"], ["dspy"])
            payload["default_base_url"] = os.environ.get(
                "HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"
            )
            payload["notes"] = [
                "Point --base-url at LM Studio (or any OpenAI-compatible local server).",
                "Do not hardcode production model IDs — pass --model from the Models page / LM Studio list.",
                "predict runs a minimal dspy.Predict signature for smoke-quality local inference.",
            ]
            return payload


        def _configure(base_url: str, model: str, api_key: str):
            import dspy

            lm = dspy.LM(
                model=model if "/" in model or model.startswith("openai/") else f"openai/{model}",
                api_base=base_url.rstrip("/"),
                api_key=api_key or "lm-studio",
                model_type="chat",
            )
            dspy.configure(lm=lm)
            return dspy


        def predict(question: str, base_url: str, model: str, api_key: str, max_chars: int) -> dict:
            if not question.strip():
                raise SystemExit("question is required")
            if not model.strip():
                raise SystemExit("model is required (use a dynamic LM Studio model id)")
            dspy = _configure(base_url, model, api_key)

            class Answer(dspy.Signature):
                """Answer the question briefly and accurately for a local HADES workspace."""

                question: str = dspy.InputField()
                answer: str = dspy.OutputField()

            predictor = dspy.Predict(Answer)
            result = predictor(question=question)
            answer = str(getattr(result, "answer", "") or "")
            return {
                "question": question,
                "model": model,
                "base_url": base_url,
                "chars": len(answer),
                "truncated": len(answer) > max_chars,
                "answer": answer[:max_chars],
            }


        def compile_program(
            training_json: str,
            base_url: str,
            model: str,
            api_key: str,
            output: str,
        ) -> dict:
            """Compile a tiny few-shot program from JSON examples and save the program state."""
            path = Path(training_json)
            if not path.is_file():
                raise SystemExit(f"training file not found: {training_json}")
            examples = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(examples, list) or not examples:
                raise SystemExit("training JSON must be a non-empty list of {question,answer} objects")
            dspy = _configure(base_url, model, api_key)

            class Answer(dspy.Signature):
                question: str = dspy.InputField()
                answer: str = dspy.OutputField()

            trainset = [
                dspy.Example(question=str(row["question"]), answer=str(row["answer"])).with_inputs("question")
                for row in examples
                if isinstance(row, dict) and "question" in row and "answer" in row
            ]
            if not trainset:
                raise SystemExit("no valid training rows")
            program = dspy.Predict(Answer)
            # Lightweight labeled few-shot attach (no heavy teleprompter required for smoke compile).
            program.demos = trainset[:8]
            out = Path(output or "dspy_program.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                program.save(str(out))
                saved = str(out.resolve())
            except Exception:
                # Fallback: persist demos manually if save API differs across versions.
                saved = str(out.resolve())
                out.write_text(
                    json.dumps(
                        [{"question": ex.question, "answer": ex.answer} for ex in trainset[:8]],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            return {"examples": len(trainset), "output": saved, "model": model, "base_url": base_url}


        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            p = sub.add_parser("predict")
            p.add_argument("--question", required=True)
            p.add_argument("--base-url", default=os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"))
            p.add_argument("--model", required=True)
            p.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", "lm-studio"))
            p.add_argument("--max-chars", type=int, default=12000)
            c = sub.add_parser("compile")
            c.add_argument("--training-json", required=True)
            c.add_argument("--base-url", default=os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"))
            c.add_argument("--model", required=True)
            c.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", "lm-studio"))
            c.add_argument("--output", default="dspy_program.json")
            args = parser.parse_args()
            if args.cmd == "doctor":
                payload = doctor()
            elif args.cmd == "predict":
                payload = predict(args.question, args.base_url, args.model, args.api_key, args.max_chars)
            else:
                payload = compile_program(
                    args.training_json, args.base_url, args.model, args.api_key, args.output
                )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(folder / "requirements.txt", "dspy>=2.6.0\n")
    effects = ["network", "read_files", "write_files", "subprocess"]
    tools = [
        {
            "name": "doctor",
            "action": "doctor",
            "command": ["{python}", "hades_bridge.py", "doctor"],
            "description": "Check whether DSPy is importable and report default LM Studio base URL.",
            "input_schema": EMPTY,
            "capabilities": _caps(effects, cost="cheap", latency="fast"),
        },
        {
            "name": "predict",
            "action": "predict",
            "command": [
                "{python}",
                "hades_bridge.py",
                "predict",
                "--question",
                "{question}",
                "--base-url",
                "{base_url}",
                "--model",
                "{model}",
                "--api-key",
                "{api_key}",
                "--max-chars",
                "{max_chars}",
            ],
            "description": "Run a minimal DSPy Predict against a local OpenAI-compatible endpoint (LM Studio).",
            "input_schema": {
                "type": "object",
                "required": ["question", "model"],
                "properties": {
                    "question": {"type": "string", "minLength": 1, "maxLength": 8000},
                    "model": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "Dynamic LM Studio / OpenAI-compatible model id",
                    },
                    "base_url": {
                        "type": "string",
                        "default": "http://127.0.0.1:1234/v1",
                        "maxLength": 400,
                    },
                    "api_key": {"type": "string", "default": "lm-studio", "maxLength": 400},
                    "max_chars": {
                        "type": "integer",
                        "default": 12000,
                        "minimum": 500,
                        "maximum": 50000,
                    },
                },
                "additionalProperties": False,
            },
            "capabilities": _caps(effects, cost="moderate", latency="normal"),
        },
        {
            "name": "compile",
            "action": "compile",
            "command": [
                "{python}",
                "hades_bridge.py",
                "compile",
                "--training-json",
                "{training_json}",
                "--base-url",
                "{base_url}",
                "--model",
                "{model}",
                "--api-key",
                "{api_key}",
                "--output",
                "{output}",
            ],
            "description": "Attach few-shot demos from a JSON list and save a lightweight DSPy program.",
            "input_schema": {
                "type": "object",
                "required": ["training_json", "model"],
                "properties": {
                    "training_json": {"type": "string", "minLength": 1, "maxLength": 500},
                    "model": {"type": "string", "minLength": 1, "maxLength": 200},
                    "base_url": {
                        "type": "string",
                        "default": "http://127.0.0.1:1234/v1",
                        "maxLength": 400,
                    },
                    "api_key": {"type": "string", "default": "lm-studio", "maxLength": 400},
                    "output": {
                        "type": "string",
                        "default": "dspy_program.json",
                        "maxLength": 400,
                    },
                },
                "additionalProperties": False,
            },
            "capabilities": _caps(effects, cost="moderate", latency="normal"),
        },
    ]
    write_json(
        folder / "hades-plugin.json",
        _finalize_manifest(
            {
                "format": 1,
                "id": plugin_id,
                "name": "DSPy",
                "version": "0.1.0",
                "description": (
                    "Program language models with Stanford DSPy inside HADES. "
                    "predict/compile talk to local LM Studio via OpenAI-compatible HTTP — model ids stay dynamic."
                ),
                "runtime_type": "python",
                "entrypoint": "hades_bridge.py",
                "plugin_type": "tool",
                "category": "AI",
                "labels": ["dspy", "llm", "lm-studio", "prompting", "compile"],
                "permissions": ["subprocess", "network", "filesystem"],
                "autonomous": True,
                "hades_api": ">=0.4.1",
                "source": "https://github.com/stanfordnlp/dspy",
                "license": "MIT",
                "dependency_install": {
                    "timeout_seconds": 1800,
                    "stall_timeout_seconds": 900,
                },
                "tools": tools,
                "capabilities": _caps(effects, cost="moderate", latency="normal"),
            }
        ),
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(
        folder / "README.md",
        readme(
            "DSPy",
            "https://github.com/stanfordnlp/dspy",
            [t["name"] for t in tools],
            "Requires a reachable LM Studio (or compatible) OpenAI endpoint. Always pass an explicit --model id.",
        ),
    )


def make_moneyprinter() -> None:
    plugin_id = "moneyprinter-turbo"
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    write_text(
        overlay / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        """HADES helpers for MoneyPrinterTurbo (doctor + LM Studio config seed)."""
        from __future__ import annotations

        import argparse
        import json
        import os
        from pathlib import Path


        ROOT = Path(__file__).resolve().parent


        def doctor() -> dict:
            return {
                "root": str(ROOT),
                "main_py": (ROOT / "main.py").is_file(),
                "webui": (ROOT / "webui" / "Main.py").is_file(),
                "cli": (ROOT / "cli.py").is_file(),
                "config_example": (ROOT / "config.example.toml").is_file(),
                "config_toml": (ROOT / "config.toml").is_file(),
                "ui": "http://127.0.0.1:8501",
                "api_docs": "http://127.0.0.1:8080/docs",
                "notes": [
                    "Prefer seed_lm_studio before start so script generation uses local models.",
                    "Video generation still needs FFmpeg and a material source (pexels/local/etc).",
                    "Network may be required for stock footage unless you use local materials.",
                ],
            }


        def seed_lm_studio(base_url: str, model: str, api_key: str) -> dict:
            """Create/update config.toml openai_* fields for LM Studio without wiping other keys."""
            example = ROOT / "config.example.toml"
            target = ROOT / "config.toml"
            if not target.is_file():
                if not example.is_file():
                    raise SystemExit("config.example.toml missing")
                target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            text = target.read_text(encoding="utf-8")
            replacements = {
                "llm_provider": "openai",
                "openai_api_key": api_key or "lm-studio",
                "openai_base_url": base_url.rstrip("/") or "http://127.0.0.1:1234/v1",
                "openai_model_name": model,
                "listen_host": "127.0.0.1",
            }
            lines = text.splitlines()
            out: list[str] = []
            seen = set()
            for line in lines:
                stripped = line.strip()
                key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
                if key in replacements:
                    out.append(f'{key} = "{replacements[key]}"')
                    seen.add(key)
                else:
                    out.append(line)
            for key, value in replacements.items():
                if key not in seen:
                    out.append(f'{key} = "{value}"')
            target.write_text("\\n".join(out) + "\\n", encoding="utf-8")
            return {
                "config": str(target),
                "llm_provider": "openai",
                "openai_base_url": replacements["openai_base_url"],
                "openai_model_name": model,
                "listen_host": "127.0.0.1",
            }


        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            s = sub.add_parser("seed_lm_studio")
            s.add_argument("--base-url", default=os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"))
            s.add_argument("--model", required=True)
            s.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", "lm-studio"))
            args = parser.parse_args()
            if args.cmd == "doctor":
                payload = doctor()
            else:
                payload = seed_lm_studio(args.base_url, args.model, args.api_key)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    # Mirror bridge at folder root for local inspection before pack_git overlay.
    write_text(folder / "hades_bridge.py", (overlay / "hades_bridge.py").read_text(encoding="utf-8"))
    for path in (folder / "requirements.txt", overlay / "requirements.txt"):
        if path.exists():
            path.unlink()
    effects = ["network", "read_files", "write_files", "subprocess", "service"]
    tools = [
        {
            "name": "doctor",
            "action": "doctor",
            "command": ["{python}", "hades_bridge.py", "doctor"],
            "description": "Check MoneyPrinterTurbo layout and report UI/API endpoints.",
            "input_schema": EMPTY,
            "capabilities": _caps(effects, cost="moderate", latency="slow"),
        },
        {
            "name": "seed_lm_studio",
            "action": "configure",
            "command": [
                "{python}",
                "hades_bridge.py",
                "seed_lm_studio",
                "--base-url",
                "{base_url}",
                "--model",
                "{model}",
                "--api-key",
                "{api_key}",
            ],
            "description": "Seed config.toml openai_* fields for local LM Studio script generation.",
            "input_schema": {
                "type": "object",
                "required": ["model"],
                "properties": {
                    "model": {"type": "string", "minLength": 1, "maxLength": 200},
                    "base_url": {
                        "type": "string",
                        "default": "http://127.0.0.1:1234/v1",
                        "maxLength": 400,
                    },
                    "api_key": {"type": "string", "default": "lm-studio", "maxLength": 400},
                },
                "additionalProperties": False,
            },
            "capabilities": _caps(
                ["read_files", "write_files", "subprocess"], cost="cheap", latency="fast"
            ),
        },
        {
            "name": "start",
            "action": "start",
            "mode": "service",
            "command": [
                "{python}",
                "-m",
                "streamlit",
                "run",
                "webui/Main.py",
                "--server.address",
                "127.0.0.1",
                "--server.port",
                "8501",
                "--browser.gatherUsageStats",
                "false",
            ],
            "env": {
                "MPT_WEBUI_HOST": "127.0.0.1",
                "MPT_WEBUI_PORT": "8501",
            },
            "description": "Start MoneyPrinterTurbo Streamlit WebUI on http://127.0.0.1:8501.",
            "input_schema": EMPTY,
            "capabilities": _caps(effects, cost="expensive", latency="slow"),
        },
        *lifecycle_tools(),
    ]
    for tool in tools:
        tool.setdefault("capabilities", _caps(effects, cost="moderate", latency="slow"))
    write_json(
        folder / "hades-plugin.json",
        _finalize_manifest(
            {
                "format": 1,
                "id": plugin_id,
                "name": "MoneyPrinterTurbo",
                "version": "0.1.0",
                "description": (
                    "AI short-video generator WebUI for HADES. Seed LM Studio for local script generation, "
                    "then start Streamlit on port 8501. Upstream: harry0703/MoneyPrinterTurbo."
                ),
                "runtime_type": "python",
                "entrypoint": "webui/Main.py",
                "plugin_type": "service",
                "category": "Media",
                "labels": ["video", "short-video", "streamlit", "lm-studio", "tts"],
                "permissions": ["subprocess", "filesystem", "network"],
                "autonomous": False,
                "hades_api": ">=0.4.1",
                "source": "https://github.com/harry0703/MoneyPrinterTurbo",
                "license": "MIT",
                "healthcheck": {
                    "type": "http",
                    "url": "http://127.0.0.1:8501/",
                    "method": "GET",
                    "expected_status": [200, 301, 302, 304],
                    "timeout_seconds": 240,
                    "interval_seconds": 2.0,
                },
                "dependency_install": {
                    "timeout_seconds": 3600,
                    "stall_timeout_seconds": 1800,
                },
                "tools": tools,
                "isolation": "restricted_env",
                "capabilities": _caps(effects, cost="expensive", latency="slow"),
            }
        ),
    )
    write_text(
        folder / "pack_hadesplugin.py",
        packer_git(plugin_id, "https://github.com/harry0703/MoneyPrinterTurbo.git"),
    )
    write_text(
        folder / "README.md",
        readme(
            "MoneyPrinterTurbo",
            "https://github.com/harry0703/MoneyPrinterTurbo",
            [t["name"] for t in tools],
            "Heavy deps + FFmpeg. Run seed_lm_studio with your LM Studio model id, then start and open http://127.0.0.1:8501.",
        ),
    )


def make_vibe_trading() -> None:
    plugin_id = "vibe-trading"
    folder = ROOT / plugin_id
    copy_shared(folder, ["cli_bridge.py", "mcp_bridge.py"])
    write_text(
        folder / "hades_bridge.py",
        (SHARED / "bridge_templates" / "vibe-trading.py").read_text(encoding="utf-8"),
    )
    write_text(
        folder / "serve_entrypoint.py",
        '''
        #!/usr/bin/env python3
        """Managed service entry for Vibe-Trading web UI (plugin venv)."""
        from __future__ import annotations

        import os
        import sys


        def main() -> int:
            os.environ.setdefault("LANGCHAIN_PROVIDER", "openai")
            os.environ.setdefault(
                "LANGCHAIN_BASE_URL",
                os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
            )
            os.environ.setdefault("LANGCHAIN_API_KEY", os.environ.get("OPENAI_API_KEY", "lm-studio"))
            # Prefer console script module path from the installed package.
            from cli import main as vibe_main

            sys.argv = ["vibe-trading", "serve", "--host", "127.0.0.1", "--port", "8899"]
            result = vibe_main()
            return int(result or 0)


        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(folder / "requirements.txt", "vibe-trading-ai>=0.1.14\n")
    effects = ["network", "read_files", "write_files", "subprocess", "service", "mcp"]
    tools = [
        {
            "name": "doctor",
            "action": "doctor",
            "command": ["{python}", "hades_bridge.py", "doctor"],
            "description": "Check vibe-trading-ai install and report UI/MCP entrypoints.",
            "input_schema": EMPTY,
            "capabilities": _caps(effects, cost="moderate", latency="normal"),
        },
        {
            "name": "start",
            "action": "start",
            "mode": "service",
            "command": ["{python}", "serve_entrypoint.py"],
            "env": {
                "LANGCHAIN_PROVIDER": "openai",
                "LANGCHAIN_BASE_URL": "http://127.0.0.1:1234/v1",
                "LANGCHAIN_API_KEY": "lm-studio",
            },
            "description": "Start Vibe-Trading FastAPI web UI on http://127.0.0.1:8899 (configure model via Settings/env).",
            "input_schema": EMPTY,
            "capabilities": _caps(effects, cost="expensive", latency="slow"),
        },
        *lifecycle_tools(),
        {
            "name": "research",
            "action": "run",
            "command": [
                "{python}",
                "hades_bridge.py",
                "research",
                "--prompt",
                "{prompt}",
                "--timeout",
                "{timeout}",
            ],
            "description": "Run one Vibe-Trading research/backtest prompt via CLI (local LLM preferred).",
            "input_schema": {
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string", "minLength": 3, "maxLength": 8000},
                    "timeout": {
                        "type": "integer",
                        "default": 600,
                        "minimum": 30,
                        "maximum": 3600,
                    },
                },
                "additionalProperties": False,
            },
            "capabilities": _caps(effects, cost="expensive", latency="slow"),
        },
        {
            "name": "list_tools",
            "action": "list",
            "mode": "command",
            "command": [
                "{python}",
                "hades_bridge.py",
                "mcp",
                "--action",
                "list_tools",
                "--timeout",
                "90",
            ],
            "description": "List research-only MCP tools exposed by vibe-trading-mcp.",
            "input_schema": EMPTY,
            "capabilities": _caps(effects, cost="moderate", latency="normal"),
        },
        {
            "name": "call_tool",
            "action": "call",
            "mode": "command",
            "command": [
                "{python}",
                "hades_bridge.py",
                "mcp",
                "--action",
                "call_tool",
                "--tool",
                "{tool}",
                "--arguments",
                "{arguments}",
                "--timeout",
                "180",
            ],
            "description": "Call one Vibe-Trading MCP research tool with JSON arguments.",
            "input_schema": {
                "type": "object",
                "required": ["tool"],
                "properties": {
                    "tool": {"type": "string", "minLength": 1, "maxLength": 200},
                    "arguments": {
                        "type": "string",
                        "default": "{}",
                        "description": "JSON object string",
                    },
                },
                "additionalProperties": False,
            },
            "capabilities": _caps(effects, cost="expensive", latency="slow"),
        },
    ]
    for tool in tools:
        tool.setdefault("capabilities", _caps(effects, cost="moderate", latency="normal"))
    write_json(
        folder / "hades-plugin.json",
        _finalize_manifest(
            {
                "format": 1,
                "id": plugin_id,
                "name": "Vibe-Trading",
                "version": "0.1.0",
                "description": (
                    "Personal trading research agent for HADES: web UI on :8899, CLI research runs, "
                    "and research-only MCP tools. Prefer local LM Studio via LANGCHAIN_* env. "
                    "Upstream: HKUDS/Vibe-Trading."
                ),
                "runtime_type": "python",
                "entrypoint": "hades_bridge.py",
                "plugin_type": "service",
                "category": "Finance",
                "labels": ["trading", "backtest", "finance", "mcp", "lm-studio", "research"],
                "permissions": ["subprocess", "filesystem", "network"],
                "autonomous": False,
                "hades_api": ">=0.4.1",
                "source": "https://github.com/HKUDS/Vibe-Trading",
                "license": "MIT",
                "mcp": {"expand_tools": True},
                "healthcheck": {
                    "type": "http",
                    "url": "http://127.0.0.1:8899/",
                    "method": "GET",
                    "expected_status": [200, 301, 302, 304],
                    "timeout_seconds": 240,
                    "interval_seconds": 2.0,
                },
                "dependency_install": {
                    "timeout_seconds": 3600,
                    "stall_timeout_seconds": 1800,
                },
                "tools": tools,
                "isolation": "restricted_env",
                "capabilities": _caps(effects, cost="expensive", latency="slow"),
            }
        ),
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(
        folder / "README.md",
        readme(
            "Vibe-Trading",
            "https://github.com/HKUDS/Vibe-Trading",
            [t["name"] for t in tools],
            "Heavy finance stack. Set LANGCHAIN_MODEL to a dynamic LM Studio id before research/start. MCP surface is research-only.",
        ),
    )


def refresh_index() -> None:
    ids = sorted(
        p.name for p in ROOT.iterdir() if p.is_dir() and (p / "hades-plugin.json").exists()
    )
    write_text(
        ROOT / "README.md",
        f"""
        # HADES plugins

        Installable `.HadesPlugin` packages and manifests.

        ## Catalog ({len(ids)})

        {chr(10).join(f"- `{item}`" for item in ids)}

        ## Pack one plugin

        ```bat
        python plugins\\markitdown\\pack_hadesplugin.py --out plugins\\markitdown\\dist
        ```

        ## Pack all local-ready plugins

        ```bat
        python plugins\\pack_all.py --mode local
        ```

        Catalog plugin source lives here. Release-ready packages normally ship a `dist/<id>-<version>.HadesPlugin` artifact through Git LFS; rebuild with `python plugins\\pack_all.py` or the per-plugin packer when an artifact is not committed.

        Shared bridges live in `plugins/_shared/`.

        ## Batch 3 notes

        - `impeccable`, `gsap-skills`, `design-dna` — skill libraries for design/animation guidance
        - `patchright` — stealth Chromium fetch/screenshot (Python package)
        - `dspy` — DSPy predict/compile against LM Studio
        - `moneyprinter-turbo` — short-video WebUI service
        - `vibe-trading` — finance research UI + MCP
        - `bikini/exploitarium` is intentionally **not** packaged (exploit PoC archive)
        """,
    )
    print("catalog size", len(ids))
    for item in ids:
        print("-", item)


def main() -> None:
    make_impeccable()
    make_gsap_skills()
    make_design_dna()
    make_patchright()
    make_dspy()
    make_moneyprinter()
    make_vibe_trading()
    # Update pack_all local_only set note is separate — refresh catalog index.
    refresh_index()
    # Ensure pack_all knows local-packable new plugins.
    pack_all = ROOT / "pack_all.py"
    text = pack_all.read_text(encoding="utf-8")
    for name in ('"patchright"', '"dspy"', '"vibe-trading"'):
        if name not in text:
            text = text.replace(
                '"sinwindie-osint",\n    }',
                f'"sinwindie-osint",\n        {name},\n    }}',
            )
    pack_all.write_text(text, encoding="utf-8")
    print("batch3 complete")


if __name__ == "__main__":
    main()
