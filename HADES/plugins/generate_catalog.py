#!/usr/bin/env python3
"""Generate HADES plugin scaffolds for the curated upstream catalog."""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHARED = ROOT / "_shared"

EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}


def copy_shared(dest: Path, names: list[str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(SHARED / name, dest / name)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip() + ("\n" if not content.endswith("\n") else ""), encoding="utf-8")


def packer_local(plugin_id: str) -> str:
    return f'''#!/usr/bin/env python3
"""Pack {plugin_id} as a .HadesPlugin from the local plugin folder."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
from pack_lib import pack_local  # noqa: E402

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "dist")
    args = parser.parse_args()
    package = pack_local(plugin_dir=Path(__file__).resolve().parent, out_dir=args.out.resolve())
    print(f"Wrote {{package}} ({{package.stat().st_size / (1024 * 1024):.2f}} MiB)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


def packer_git(plugin_id: str, upstream: str, ref: str = "main") -> str:
    return f'''#!/usr/bin/env python3
"""Pack {plugin_id} as a .HadesPlugin from upstream git + overlay."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
from pack_lib import pack_git  # noqa: E402

UPSTREAM = "{upstream}"
DEFAULT_REF = "{ref}"

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
    )
    print(f"Wrote {{package}} ({{package.stat().st_size / (1024 * 1024):.2f}} MiB)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


def readme(name: str, source: str, tools: list[str], notes: str) -> str:
    tool_rows = "\n".join(f"| `{t}` | See manifest |" for t in tools)
    return f"""# {name} — HADES plugin

Installable `.HadesPlugin` wrapper around [{source}]({source}).

## Install in HADES

1. Build the package:

```bat
python plugins\\<plugin-id>\\pack_hadesplugin.py --out plugins\\<plugin-id>\\dist
```

2. HADES → **Plugins** → **ZIP / .HadesPlugin**
3. Approve dependency install when prompted
4. Enable the plugin when status is Ready
5. Run tools from the Plugins page (or via autonomous shortlist when `autonomous: true`)

## Tools

| Tool | Purpose |
|------|---------|
{tool_rows}

{notes}
"""


def catalog_tools(prefix_desc: str) -> list[dict]:
    return [
        {
            "name": "list_entries",
            "action": "list",
            "mode": "command",
            "description": f"List packaged files in {prefix_desc}.",
            "command": ["{python}", "catalog_bridge.py", "list", "--limit", "{limit}"],
            "input_schema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500}},
                "additionalProperties": False,
            },
        },
        {
            "name": "search",
            "action": "search",
            "mode": "command",
            "description": f"Search {prefix_desc} for a query string.",
            "command": ["{python}", "catalog_bridge.py", "search", "--query", "{query}", "--limit", "{limit}"],
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 200},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "read",
            "action": "read",
            "mode": "command",
            "description": f"Read one file from {prefix_desc}.",
            "command": ["{python}", "catalog_bridge.py", "read", "--path", "{path}", "--max-chars", "{max_chars}"],
            "input_schema": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 400},
                    "max_chars": {"type": "integer", "default": 12000, "minimum": 500, "maximum": 50000},
                },
                "additionalProperties": False,
            },
        },
    ]


def skill_tools(label: str) -> list[dict]:
    return [
        {
            "name": "list_skills",
            "action": "list",
            "mode": "command",
            "description": f"List skills/rules packaged in {label}.",
            "command": ["{python}", "skill_bridge.py", "list", "--limit", "{limit}"],
            "input_schema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 200, "minimum": 1, "maximum": 1000}},
                "additionalProperties": False,
            },
        },
        {
            "name": "get_skill",
            "action": "get",
            "mode": "command",
            "description": f"Load one skill/rule document from {label}.",
            "command": ["{python}", "skill_bridge.py", "get", "--skill", "{skill}", "--max-chars", "{max_chars}"],
            "input_schema": {
                "type": "object",
                "required": ["skill"],
                "properties": {
                    "skill": {"type": "string", "minLength": 1, "maxLength": 300},
                    "max_chars": {"type": "integer", "default": 16000, "minimum": 500, "maximum": 80000},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "search_skills",
            "action": "search",
            "mode": "command",
            "description": f"Search skills/rules in {label}.",
            "command": ["{python}", "skill_bridge.py", "search", "--query", "{query}", "--limit", "{limit}"],
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 200},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                },
                "additionalProperties": False,
            },
        },
    ]


def lifecycle_tools() -> list[dict]:
    return [
        {"name": "health", "action": "health", "mode": "command", "description": "Run declared healthcheck.", "command": "", "input_schema": EMPTY},
        {"name": "status", "action": "status", "mode": "command", "description": "Report managed service status.", "command": "", "input_schema": EMPTY},
        {"name": "logs", "action": "logs", "mode": "command", "description": "Read persisted service logs.", "command": "", "input_schema": EMPTY},
        {"name": "stop", "action": "stop", "mode": "command", "description": "Stop managed service.", "command": "", "input_schema": EMPTY},
    ]


def make_catalog_git(plugin_id: str, name: str, source: str, description: str, category: str, labels: list[str]) -> None:
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    copy_shared(overlay, ["catalog_bridge.py"])
    copy_shared(folder, ["catalog_bridge.py"])
    # Ensure python runtime without heavy deps
    write_text(overlay / "requirements.txt", "# catalog plugin — stdlib only\n")
    write_text(folder / "requirements.txt", "# catalog plugin — stdlib only\n")
    tools = catalog_tools(name)
    write_json(
        folder / "hades-plugin.json",
        {
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
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_git(plugin_id, source))
    write_text(folder / "README.md", readme(name, source, [t["name"] for t in tools], "Autonomous catalog search/read is enabled."))


def make_skill_git(plugin_id: str, name: str, source: str, description: str, category: str, labels: list[str], autonomous: bool = True) -> None:
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    copy_shared(overlay, ["skill_bridge.py"])
    copy_shared(folder, ["skill_bridge.py"])
    write_text(overlay / "requirements.txt", "# skill plugin — stdlib only\n")
    write_text(folder / "requirements.txt", "# skill plugin — stdlib only\n")
    tools = skill_tools(name)
    write_json(
        folder / "hades-plugin.json",
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
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_git(plugin_id, source))
    write_text(folder / "README.md", readme(name, source, [t["name"] for t in tools], "Use list/get/search to load skill content into HADES tool results."))


def make_markitdown() -> None:
    plugin_id = "markitdown"
    folder = ROOT / plugin_id
    copy_shared(folder, ["cli_bridge.py"])
    write_text(
        folder / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        from __future__ import annotations
        import argparse
        import json
        import sys
        from pathlib import Path

        def convert(path: str, output: str | None) -> dict:
            from markitdown import MarkItDown
            source = Path(path)
            if not source.is_file():
                raise SystemExit(f"input file not found: {path}")
            md = MarkItDown()
            result = md.convert(str(source))
            text = result.text_content or ""
            if output:
                out = Path(output)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
            return {"input": str(source), "output": output, "chars": len(text), "markdown": text[:20000], "truncated": len(text) > 20000}

        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            c = sub.add_parser("convert")
            c.add_argument("--path", required=True)
            c.add_argument("--output", default="")
            d = sub.add_parser("doctor")
            args = parser.parse_args()
            if args.cmd == "doctor":
                import cli_bridge
                print(json.dumps(cli_bridge.doctor(["markitdown"], ["markitdown"]), indent=2))
                return 0
            print(json.dumps(convert(args.path, args.output or None), ensure_ascii=False, indent=2))
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(folder / "requirements.txt", "markitdown[all]>=0.1.0\n")
    tools = [
        {
            "name": "doctor",
            "action": "doctor",
            "command": ["{python}", "hades_bridge.py", "doctor"],
            "description": "Check whether MarkItDown is importable in the plugin venv.",
            "input_schema": EMPTY,
        },
        {
            "name": "convert",
            "action": "convert",
            "command": ["{python}", "hades_bridge.py", "convert", "--path", "{path}", "--output", "{output}"],
            "description": "Convert a local file to Markdown via MarkItDown.",
            "input_schema": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "output": {"type": "string", "default": ""},
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
            "name": "MarkItDown",
            "version": "0.1.0",
            "description": "Convert documents (PDF, Office, HTML, and more) to Markdown for LLM pipelines. Upstream: microsoft/markitdown.",
            "runtime_type": "python",
            "entrypoint": "hades_bridge.py",
            "plugin_type": "tool",
            "category": "Data",
            "labels": ["markdown", "conversion", "documents"],
            "permissions": ["subprocess", "filesystem"],
            "autonomous": True,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/microsoft/markitdown",
            "license": "MIT",
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(folder / "README.md", readme("MarkItDown", "https://github.com/microsoft/markitdown", [t["name"] for t in tools], "Requires plugin-local pip install of markitdown[all]."))


def make_graphrag() -> None:
    plugin_id = "graphrag"
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
        import sys
        from pathlib import Path

        def _graphrag_bin() -> str:
            return shutil.which("graphrag") or "graphrag"

        def run(args: list[str], timeout: int = 600) -> dict:
            command = [_graphrag_bin(), *args]
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
            init = sub.add_parser("init")
            init.add_argument("--root", required=True)
            index = sub.add_parser("index")
            index.add_argument("--root", required=True)
            query = sub.add_parser("query")
            query.add_argument("--root", required=True)
            query.add_argument("--method", default="local")
            query.add_argument("--query", required=True)
            args = parser.parse_args()
            if args.cmd == "doctor":
                import cli_bridge
                payload = cli_bridge.doctor(["graphrag"], ["graphrag"])
                print(json.dumps(payload, indent=2))
                return 0
            if args.cmd == "init":
                Path(args.root).mkdir(parents=True, exist_ok=True)
                print(json.dumps(run(["init", "--root", args.root]), indent=2))
                return 0
            if args.cmd == "index":
                print(json.dumps(run(["index", "--root", args.root], timeout=3600), indent=2))
                return 0
            print(json.dumps(run(["query", "--root", args.root, "--method", args.method, "--query", args.query], timeout=600), indent=2))
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(folder / "requirements.txt", "graphrag>=2.0.0\n")
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Check GraphRAG install in the plugin venv.", "input_schema": EMPTY},
        {
            "name": "init",
            "action": "init",
            "command": ["{python}", "hades_bridge.py", "init", "--root", "{root}"],
            "description": "Initialize a GraphRAG project root.",
            "input_schema": {"type": "object", "required": ["root"], "properties": {"root": {"type": "string", "minLength": 1}}, "additionalProperties": False},
        },
        {
            "name": "index",
            "action": "index",
            "command": ["{python}", "hades_bridge.py", "index", "--root", "{root}"],
            "description": "Run GraphRAG indexing (can be expensive; configure LLM keys first).",
            "input_schema": {"type": "object", "required": ["root"], "properties": {"root": {"type": "string", "minLength": 1}}, "additionalProperties": False},
        },
        {
            "name": "query",
            "action": "query",
            "command": ["{python}", "hades_bridge.py", "query", "--root", "{root}", "--method", "{method}", "--query", "{query}"],
            "description": "Query an indexed GraphRAG project.",
            "input_schema": {
                "type": "object",
                "required": ["root", "query"],
                "properties": {
                    "root": {"type": "string", "minLength": 1},
                    "method": {"type": "string", "enum": ["local", "global", "drift", "basic"], "default": "local"},
                    "query": {"type": "string", "minLength": 1, "maxLength": 4000},
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
            "name": "GraphRAG",
            "version": "0.1.0",
            "description": "Microsoft GraphRAG CLI for graph-based retrieval-augmented generation. Indexing can be expensive and needs configured LLM credentials.",
            "runtime_type": "python",
            "entrypoint": "hades_bridge.py",
            "plugin_type": "tool",
            "category": "Research",
            "labels": ["rag", "graph", "knowledge"],
            "permissions": ["subprocess", "filesystem", "network"],
            "autonomous": False,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/microsoft/graphrag",
            "license": "MIT",
            "dependency_install": {"timeout_seconds": 1800, "stall_timeout_seconds": 900},
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(folder / "README.md", readme("GraphRAG", "https://github.com/microsoft/graphrag", [t["name"] for t in tools], "Autonomous use is disabled because indexing/query can incur LLM costs."))


def make_unsloth() -> None:
    plugin_id = "unsloth"
    folder = ROOT / plugin_id
    copy_shared(folder, ["cli_bridge.py"])
    write_text(
        folder / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        from __future__ import annotations
        import argparse
        import json
        import platform
        import sys

        def doctor() -> dict:
            import cli_bridge
            payload = cli_bridge.doctor(["unsloth", "torch"], ["nvidia-smi"])
            payload["python_version"] = sys.version
            payload["machine"] = platform.machine()
            payload["notes"] = [
                "Unsloth fine-tuning needs a suitable GPU stack on most workloads.",
                "Prefer the official Unsloth Desktop app for interactive training on Windows.",
                "This HADES plugin exposes environment checks and import diagnostics.",
            ]
            return payload

        def info() -> dict:
            import cli_bridge
            return {"unsloth": cli_bridge.module_status("unsloth"), "torch": cli_bridge.module_status("torch")}

        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            sub.add_parser("info")
            args = parser.parse_args()
            payload = doctor() if args.cmd == "doctor" else info()
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    # Keep requirements soft — full unsloth install is environment-specific.
    write_text(
        folder / "requirements.txt",
        """
        # Optional heavy deps. Install may fail without a compatible GPU/torch stack.
        # Operators can repair/reinstall after bringing a CUDA/torch environment.
        unsloth>=2024.1
        """,
    )
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Diagnose Unsloth/torch availability for local fine-tuning.", "input_schema": EMPTY},
        {"name": "info", "action": "info", "command": ["{python}", "hades_bridge.py", "info"], "description": "Report imported Unsloth/torch module versions.", "input_schema": EMPTY},
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "Unsloth",
            "version": "0.1.0",
            "description": "Environment diagnostics for Unsloth local LLM training/runtime. Full GPU training remains an operator-managed workload; use doctor/info from HADES Plugins.",
            "runtime_type": "python",
            "entrypoint": "hades_bridge.py",
            "plugin_type": "tool",
            "category": "Developer",
            "labels": ["llm", "finetune", "unsloth"],
            "permissions": ["subprocess"],
            "autonomous": True,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/unslothai/unsloth",
            "dependency_install": {"timeout_seconds": 3600, "stall_timeout_seconds": 1200},
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(folder / "README.md", readme("Unsloth", "https://github.com/unslothai/unsloth", [t["name"] for t in tools], "Dependency install can fail without CUDA/torch; plugin stays needs_review until repaired."))


def make_composio() -> None:
    plugin_id = "composio"
    folder = ROOT / plugin_id
    copy_shared(folder, ["cli_bridge.py"])
    write_text(
        folder / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        from __future__ import annotations
        import argparse
        import json
        import os
        import shutil
        import subprocess

        def doctor() -> dict:
            import cli_bridge
            payload = cli_bridge.doctor(["composio"], ["composio"])
            payload["has_api_key"] = bool(os.environ.get("COMPOSIO_API_KEY"))
            return payload

        def list_toolkits(query: str = "", limit: int = 30) -> dict:
            # Prefer CLI when present; fall back to SDK listing hints.
            binary = shutil.which("composio") or shutil.which("composio.exe")
            if binary:
                process = subprocess.run([binary, "apps"], capture_output=True, text=True, timeout=120, shell=False)
                text = (process.stdout or "") + "\\n" + (process.stderr or "")
                lines = [line for line in text.splitlines() if line.strip()]
                if query:
                    q = query.lower()
                    lines = [line for line in lines if q in line.lower()]
                return {"source": "cli", "exit_code": process.returncode, "items": lines[:limit]}
            try:
                from composio import Composio  # type: ignore
            except Exception as exc:  # noqa: BLE001
                return {"source": "sdk", "error": str(exc), "hint": "Set COMPOSIO_API_KEY and reinstall plugin deps."}
            return {
                "source": "sdk",
                "items": [],
                "note": "CLI unavailable; configure COMPOSIO_API_KEY and use Composio dashboard/docs for toolkit IDs.",
                "has_api_key": bool(os.environ.get("COMPOSIO_API_KEY")),
            }

        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            lst = sub.add_parser("list_toolkits")
            lst.add_argument("--query", default="")
            lst.add_argument("--limit", type=int, default=30)
            args = parser.parse_args()
            if args.cmd == "doctor":
                print(json.dumps(doctor(), indent=2))
            else:
                print(json.dumps(list_toolkits(args.query, args.limit), indent=2))
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(folder / "requirements.txt", "composio>=0.7.0\n")
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Check Composio SDK/CLI and COMPOSIO_API_KEY presence.", "input_schema": EMPTY},
        {
            "name": "list_toolkits",
            "action": "list",
            "command": ["{python}", "hades_bridge.py", "list_toolkits", "--query", "{query}", "--limit", "{limit}"],
            "description": "List/search Composio toolkits/apps available to this install.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 200},
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
            "name": "Composio",
            "version": "0.1.0",
            "description": "Composio toolkit discovery for agents. Execution of authenticated remote actions requires COMPOSIO_API_KEY.",
            "runtime_type": "python",
            "entrypoint": "hades_bridge.py",
            "plugin_type": "tool",
            "category": "Tool",
            "labels": ["integrations", "tools", "composio"],
            "permissions": ["subprocess", "network"],
            "autonomous": True,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/ComposioHQ/composio",
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(folder / "README.md", readme("Composio", "https://github.com/ComposioHQ/composio", [t["name"] for t in tools], "Set COMPOSIO_API_KEY in the HADES process environment before using authenticated toolkits."))


def make_gpt_crawler() -> None:
    plugin_id = "gpt-crawler"
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    write_text(
        overlay / "hades_bridge.mjs",
        '''
        import fs from "node:fs";
        import path from "node:path";
        import { fileURLToPath } from "node:url";

        const __dirname = path.dirname(fileURLToPath(import.meta.url));
        const args = process.argv.slice(2);
        const cmd = args[0];

        function readJson(filePath) {
          return JSON.parse(fs.readFileSync(filePath, "utf8"));
        }

        if (cmd === "doctor") {
          const pkg = readJson(path.join(__dirname, "package.json"));
          console.log(JSON.stringify({
            name: pkg.name,
            version: pkg.version,
            scripts: Object.keys(pkg.scripts || {}),
            hasConfigExample: fs.existsSync(path.join(__dirname, "config.ts")) || fs.existsSync(path.join(__dirname, "config.example.ts")),
          }, null, 2));
          process.exit(0);
        }

        if (cmd === "write-config") {
          const url = args[args.indexOf("--url") + 1];
          const match = args[args.indexOf("--match") + 1] || `${url.replace(/\\/$/, "")}/**`;
          const maxPages = Number(args[args.indexOf("--max-pages") + 1] || 50);
          const out = args[args.indexOf("--out") + 1] || path.join(__dirname, "hades-config.json");
          if (!url || url.startsWith("--")) {
            console.error("url is required");
            process.exit(1);
          }
          const config = {
            url,
            match,
            maxPagesToCrawl: maxPages,
            outputFileName: "hades-output.json",
          };
          fs.writeFileSync(out, JSON.stringify(config, null, 2));
          console.log(JSON.stringify({ wrote: out, config }, null, 2));
          process.exit(0);
        }

        console.error(`unknown command: ${cmd}`);
        process.exit(1);
        ''',
    )
    tools = [
        {
            "name": "doctor",
            "action": "doctor",
            "command": ["{npm}", "exec", "--", "node", "hades_bridge.mjs", "doctor"],
            "description": "Inspect gpt-crawler package metadata after npm install.",
            "input_schema": EMPTY,
        },
        {
            "name": "write_config",
            "action": "configure",
            "command": ["{npm}", "exec", "--", "node", "hades_bridge.mjs", "write-config", "--url", "{url}", "--match", "{match}", "--max-pages", "{max_pages}", "--out", "{out}"],
            "description": "Write a crawl config JSON for gpt-crawler.",
            "input_schema": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "minLength": 8},
                    "match": {"type": "string", "default": ""},
                    "max_pages": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
                    "out": {"type": "string", "default": "hades-config.json"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "start",
            "action": "start",
            "mode": "service",
            "command": ["{npm}", "run", "start"],
            "description": "Start the gpt-crawler web UI (default upstream start script).",
            "env": {"HOST": "127.0.0.1", "PORT": "3000"},
            "input_schema": EMPTY,
        },
        *lifecycle_tools(),
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "GPT Crawler",
            "version": "0.1.0",
            "description": "Builder.io gpt-crawler: crawl sites into knowledge files. Starts local UI on port 3000 when available.",
            "runtime_type": "node",
            "entrypoint": "start",
            "plugin_type": "service",
            "category": "Research",
            "labels": ["crawler", "knowledge", "gpt"],
            "permissions": ["subprocess", "network", "filesystem"],
            "autonomous": False,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/BuilderIO/gpt-crawler",
            "healthcheck": {
                "type": "http",
                "url": "http://127.0.0.1:3000/",
                "method": "GET",
                "expected_status": [200, 301, 302, 304],
                "timeout_seconds": 90,
                "interval_seconds": 1.0,
            },
            "tools": tools,
        },
    )
    # Local import stub so Plugin Manager can load the folder without packing.
    write_json(folder / "package.json", {"name": "gpt-crawler", "private": True, "scripts": {"start": "node -e \"console.log('pack upstream to run real UI')\""}})
    write_text(folder / "hades_bridge.mjs", (overlay / "hades_bridge.mjs").read_text(encoding="utf-8"))
    write_text(folder / "pack_hadesplugin.py", packer_git(plugin_id, "https://github.com/BuilderIO/gpt-crawler.git"))
    write_text(folder / "README.md", readme("GPT Crawler", "https://github.com/BuilderIO/gpt-crawler", [t["name"] for t in tools], "Use write_config then upstream npm scripts; start exposes the UI when health passes."))


def make_mcp_plugin(
    plugin_id: str,
    name: str,
    source: str,
    description: str,
    npm_package: str,
    category: str,
    labels: list[str],
    autonomous: bool,
    extra_server_args: list[str] | None = None,
) -> None:
    folder = ROOT / plugin_id
    copy_shared(folder, ["mcp_bridge.py"])
    server_args = ["-y", npm_package, *(extra_server_args or [])]
    write_text(
        folder / "hades_bridge.py",
        f'''
        #!/usr/bin/env python3
        from __future__ import annotations
        import argparse
        import json
        import shutil
        import sys
        from pathlib import Path

        import mcp_bridge

        def server_command() -> list[str]:
            npx = shutil.which("npx") or shutil.which("npx.cmd")
            if not npx:
                raise SystemExit("npx not found on PATH")
            return [npx, *{server_args!r}]

        def main() -> int:
            parser = argparse.ArgumentParser()
            parser.add_argument("--action", required=True, choices=["list_tools", "call_tool"])
            parser.add_argument("--tool", default="")
            parser.add_argument("--arguments", default="{{}}")
            parser.add_argument("--timeout", type=float, default=90.0)
            args = parser.parse_args()
            payload = mcp_bridge.run_session(
                server_command(),
                args.action,
                args.tool or None,
                args.arguments or None,
                args.timeout,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_json(
        folder / "package.json",
        {
            "name": f"hades-{plugin_id}",
            "version": "0.1.0",
            "private": True,
            "dependencies": {npm_package: "latest"},
        },
    )
    tools = [
        {
            "name": "list_tools",
            "action": "list",
            "mode": "command",
            "description": f"List MCP tools exposed by {name}.",
            "command": ["{python}", "hades_bridge.py", "--action", "list_tools", "--timeout", "90"],
            "input_schema": EMPTY,
        },
        {
            "name": "call_tool",
            "action": "call",
            "mode": "command",
            "description": f"Call one MCP tool from {name} with JSON arguments.",
            "command": [
                "{python}",
                "hades_bridge.py",
                "--action",
                "call_tool",
                "--tool",
                "{tool}",
                "--arguments",
                "{arguments}",
                "--timeout",
                "120",
            ],
            "input_schema": {
                "type": "object",
                "required": ["tool"],
                "properties": {
                    "tool": {"type": "string", "minLength": 1, "maxLength": 200},
                    "arguments": {"type": "string", "default": "{}", "description": "JSON object string"},
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
            "name": name,
            "version": "0.1.0",
            "description": description,
            "runtime_type": "node",
            "entrypoint": "list_tools",
            "plugin_type": "tool",
            "category": category,
            "labels": labels,
            "permissions": ["subprocess", "network", "filesystem"],
            "autonomous": autonomous,
            "hades_api": ">=0.4.1",
            "source": source,
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(
        folder / "README.md",
        readme(
            name,
            source,
            [t["name"] for t in tools],
            "HADES talks to the upstream MCP server through mcp_bridge.py (stdio JSON-RPC).",
        ),
    )


def make_activepieces() -> None:
    plugin_id = "activepieces"
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    write_text(
        overlay / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        from __future__ import annotations
        import argparse
        import json
        import shutil
        import subprocess

        def doctor() -> dict:
            return {
                "docker": shutil.which("docker") or shutil.which("docker.exe"),
                "compose_file": "docker-compose.yml",
                "hint": "Prefer official Activepieces docker compose; HADES start uses docker compose up when Docker is available.",
            }

        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            args = parser.parse_args()
            print(json.dumps(doctor(), indent=2))
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    # Also need a minimal package.json so runtime_type node dependency plan works if compose isn't used —
    # Activepieces is huge; we use docker compose as the service command.
    tools = [
        {
            "name": "doctor",
            "action": "doctor",
            "command": ["{python}", "hades_bridge.py", "doctor"],
            "description": "Check Docker availability for Activepieces.",
            "input_schema": EMPTY,
        },
        {
            "name": "start",
            "action": "start",
            "mode": "service",
            "command": ["docker", "compose", "up"],
            "description": "Start Activepieces via docker compose (requires Docker). UI typically on http://127.0.0.1:8080.",
            "input_schema": EMPTY,
        },
        *lifecycle_tools(),
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "Activepieces",
            "version": "0.1.0",
            "description": "Open-source Zapier alternative. Packaged from upstream with docker compose start + healthcheck on port 8080.",
            "runtime_type": "python",
            "entrypoint": "start",
            "plugin_type": "service",
            "category": "Tool",
            "labels": ["automation", "zapier", "docker"],
            "permissions": ["subprocess", "network"],
            "autonomous": False,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/activepieces/activepieces",
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
    write_text(folder / "pack_hadesplugin.py", packer_git(plugin_id, "https://github.com/activepieces/activepieces.git"))
    # Overlay python bridge + empty requirements for python runtime detection path
    write_text(overlay / "requirements.txt", "# no pip deps; Docker hosts Activepieces\n")
    write_text(folder / "requirements.txt", "# no pip deps; Docker hosts Activepieces\n")
    write_text(folder / "hades_bridge.py", (overlay / "hades_bridge.py").read_text(encoding="utf-8"))
    write_text(folder / "README.md", readme("Activepieces", "https://github.com/activepieces/activepieces", [t["name"] for t in tools], "Requires Docker. Configure `.env` from upstream examples before start."))


def make_voicestudio() -> None:
    plugin_id = "voicestudio"
    folder = ROOT / plugin_id
    write_text(
        folder / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        from __future__ import annotations
        import argparse
        import json
        import shutil

        def doctor() -> dict:
            return {
                "docker": shutil.which("docker") or shutil.which("docker.exe"),
                "default_image": "palashdeb/omnivoice-studio:stable",
                "ui": "http://127.0.0.1:3900",
                "notes": [
                    "Prefer official VoiceStudio desktop installers on Windows.",
                    "HADES start uses the published Docker image when Docker is available.",
                ],
            }

        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            args = parser.parse_args()
            print(json.dumps(doctor(), indent=2))
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(folder / "requirements.txt", "# docker-driven service\n")
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Check Docker availability for VoiceStudio.", "input_schema": EMPTY},
        {
            "name": "start",
            "action": "start",
            "mode": "service",
            "command": [
                "docker",
                "run",
                "--rm",
                "-p",
                "127.0.0.1:3900:3900",
                "--name",
                "hades-voicestudio",
                "palashdeb/omnivoice-studio:stable",
            ],
            "description": "Start VoiceStudio Docker image on http://127.0.0.1:3900.",
            "input_schema": EMPTY,
        },
        *lifecycle_tools(),
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "VoiceStudio",
            "version": "0.1.0",
            "description": "Local voice cloning/TTS/ASR studio (AGPL-3.0). HADES can start the published Docker image and healthcheck port 3900.",
            "runtime_type": "python",
            "entrypoint": "start",
            "plugin_type": "service",
            "category": "Tool",
            "labels": ["voice", "tts", "asr", "docker"],
            "permissions": ["subprocess", "network"],
            "autonomous": False,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/debpalash/VoiceStudio",
            "license": "AGPL-3.0",
            "healthcheck": {
                "type": "http",
                "url": "http://127.0.0.1:3900/",
                "method": "GET",
                "expected_status": [200, 301, 302, 304],
                "timeout_seconds": 180,
                "interval_seconds": 2.0,
            },
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(folder / "README.md", readme("VoiceStudio", "https://github.com/debpalash/VoiceStudio", [t["name"] for t in tools], "Docker required for the managed start tool. Desktop installers remain supported outside HADES."))


def make_project_nomad() -> None:
    plugin_id = "project-nomad"
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    copy_shared(overlay, ["catalog_bridge.py"])
    write_text(
        overlay / "hades_bridge.py",
        '''
        #!/usr/bin/env python3
        from __future__ import annotations
        import argparse
        import json
        from pathlib import Path

        ROOT = Path(__file__).resolve().parent

        def doctor() -> dict:
            compose = ROOT / "docker-compose.yml"
            alt = ROOT / "docker_compose.yaml"
            return {
                "compose_present": compose.exists() or alt.exists(),
                "compose_path": str(compose if compose.exists() else alt if alt.exists() else ""),
                "docs": [p.name for p in ROOT.glob("*.md")][:20],
                "warning": "Full NOMAD install uses a privileged installer; HADES only packages docs/helpers — do not run sudo install from autonomous tools.",
            }

        def main() -> int:
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="cmd", required=True)
            sub.add_parser("doctor")
            args = parser.parse_args()
            print(json.dumps(doctor(), indent=2))
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )
    write_text(overlay / "requirements.txt", "# docs/catalog only\n")
    write_text(folder / "requirements.txt", "# docs/catalog only\n")
    copy_shared(folder, ["catalog_bridge.py"])
    write_text(folder / "hades_bridge.py", (overlay / "hades_bridge.py").read_text(encoding="utf-8"))
    tools = [
        {"name": "doctor", "action": "doctor", "command": ["{python}", "hades_bridge.py", "doctor"], "description": "Inspect packaged NOMAD docs/compose presence.", "input_schema": EMPTY},
        *catalog_tools("Project NOMAD docs"),
    ]
    write_json(
        folder / "hades-plugin.json",
        {
            "format": 1,
            "id": plugin_id,
            "name": "Project NOMAD",
            "version": "0.1.0",
            "description": "Offline knowledge/education server docs and helpers. HADES exposes search/read over packaged docs; full host install remains a manual operator action.",
            "runtime_type": "python",
            "entrypoint": "catalog_bridge.py",
            "plugin_type": "tool",
            "category": "Research",
            "labels": ["offline", "knowledge", "education"],
            "permissions": ["subprocess"],
            "autonomous": True,
            "hades_api": ">=0.4.1",
            "source": "https://github.com/Crosstalk-Solutions/project-nomad",
            "license": "Apache-2.0",
            "tools": tools,
        },
    )
    write_text(folder / "pack_hadesplugin.py", packer_git(plugin_id, "https://github.com/Crosstalk-Solutions/project-nomad.git"))
    write_text(folder / "README.md", readme("Project NOMAD", "https://github.com/Crosstalk-Solutions/project-nomad", [t["name"] for t in tools], "Does not run the privileged upstream installer."))


def main() -> None:
    # Catalog / awesome lists
    make_catalog_git(
        "awesome-llm-apps",
        "Awesome LLM Apps",
        "https://github.com/Shubhamsaboo/awesome-llm-apps",
        "Searchable catalog of open-source LLM apps and agents for inspiration and research.",
        "Research",
        ["awesome", "llm", "catalog"],
    )
    make_catalog_git(
        "awesome-claude-code",
        "Awesome Claude Code",
        "https://github.com/hesreallyhim/awesome-claude-code",
        "Searchable awesome-list of Claude Code resources.",
        "Developer",
        ["awesome", "claude-code", "catalog"],
    )
    make_catalog_git(
        "awesome-claude-code-toolkit",
        "Awesome Claude Code Toolkit",
        "https://github.com/rohitg00/awesome-claude-code-toolkit",
        "Searchable toolkit catalog for Claude Code workflows.",
        "Developer",
        ["awesome", "claude-code", "toolkit"],
    )

    # Skill packs
    make_skill_git(
        "ponytail",
        "Ponytail",
        "https://github.com/DietrichGebert/ponytail",
        "Minimal-code agent skill/ruleset. Load skills into HADES tool results for coding guidance.",
        "Developer",
        ["skills", "agents", "minimal"],
    )
    make_skill_git(
        "antigravity-awesome-skills",
        "Antigravity Awesome Skills",
        "https://github.com/benjaminasterA/antigravity-awesome-skills",
        "Packaged agent skills collection searchable from HADES.",
        "Developer",
        ["skills", "agents"],
    )
    make_skill_git(
        "ecc",
        "Everything Claude Code (ECC)",
        "https://github.com/affaan-m/ECC",
        "ECC agents/skills/rules catalog for harness-style coding workflows, exposed via list/get/search tools.",
        "Developer",
        ["ecc", "skills", "agents"],
    )
    make_skill_git(
        "design-dna",
        "Design DNA",
        "https://github.com/zanwei/design-dna",
        "Design DNA skill: extract/apply visual design identity as structured JSON guidance.",
        "Developer",
        ["design", "skills", "ui"],
    )

    # Slim local tool plugins
    make_markitdown()
    make_graphrag()
    make_unsloth()
    make_composio()
    make_voicestudio()

    # Git-sourced app/services
    make_gpt_crawler()
    make_activepieces()
    make_project_nomad()

    # MCP bridges
    make_mcp_plugin(
        "chrome-devtools-mcp",
        "Chrome DevTools MCP",
        "https://github.com/ChromeDevTools/chrome-devtools-mcp",
        "Drive Chrome DevTools via MCP from HADES using list_tools/call_tool bridges.",
        "chrome-devtools-mcp",
        "Browser",
        ["chrome", "devtools", "mcp"],
        autonomous=False,
        extra_server_args=["--no-usage-statistics"],
    )
    make_mcp_plugin(
        "desktop-commander-mcp",
        "Desktop Commander MCP",
        "https://github.com/wonderwhy-er/DesktopCommanderMCP",
        "Desktop Commander MCP bridge for terminal/filesystem tools. Powerful host access — autonomous disabled.",
        "@wonderwhy-er/desktop-commander",
        "Developer",
        ["mcp", "desktop", "terminal"],
        autonomous=False,
    )

    # Index
    ids = sorted(
        p.name
        for p in ROOT.iterdir()
        if p.is_dir() and (p / "hades-plugin.json").exists()
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

        Shared bridges live in `plugins/_shared/`.
        """,
    )
    print("generated", len(ids), "plugins")
    for item in ids:
        print("-", item)


if __name__ == "__main__":
    main()
