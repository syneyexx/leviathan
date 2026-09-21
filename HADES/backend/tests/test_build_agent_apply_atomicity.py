from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_agent import BuildAgentService


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BuildAgentApplyAtomicityTests(unittest.TestCase):
    def test_mid_apply_copy_failure_does_not_leave_partial_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "source"
            source.mkdir()
            source_a = source / "a.txt"
            source_b = source / "b.txt"
            source_a.write_text("a-before\n", encoding="utf-8")
            source_b.write_text("b-before\n", encoding="utf-8")

            service = BuildAgentService(base / "hades-workspace")
            run_id = "apply-atomicity"
            run_root = service.runs_root / run_id
            work = run_root / "work"
            work.mkdir(parents=True)
            work_a = work / "a.txt"
            work_b = work / "b.txt"
            work_a.write_text("a-after\n", encoding="utf-8")
            work_b.write_text("b-after\n", encoding="utf-8")
            (run_root / "meta.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "source": str(source),
                        "work_root": str(work),
                        "baseline_commit": None,
                        "baseline_hashes": {
                            "a.txt": _sha256(source_a),
                            "b.txt": _sha256(source_b),
                        },
                    }
                ),
                encoding="utf-8",
            )

            real_copy2 = shutil.copy2

            def fail_second_apply(src: str | Path, dst: str | Path, *args, **kwargs):
                src_path = Path(src)
                dst_path = Path(dst)
                if src_path == work_b and dst_path == source_b:
                    raise OSError("injected second-file apply failure")
                return real_copy2(src, dst, *args, **kwargs)

            outcome = None
            with patch("build_agent.shutil.copy2", side_effect=fail_second_apply):
                try:
                    outcome = service.apply_to_source(run_id, approved=True)
                except OSError:
                    pass

            self.assertEqual(source_a.read_text(encoding="utf-8"), "a-before\n")
            self.assertEqual(source_b.read_text(encoding="utf-8"), "b-before\n")
            if outcome is not None:
                self.assertFalse(bool(outcome.get("applied")))


if __name__ == "__main__":
    unittest.main()
