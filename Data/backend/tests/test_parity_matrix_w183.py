"""W183 — Python vs Rust parity matrix exists; comparable ops PASS or documented."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "build_parity_matrix.py"
MATRIX = ROOT / "Data" / "backend" / "tests" / "parity_matrix.json"


class ParityMatrixW183(unittest.TestCase):
    def test_matrix_exists_and_comparable_ops_pass_or_documented(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lev-w183-") as tmp:
            out = Path(tmp) / "parity_matrix.json"
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--rows", "24", "--out", str(out)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertTrue(out.is_file())
            report = json.loads(out.read_text(encoding="utf-8"))

            MATRIX.parent.mkdir(parents=True, exist_ok=True)
            MATRIX.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.assertTrue(MATRIX.is_file())

            self.assertEqual(report.get("wave"), "W183")
            ops = report.get("operations") or []
            self.assertGreaterEqual(len(ops), 6)
            intentional = {
                str(item.get("operation"))
                for item in (report.get("intentionalDifferences") or [])
            }
            failures = [e for e in ops if e.get("status") == "FAIL"]
            for fail in failures:
                op = str(fail.get("operation"))
                self.assertIn(
                    op,
                    intentional,
                    f"{op} FAILED without intentionalDifferences documentation: {fail}",
                )
            # If rust is present, expect all comparable PASS
            if report.get("nativeBinary"):
                comparable = [e for e in ops if e.get("status") in {"PASS", "FAIL"}]
                self.assertTrue(comparable)
                undocumented_fail = [
                    e
                    for e in comparable
                    if e.get("status") == "FAIL"
                    and str(e.get("operation")) not in intentional
                ]
                self.assertEqual(undocumented_fail, [])
                # Prefer full pass when binary available
                self.assertTrue(
                    report.get("summary", {}).get("allComparablePass")
                    or intentional,
                    report.get("summary"),
                )


if __name__ == "__main__":
    unittest.main()
