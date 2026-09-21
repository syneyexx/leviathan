from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from build_agent import BuildAgentService
from coding_agent import CodingAgentService


class CodingAgentRepairLogPathBoundaryTests(unittest.TestCase):
    def test_test_log_parent_relative_path_is_not_loaded_into_model_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            work = base / "isolated" / "work"
            work.mkdir(parents=True)
            outside = base / "outside.py"
            marker = "ASTRA_OUTSIDE_REPAIR_CONTEXT_SECRET"
            outside.write_text(marker + " = True\n", encoding="utf-8")

            captured: dict[str, Any] = {}

            async def fake_chat(request: dict[str, Any]) -> dict[str, Any]:
                captured["request"] = request
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"edits": []}',
                            }
                        }
                    ]
                }

            service = CodingAgentService(BuildAgentService(base / "hades-workspace"))
            service.propose_repair(
                work,
                goal="Fix the failing test",
                diagnosis=None,
                test_result={
                    "stdout": "FAILED ../../outside.py\nAssertionError: deterministic failure\n",
                    "stderr": "",
                },
                previous_signatures=set(),
                chat_fn=fake_chat,
                model_id="local-test-model",
            )

            request = captured.get("request") or {}
            messages = request.get("messages") or []
            prompt = "\n".join(str(item.get("content") or "") for item in messages if isinstance(item, dict))
            self.assertNotIn(marker, prompt)
            self.assertNotIn("../../outside.py", prompt)


if __name__ == "__main__":
    unittest.main()
