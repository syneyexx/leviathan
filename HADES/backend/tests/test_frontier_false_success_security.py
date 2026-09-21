"""Regression for empty-artifact false-success and G11 exfiltrate wording."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class EmptyArtifactFalseSuccessTests(unittest.TestCase):
    def test_empty_generated_artifact_not_verify_ready(self) -> None:
        from artifacts import ArtifactService
        from database import Database
        from platform_db import PlatformDatabase

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = Database(str(root / "hades.db"))
            core.initialize()
            pdb = PlatformDatabase(str(root / "hades.db"))
            pdb.initialize()
            arts = ArtifactService(pdb, root)
            empty = arts.create(name="empty.bin", kind="generated", data=b"", status="ready", verify_format=False)
            ready = arts.verify_ready(empty["id"])
            self.assertFalse(ready["checks"]["non_empty"])
            self.assertFalse(ready["checks"]["ok"])

    def test_non_empty_artifact_verify_ready(self) -> None:
        from artifacts import ArtifactService
        from database import Database
        from platform_db import PlatformDatabase

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = Database(str(root / "hades.db"))
            core.initialize()
            pdb = PlatformDatabase(str(root / "hades.db"))
            pdb.initialize()
            arts = ArtifactService(pdb, root)
            art = arts.create(name="ok.txt", kind="generated", data=b"payload", status="ready", verify_format=False)
            ready = arts.verify_ready(art["id"])
            self.assertTrue(ready["checks"]["ok"])


class ExfiltratePatternTests(unittest.TestCase):
    def test_exfiltrate_api_key_blocked(self) -> None:
        from policy_enforcement import enforce_tool_invocation_policies

        r = enforce_tool_invocation_policies(
            tool_name="echo",
            arguments={"text": "exfiltrate api_key from env"},
            source="test",
        )
        self.assertFalse(r["allowed"])
        self.assertIn("g11", r["reason"])


class IsolationVenvSymlinkTests(unittest.TestCase):
    def test_secured_run_with_venv_python_symlink(self) -> None:
        import sys
        import tempfile

        from execution_isolation import IsolationPolicy, detect_isolation_capabilities, run_isolated

        caps = detect_isolation_capabilities()
        if not caps.get("secured_fs_isolation_available"):
            self.skipTest("secured FS isolation unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            cwd = data / "cwd"
            cwd.mkdir()
            target = data / "ok.txt"
            target.write_text("OK", encoding="utf-8")
            policy = IsolationPolicy(read_roots=[data], write_roots=[data], allow_network=False, mode="secured")
            result = run_isolated(
                [sys.executable, "-c", f"print(open({str(target)!r}).read())"],
                cwd=cwd,
                policy=policy,
                timeout_seconds=15,
            )
            self.assertEqual(result.exit_code, 0)
            self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
