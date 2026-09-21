#!/usr/bin/env python3
"""Generate the second curated upstream HADES plugin batch."""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

from generate_catalog import (
    EMPTY,
    ROOT,
    SHARED,
    catalog_tools,
    copy_shared,
    lifecycle_tools,
    packer_git,
    packer_local,
    readme,
    skill_tools,
    write_json,
    write_text,
)


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
) -> None:
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    copy_shared(overlay, ["skill_bridge.py"])
    copy_shared(folder, ["skill_bridge.py"])
    write_text(overlay / "requirements.txt", "# skill plugin — stdlib only\n")
    write_text(folder / "requirements.txt", "# skill plugin — stdlib only\n")
    tools = skill_tools(name)
    payload = {
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
    if license_id:
        payload["license"] = license_id
    write_json(folder / "hades-plugin.json", payload)
    write_text(folder / "pack_hadesplugin.py", packer_git(plugin_id, source))
    write_text(folder / "README.md", readme(name, source, [t["name"] for t in tools], notes))


def make_catalog_git(
    plugin_id: str,
    name: str,
    source: str,
    description: str,
    category: str,
    labels: list[str],
    *,
    license_id: str | None = None,
) -> None:
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    copy_shared(overlay, ["catalog_bridge.py"])
    copy_shared(folder, ["catalog_bridge.py"])
    write_text(overlay / "requirements.txt", "# catalog plugin — stdlib only\n")
    write_text(folder / "requirements.txt", "# catalog plugin — stdlib only\n")
    tools = catalog_tools(name)
    payload = {
        "format": 1,
        "id": plugin_id,
        "name": name,
        "version": "0.1.0",
        "description": description,
        "runtime_type": "python",
        "entrypoint": "catalog_bridge.py",
        "plugin_type": "tool",
        "category": category,
        "labels": labels,
        "permissions": ["subprocess"],
        "autonomous": True,
        "hades_api": ">=0.4.1",
        "source": source,
        "tools": tools,
    }
    if license_id:
        payload["license"] = license_id
    write_json(folder / "hades-plugin.json", payload)
    write_text(folder / "pack_hadesplugin.py", packer_git(plugin_id, source))
    write_text(
        folder / "README.md",
        readme(name, source, [t["name"] for t in tools], "Autonomous catalog search/read is enabled."),
    )


def make_scrapling() -> None:
    plugin_id = "scrapling"
    folder = ROOT / plugin_id
    copy_shared(folder, ["cli_bridge.py"])
    write_text(
        folder / "hades_bridge.py",
        (SHARED / "bridge_templates" / "scrapling.py").read_text(encoding="utf-8"),
    )
    write_text(folder / "requirements.txt", 'scrapling[fetchers,shell]>=0.3.0\n')
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Check Scrapling install in the plugin venv.", "input_schema": EMPTY},
        {"name": "install_browsers", "action": "install", "command": ["{python}", "hades_bridge.py", "install_browsers"], "description": "Run scrapling install to fetch browser dependencies.", "input_schema": EMPTY},
        {
            "name": "fetch",
            "action": "fetch",
            "command": ["{python}", "hades_bridge.py", "fetch", "--url", "{url}", "--mode", "{mode}", "--css", "{css}", "--max-chars", "{max_chars}"],
            "description": "Fetch a URL with Scrapling (basic/stealth/dynamic) and optionally extract CSS matches.",
            "input_schema": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2000},
                    "mode": {"type": "string", "enum": ["basic", "stealth", "dynamic"], "default": "basic"},
                    "css": {"type": "string", "default": ""},
                    "max_chars": {"type": "integer", "default": 20000, "minimum": 500, "maximum": 80000},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "extract",
            "action": "extract",
            "command": ["{python}", "hades_bridge.py", "extract", "--url", "{url}", "--output", "{output}"],
            "description": "Use scrapling extract get to save page markdown/content to a local file.",
            "input_schema": {
                "type": "object",
                "required": ["url", "output"],
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2000},
                    "output": {"type": "string", "minLength": 1, "maxLength": 400},
                },
                "additionalProperties": False,
            },
        },
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "Scrapling",
            "version": "0.1.0",
            "description": "Adaptive web scraping framework with fetch/extract tools for HADES. Upstream: D4Vinci/Scrapling.",
            "runtime_type": "python",
            "entrypoint": "hades_bridge.py",
            "plugin_type": "tool",
            "category": "Research",
            "labels": ["scraping", "crawler", "fetch"],
            "permissions": ["subprocess", "network", "filesystem"],
            "autonomous": False,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/D4Vinci/Scrapling",
            "license": "BSD-3-Clause",
            "dependency_install": {"timeout_seconds": 1800, "stall_timeout_seconds": 900},
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(
        folder / "README.md",
        readme(
            "Scrapling",
            "https://github.com/D4Vinci/Scrapling",
            [t["name"] for t in tools],
            "Autonomous use is disabled. Allow network policy before fetch/extract. Run install_browsers once for stealth/dynamic modes.",
        ),
    )


def make_puppeteer() -> None:
    plugin_id = "puppeteer"
    folder = ROOT / plugin_id
    write_text(
        folder / "hades_bridge.mjs",
        '''
        import fs from "node:fs";
        import path from "node:path";
        import { fileURLToPath } from "node:url";

        const __dirname = path.dirname(fileURLToPath(import.meta.url));
        const args = process.argv.slice(2);
        const cmd = args[0];

        function argValue(flag, fallback = "") {
          const idx = args.indexOf(flag);
          if (idx === -1) return fallback;
          const value = args[idx + 1];
          if (!value || value.startsWith("--")) return fallback;
          return value;
        }

        async function withBrowser(fn) {
          const puppeteer = await import("puppeteer");
          const browser = await puppeteer.default.launch({
            headless: true,
            args: ["--no-sandbox", "--disable-setuid-sandbox"],
          });
          try {
            return await fn(browser);
          } finally {
            await browser.close();
          }
        }

        if (cmd === "doctor") {
          const pkgPath = path.join(__dirname, "package.json");
          const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
          let puppeteerOk = false;
          try {
            await import("puppeteer");
            puppeteerOk = true;
          } catch {
            puppeteerOk = false;
          }
          console.log(JSON.stringify({
            name: pkg.name,
            version: pkg.version,
            dependency: pkg.dependencies?.puppeteer || null,
            puppeteer_importable: puppeteerOk,
          }, null, 2));
          process.exit(0);
        }

        if (cmd === "fetch") {
          const url = argValue("--url");
          const maxChars = Number(argValue("--max-chars", "20000"));
          if (!url) {
            console.error("url is required");
            process.exit(1);
          }
          const result = await withBrowser(async (browser) => {
            const page = await browser.newPage();
            await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
            const title = await page.title();
            const text = await page.evaluate(() => document.body?.innerText || "");
            const html = await page.content();
            return {
              url,
              title,
              chars: text.length,
              truncated: text.length > maxChars,
              text: text.slice(0, maxChars),
              html_chars: html.length,
            };
          });
          console.log(JSON.stringify(result, null, 2));
          process.exit(0);
        }

        if (cmd === "screenshot") {
          const url = argValue("--url");
          const output = argValue("--output", "screenshot.png");
          if (!url) {
            console.error("url is required");
            process.exit(1);
          }
          const result = await withBrowser(async (browser) => {
            const page = await browser.newPage();
            await page.setViewport({ width: 1280, height: 720 });
            await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });
            const outPath = path.resolve(output);
            await page.screenshot({ path: outPath, fullPage: true });
            return { url, output: outPath, bytes: fs.statSync(outPath).size };
          });
          console.log(JSON.stringify(result, null, 2));
          process.exit(0);
        }

        console.error(`unknown command: ${cmd}`);
        process.exit(1);
        ''',
    )
    # Fix typo introduced above - I'll rewrite the doctor block cleanly in a follow-up write
    write_json(
        folder / "package.json",
        {
            "name": "hades-puppeteer",
            "version": "0.1.0",
            "private": True,
            "type": "module",
            "dependencies": {"puppeteer": "^24.0.0"},
        },
    )
    tools = [
        {
            "name": "doctor",
            "action": "doctor",
            "command": ["{npm}", "exec", "--", "node", "hades_bridge.mjs", "doctor"],
            "description": "Check whether the Puppeteer package is installed and importable.",
            "input_schema": EMPTY,
        },
        {
            "name": "fetch",
            "action": "fetch",
            "command": ["{npm}", "exec", "--", "node", "hades_bridge.mjs", "fetch", "--url", "{url}", "--max-chars", "{max_chars}"],
            "description": "Open a URL in headless Chromium and return page text.",
            "input_schema": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2000},
                    "max_chars": {"type": "integer", "default": 20000, "minimum": 500, "maximum": 80000},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "screenshot",
            "action": "screenshot",
            "command": ["{npm}", "exec", "--", "node", "hades_bridge.mjs", "screenshot", "--url", "{url}", "--output", "{output}"],
            "description": "Capture a full-page screenshot of a URL with Puppeteer.",
            "input_schema": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2000},
                    "output": {"type": "string", "default": "screenshot.png", "maxLength": 400},
                },
                "additionalProperties": False,
            },
        },
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "Puppeteer",
            "version": "0.1.0",
            "description": "Headless Chromium automation via Puppeteer for fetch and screenshot tools. Slim HADES wrapper around the puppeteer npm package.",
            "runtime_type": "node",
            "entrypoint": "hades_bridge.mjs",
            "plugin_type": "tool",
            "category": "Browser",
            "labels": ["puppeteer", "browser", "screenshot"],
            "permissions": ["subprocess", "network", "filesystem"],
            "autonomous": False,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/puppeteer/puppeteer",
            "license": "Apache-2.0",
            "dependency_install": {"timeout_seconds": 1800, "stall_timeout_seconds": 900},
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(
        folder / "README.md",
        readme(
            "Puppeteer",
            "https://github.com/puppeteer/puppeteer",
            [t["name"] for t in tools],
            "npm install downloads Chromium. Autonomous use is disabled; allow network policy for page loads.",
        ),
    )


def make_headroom() -> None:
    plugin_id = "headroom"
    folder = ROOT / plugin_id
    copy_shared(folder, ["cli_bridge.py"])
    write_text(
        folder / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        from __future__ import annotations
        import argparse
        import json
        import shutil
        import subprocess
        from pathlib import Path


        def doctor() -> dict:
            import cli_bridge
            payload = cli_bridge.doctor(["headroom"], ["headroom"])
            payload["notes"] = [
                "Use compress for one-shot message compression.",
                "Use start to run the local Headroom proxy (default 127.0.0.1:8787).",
            ]
            return payload


        def compress(path: str, model: str, max_chars: int) -> dict:
            from headroom import compress as headroom_compress
            source = Path(path)
            if not source.is_file():
                raise SystemExit(f"input file not found: {path}")
            text = source.read_text(encoding="utf-8", errors="replace")
            messages = [{"role": "user", "content": text}]
            result = headroom_compress(messages, model=model or "gpt-4o")
            if isinstance(result, dict):
                payload = result
            else:
                payload = {"result": result}
            rendered = json.dumps(payload, ensure_ascii=False)
            return {
                "input": str(source),
                "model": model or "gpt-4o",
                "input_chars": len(text),
                "output_chars": len(rendered),
                "truncated": len(rendered) > max_chars,
                "compressed": rendered[:max_chars],
            }


        def headroom_bin() -> str:
            return shutil.which("headroom") or shutil.which("headroom.exe") or "headroom"


        def cli(args: list[str], timeout: int = 120) -> dict:
            command = [headroom_bin(), *args]
            process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=False)
            return {
                "command": command,
                "exit_code": process.returncode,
                "stdout": (process.stdout or "")[-50_000:],
                "stderr": (process.stderr or "")[-50_000:],
            }


        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            c = sub.add_parser("compress")
            c.add_argument("--path", required=True)
            c.add_argument("--model", default="gpt-4o")
            c.add_argument("--max-chars", type=int, default=20000)
            p = sub.add_parser("proxy")
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", default="8787")
            args = parser.parse_args()
            if args.cmd == "doctor":
                payload = doctor()
            elif args.cmd == "proxy":
                # Exec-style service entry used by the managed start tool.
                command = [headroom_bin(), "proxy", "--host", args.host, "--port", str(args.port)]
                raise SystemExit(subprocess.call(command))
            else:
                payload = compress(args.path, args.model, args.max_chars)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(folder / "requirements.txt", 'headroom-ai[all]>=0.30.0\n')
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Check Headroom Python module and CLI in the plugin venv.", "input_schema": EMPTY},
        {
            "name": "compress",
            "action": "compress",
            "command": ["{python}", "hades_bridge.py", "compress", "--path", "{path}", "--model", "{model}", "--max-chars", "{max_chars}"],
            "description": "Compress a local text/JSON file through Headroom before sending it to an LLM.",
            "input_schema": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 500},
                    "model": {"type": "string", "default": "gpt-4o", "maxLength": 80},
                    "max_chars": {"type": "integer", "default": 20000, "minimum": 500, "maximum": 100000},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "start",
            "action": "start",
            "mode": "service",
            "command": ["{python}", "hades_bridge.py", "proxy", "--host", "127.0.0.1", "--port", "8787"],
            "description": "Start the local Headroom optimization proxy on 127.0.0.1:8787.",
            "input_schema": EMPTY,
        },
        *lifecycle_tools(),
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "Headroom",
            "version": "0.1.0",
            "description": "Local context compression for tool outputs/logs/RAG chunks. Compress files or start the Headroom proxy. Upstream: headroomlabs-ai/headroom.",
            "runtime_type": "python",
            "entrypoint": "hades_bridge.py",
            "plugin_type": "service",
            "category": "Developer",
            "labels": ["tokens", "compression", "context"],
            "permissions": ["subprocess", "filesystem", "network"],
            "autonomous": True,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/headroomlabs-ai/headroom",
            "license": "Apache-2.0",
            "healthcheck": {
                "type": "tcp",
                "host": "127.0.0.1",
                "port": 8787,
                "timeout_seconds": 60,
                "interval_seconds": 1.0,
            },
            "dependency_install": {"timeout_seconds": 1800, "stall_timeout_seconds": 900},
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(
        folder / "README.md",
        readme(
            "Headroom",
            "https://github.com/headroomlabs-ai/headroom",
            [t["name"] for t in tools],
            "compress works offline for local files. start requires the proxy extra from headroom-ai[all].",
        ),
    )


def make_agent_reach() -> None:
    plugin_id = "agent-reach"
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    copy_shared(folder, ["cli_bridge.py", "skill_bridge.py"])
    copy_shared(overlay, ["skill_bridge.py"])
    write_text(
        folder / "hades_bridge.py",
        (SHARED / "bridge_templates" / "agent-reach.py").read_text(encoding="utf-8"),
    )
    write_text(overlay / "hades_bridge.py", (folder / "hades_bridge.py").read_text(encoding="utf-8"))
    write_text(overlay / "cli_bridge.py", (SHARED / "cli_bridge.py").read_text(encoding="utf-8"))
    # Do not ship requirements.txt: packed upstream provides pyproject.toml for pip install.
    for path in (folder / "requirements.txt", overlay / "requirements.txt"):
        if path.exists():
            path.unlink()
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Run Agent Reach doctor and report channel readiness.", "input_schema": EMPTY},
        {
            "name": "install_check",
            "action": "install",
            "command": ["{python}", "hades_bridge.py", "install_check", "--env", "{env}"],
            "description": "Dry-run Agent Reach install checks without applying system changes.",
            "input_schema": {
                "type": "object",
                "properties": {"env": {"type": "string", "enum": ["auto", "local", "server"], "default": "auto"}},
                "additionalProperties": False,
            },
        },
        *skill_tools("Agent Reach"),
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "Agent Reach",
            "version": "0.1.0",
            "description": "Give HADES eyes on the internet: Agent Reach doctor/install checks plus packaged skill docs for platform read/search commands. Upstream: Panniantong/Agent-Reach.",
            "runtime_type": "python",
            "entrypoint": "hades_bridge.py",
            "plugin_type": "tool",
            "category": "Research",
            "labels": ["web", "social", "search", "agent-reach"],
            "permissions": ["subprocess", "network"],
            "autonomous": True,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/Panniantong/Agent-Reach",
            "license": "MIT",
            "dependency_install": {"timeout_seconds": 1800, "stall_timeout_seconds": 900},
            "tools": tools,
        },
    )
    write_text(
        folder / "pack_hadesplugin.py",
        packer_git(plugin_id, "https://github.com/Panniantong/Agent-Reach.git"),
    )
    write_text(
        folder / "README.md",
        readme(
            "Agent Reach",
            "https://github.com/Panniantong/Agent-Reach",
            [t["name"] for t in tools],
            "doctor/install_check stay safe-by-default. Platform read/search uses upstream tools documented in the packaged skills after operator setup.",
        ),
    )


def make_rtk() -> None:
    plugin_id = "rtk"
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    write_text(
        overlay / "hades_bridge.py",
        (SHARED / "bridge_templates" / "rtk.py").read_text(encoding="utf-8"),
    )
    write_text(folder / "hades_bridge.py", (overlay / "hades_bridge.py").read_text(encoding="utf-8"))
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Locate the RTK binary built into the plugin runtime.", "input_schema": EMPTY},
        {"name": "gain", "action": "status", "command": ["{python}", "hades_bridge.py", "gain"], "description": "Show RTK savings dashboard (rtk gain).", "input_schema": EMPTY},
        {
            "name": "run",
            "action": "run",
            "command": ["{python}", "hades_bridge.py", "run", "--args", "{args}"],
            "description": "Run RTK with argv tokens (example: git status, read file.py, ls .).",
            "input_schema": {
                "type": "object",
                "required": ["args"],
                "properties": {
                    "args": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 30,
                        "items": {"type": "string", "minLength": 1, "maxLength": 400},
                    }
                },
                "additionalProperties": False,
            },
        },
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "RTK",
            "version": "0.1.0",
            "description": "Rust Token Killer: compress common shell/dev command output before it reaches an LLM. Builds with Cargo on plugin install. Upstream: rtk-ai/rtk.",
            "runtime_type": "rust",
            "entrypoint": "hades_bridge.py",
            "plugin_type": "tool",
            "category": "Developer",
            "labels": ["tokens", "cli", "rust", "rtk"],
            "permissions": ["subprocess", "filesystem"],
            "autonomous": True,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/rtk-ai/rtk",
            "license": "Apache-2.0",
            "dependency_install": {"timeout_seconds": 2400, "stall_timeout_seconds": 1200},
            "tools": tools,
        },
    )
    write_text(
        folder / "pack_hadesplugin.py",
        packer_git(plugin_id, "https://github.com/rtk-ai/rtk.git", ref="develop"),
    )
    write_text(
        folder / "README.md",
        readme(
            "RTK",
            "https://github.com/rtk-ai/rtk",
            [t["name"] for t in tools],
            "Requires Rust/Cargo on PATH for dependency install (`cargo build --release`). Then use run with argv like `[\"git\",\"status\"]`.",
        ),
    )


def make_searxng() -> None:
    plugin_id = "searxng"
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    write_text(
        overlay / "hades_bridge.py",
        (SHARED / "bridge_templates" / "searxng.py").read_text(encoding="utf-8"),
    )
    write_text(folder / "hades_bridge.py", (overlay / "hades_bridge.py").read_text(encoding="utf-8"))
    write_text(overlay / "requirements.txt", "# stdlib only\n")
    write_text(folder / "requirements.txt", "# stdlib only\n")
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Check Docker availability and SearXNG endpoint defaults.", "input_schema": EMPTY},
        {
            "name": "start",
            "action": "start",
            "mode": "service",
            "command": ["docker", "compose", "-f", "container/docker-compose.yml", "up"],
            "description": "Start SearXNG via docker compose (UI/API on http://127.0.0.1:8080).",
            "input_schema": EMPTY,
        },
        {
            "name": "search",
            "action": "search",
            "command": ["{python}", "hades_bridge.py", "search", "--query", "{query}", "--language", "{language}", "--limit", "{limit}", "--base-url", "{base_url}"],
            "description": "Query the local SearXNG JSON API after the service is healthy.",
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 300},
                    "language": {"type": "string", "default": "en", "maxLength": 16},
                    "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 30},
                    "base_url": {"type": "string", "default": "http://127.0.0.1:8080", "maxLength": 200},
                },
                "additionalProperties": False,
            },
        },
        *lifecycle_tools(),
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "SearXNG",
            "version": "0.1.0",
            "description": "Privacy-respecting metasearch. Starts local SearXNG with Docker and exposes a JSON search tool for HADES.",
            "runtime_type": "python",
            "entrypoint": "start",
            "plugin_type": "service",
            "category": "Research",
            "labels": ["search", "metasearch", "privacy", "docker"],
            "permissions": ["subprocess", "network"],
            "autonomous": False,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/searxng/searxng",
            "license": "AGPL-3.0",
            "healthcheck": {
                "type": "http",
                "url": "http://127.0.0.1:8080/",
                "method": "GET",
                "expected_status": [200, 301, 302, 304],
                "timeout_seconds": 180,
                "interval_seconds": 2.0,
            },
            "tools": tools,
        },
    )
    write_text(
        folder / "pack_hadesplugin.py",
        packer_git(plugin_id, "https://github.com/searxng/searxng.git", ref="master"),
    )
    write_text(
        folder / "README.md",
        readme(
            "SearXNG",
            "https://github.com/searxng/searxng",
            [t["name"] for t in tools],
            "Requires Docker. After start/health succeeds, use search against http://127.0.0.1:8080.",
        ),
    )


def make_kotaemon() -> None:
    plugin_id = "kotaemon"
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    write_text(
        overlay / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        from __future__ import annotations
        import argparse
        import json
        from pathlib import Path


        def doctor() -> dict:
            root = Path(__file__).resolve().parent
            return {
                "app_py": (root / "app.py").is_file(),
                "pyproject": (root / "pyproject.toml").is_file(),
                "ui": "http://127.0.0.1:7860",
                "notes": [
                    "Dependency install uses upstream pyproject/libs.",
                    "Configure local LLM providers inside the kotaemon UI after start.",
                ],
            }


        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            args = parser.parse_args()
            print(json.dumps(doctor() if args.cmd == "doctor" else {}, ensure_ascii=False, indent=2))
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(folder / "hades_bridge.py", (overlay / "hades_bridge.py").read_text(encoding="utf-8"))
    # Prefer upstream pyproject.toml after pack_git (no requirements.txt shadowing).
    for path in (folder / "requirements.txt", overlay / "requirements.txt"):
        if path.exists():
            path.unlink()
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Check kotaemon source layout before starting the UI.", "input_schema": EMPTY},
        {
            "name": "start",
            "action": "start",
            "mode": "service",
            "command": ["{python}", "app.py"],
            "env": {
                "GRADIO_SERVER_NAME": "127.0.0.1",
                "GRADIO_SERVER_PORT": "7860",
            },
            "description": "Start kotaemon Gradio UI on http://127.0.0.1:7860.",
            "input_schema": EMPTY,
        },
        *lifecycle_tools(),
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "kotaemon",
            "version": "0.1.0",
            "description": "Open-source RAG UI for chatting with documents. Starts local Gradio app on port 7860. Upstream: Cinnamon/kotaemon.",
            "runtime_type": "python",
            "entrypoint": "app.py",
            "plugin_type": "service",
            "category": "Research",
            "labels": ["rag", "documents", "gradio"],
            "permissions": ["subprocess", "filesystem", "network"],
            "autonomous": False,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/Cinnamon/kotaemon",
            "license": "Apache-2.0",
            "healthcheck": {
                "type": "http",
                "url": "http://127.0.0.1:7860/",
                "method": "GET",
                "expected_status": [200, 301, 302, 304],
                "timeout_seconds": 180,
                "interval_seconds": 2.0,
            },
            "dependency_install": {"timeout_seconds": 2400, "stall_timeout_seconds": 1200},
            "tools": tools,
        },
    )
    write_text(
        folder / "pack_hadesplugin.py",
        packer_git(plugin_id, "https://github.com/Cinnamon/kotaemon.git"),
    )
    write_text(
        folder / "README.md",
        readme(
            "kotaemon",
            "https://github.com/Cinnamon/kotaemon",
            [t["name"] for t in tools],
            "Heavy Python deps. After Ready, run start and open http://127.0.0.1:7860.",
        ),
    )


def refresh_index() -> None:
    ids = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and (p / "hades-plugin.json").exists())
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

        Shared bridges live in `plugins/_shared/`.
        """,
    )
    print("catalog size", len(ids))
    for item in ids:
        print("-", item)


def main() -> None:
    # Skill / catalog sources
    make_skill_git(
        "anthropic-cybersecurity-skills",
        "Anthropic Cybersecurity Skills",
        "https://github.com/mukul975/Anthropic-Cybersecurity-Skills",
        "Read-only cybersecurity skill library (agentskills.io). Search/load playbooks into HADES — does not execute offensive scripts.",
        "Security",
        ["cybersecurity", "skills", "mitre", "playbooks"],
        autonomous=True,
        license_id="Apache-2.0",
        notes=(
            "Read-only skill lookup. This plugin exposes list/get/search over Markdown playbooks; "
            "it does not run offensive tooling from the upstream scripts/ folders."
        ),
    )
    make_skill_git(
        "agentic-awesome-skills",
        "Agentic Awesome Skills",
        "https://github.com/sickn33/agentic-awesome-skills",
        "AAS catalog of 2100+ agentic skills searchable from HADES via list/get/search.",
        "Developer",
        ["skills", "agents", "aas"],
        license_id="MIT",
    )
    make_skill_git(
        "humanizer",
        "Humanizer",
        "https://github.com/blader/humanizer",
        "Agent skill that removes AI-writing patterns from prose. Load the skill guidance via HADES tools.",
        "Developer",
        ["writing", "skills", "humanizer"],
        license_id="MIT",
    )
    make_catalog_git(
        "claude-code-best-practice",
        "Claude Code Best Practice",
        "https://github.com/shanraisshan/claude-code-best-practice",
        "Searchable Claude Code / agentic engineering best-practice docs for HADES.",
        "Developer",
        ["claude-code", "best-practices", "catalog"],
        license_id="MIT",
    )

    # Runnable tool/service plugins
    make_scrapling()
    make_puppeteer()
    make_headroom()
    make_agent_reach()
    make_rtk()
    make_searxng()
    make_kotaemon()
    refresh_index()


if __name__ == "__main__":
    main()
