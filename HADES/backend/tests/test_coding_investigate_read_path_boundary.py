from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_investigate import InteractiveCodingInvestigator, InvestigateAction


class CodingInvestigateReadPathBoundaryTests(unittest.TestCase):
    def test_parent_relative_read_file_outside_workspace_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.txt"
            marker = "ASTRA_OUTSIDE_INVESTIGATE_SECRET"
            outside.write_text(marker + "\n", encoding="utf-8")

            investigator = InteractiveCodingInvestigator(root)
            observation = investigator.execute(
                InvestigateAction(
                    kind="read_file",
                    args={"path": "../outside.txt"},
                    rationale="workspace-boundary-regression",
                )
            )

            self.assertNotEqual(observation.status, "ok")
            self.assertNotIn(marker, str(observation.to_dict()))

    def test_parent_relative_read_span_outside_workspace_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.txt"
            marker = "ASTRA_OUTSIDE_INVESTIGATE_SPAN_SECRET"
            outside.write_text(marker + "\nsecond line\n", encoding="utf-8")

            investigator = InteractiveCodingInvestigator(root)
            observation = investigator.execute(
                InvestigateAction(
                    kind="read_span",
                    args={"path": "../outside.txt", "start_line": 1, "end_line": 1},
                    rationale="workspace-boundary-regression",
                )
            )

            self.assertNotEqual(observation.status, "ok")
            self.assertNotIn(marker, str(observation.to_dict()))

    def test_relative_js_import_resolver_cannot_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            nested = root / "nested"
            nested.mkdir(parents=True)
            (nested / "main.ts").write_text(
                "import value from '../../outside';\nconsole.log(value);\n",
                encoding="utf-8",
            )
            outside = base / "outside.ts"
            outside.write_text("export default 'ASTRA_OUTSIDE_JS_SECRET';\n", encoding="utf-8")

            investigator = InteractiveCodingInvestigator(root)
            resolved = investigator._resolve_relative_js("nested/main.ts", "../../outside")

            self.assertIsNone(resolved)


if __name__ == "__main__":
    unittest.main()
