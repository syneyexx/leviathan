from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugin_dependency_runtime import DependencyCommandRunner


class _CompletedProcess:
    pid = 4242
    returncode = 0

    def __init__(self) -> None:
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        return 0


class PluginDependencyEnvironmentSecurityTests(unittest.TestCase):
    def _captured_env(self, runtime: str, env: dict[str, str]) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = DependencyCommandRunner(
                log_path=root / "deps.log",
                status_path=root / "deps.status.json",
                runtime=runtime,
                command_index=1,
                total_commands=1,
                timeout_seconds=5,
                stall_timeout_seconds=0,
            )
            with patch("plugin_dependency_runtime.subprocess.Popen", return_value=_CompletedProcess()) as popen:
                runner.run(["dependency-tool", "install"], cwd=root, env=env)
            return dict(popen.call_args.kwargs["env"])

    def test_node_dependency_env_strips_unrelated_secrets_but_keeps_npm_auth(self) -> None:
        child = self._captured_env(
            "node",
            {
                "PATH": "/runtime/bin",
                "OPENAI_API_KEY": "openai-secret",
                "HADES_LM_STUDIO_API_KEY": "hades-secret",
                "AWS_SECRET_ACCESS_KEY": "aws-secret",
                "NPM_TOKEN": "npm-private-registry-token",
            },
        )
        self.assertEqual(child.get("PATH"), "/runtime/bin")
        self.assertEqual(child.get("NPM_TOKEN"), "npm-private-registry-token")
        self.assertNotIn("OPENAI_API_KEY", child)
        self.assertNotIn("HADES_LM_STUDIO_API_KEY", child)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", child)

    def test_python_dependency_env_keeps_pip_registry_but_not_other_runtime_tokens(self) -> None:
        child = self._captured_env(
            "python",
            {
                "PATH": "/runtime/bin",
                "ANTHROPIC_API_KEY": "anthropic-secret",
                "NPM_TOKEN": "npm-token",
                "PIP_INDEX_URL": "https://user:pass@example.invalid/simple",
                "PIP_PASSWORD": "python-registry-password",
            },
        )
        self.assertEqual(child.get("PIP_INDEX_URL"), "https://user:pass@example.invalid/simple")
        self.assertEqual(child.get("PIP_PASSWORD"), "python-registry-password")
        self.assertNotIn("ANTHROPIC_API_KEY", child)
        self.assertNotIn("NPM_TOKEN", child)


if __name__ == "__main__":
    unittest.main()
