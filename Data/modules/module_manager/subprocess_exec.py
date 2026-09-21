from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


class SubprocessModuleExecutor:
    """Execute a module operation in an isolated Python subprocess.

    Used for untrusted ModelData plugins when isolation=SUBPROCESS.
    Does not grant gateway authority — still advisory/module-local only.
    """

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def execute(
        self,
        *,
        entrypoint: str,
        operation: str,
        arguments: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        script = f"""
import json, importlib, sys
payload = json.loads(sys.stdin.read())
module_name, _, attr = payload["entrypoint"].partition(":")
mod = importlib.import_module(module_name)
factory = getattr(mod, attr)
instance = factory()
from Data.modules.module_manager.types import ModuleContext
ctx_data = payload.get("context") or {{}}
instance.initialize(ModuleContext(
    database_path=ctx_data.get("database_path"),
    data_root=ctx_data.get("data_root"),
    feature_flags=ctx_data.get("feature_flags") or {{}},
    metadata=ctx_data.get("metadata") or {{}},
))
result = instance.execute(payload["operation"], payload.get("arguments") or {{}})
print(json.dumps(result.public_dict()))
instance.shutdown()
"""
        payload = {
            "entrypoint": entrypoint,
            "operation": operation,
            "arguments": dict(arguments),
            "context": dict(context or {}),
        }
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                cwd=str(Path(__file__).resolve().parents[3]),  # repo root
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "TIMEOUT",
                "error": f"Subprocess timed out after {self.timeout_seconds}s",
                "truth": {"subprocess_isolation": True},
            }
        if proc.returncode != 0:
            return {
                "status": "FAILED",
                "error": (proc.stderr or proc.stdout or "subprocess failed").strip()[:2000],
                "truth": {"subprocess_isolation": True},
            }
        try:
            return json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            return {
                "status": "FAILED",
                "error": f"Invalid subprocess JSON: {exc}; raw={proc.stdout[:500]!r}",
                "truth": {"subprocess_isolation": True},
            }
