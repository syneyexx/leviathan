
"""DSPy compile must fail closed when program persistence fails."""
from __future__ import annotations
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_bridge():
    spec = importlib.util.spec_from_file_location("dspy_hades_bridge", ROOT / "hades_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class DspyCompileHonestyTests(unittest.TestCase):
    def test_compile_save_and_fallback_failure_is_not_ok(self) -> None:
        bridge = load_bridge()
        with tempfile.TemporaryDirectory() as tmp:
            train = Path(tmp) / "train.json"
            train.write_text(json.dumps([{"question": "q", "answer": "a"}]), encoding="utf-8")
            out = Path(tmp) / "program.json"

            class _Prog:
                demos = []
                def save(self, _path):
                    raise RuntimeError("save api broken")

            class _Ex:
                def __init__(self, question, answer):
                    self.question = question
                    self.answer = answer
                def with_inputs(self, *_a, **_k):
                    return self

            fake_dspy = ModuleType("dspy")
            fake_dspy.LM = mock.Mock(return_value=mock.Mock())
            fake_dspy.Predict = mock.Mock(return_value=_Prog())
            fake_dspy.Example = mock.Mock(side_effect=lambda **kw: _Ex(**kw))
            fake_dspy.Signature = type("Signature", (), {})
            fake_dspy.InputField = mock.Mock()
            fake_dspy.OutputField = mock.Mock()
            fake_dspy.configure = mock.Mock()

            with mock.patch.dict(sys.modules, {"dspy": fake_dspy}), mock.patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                payload = bridge.compile_program(str(train), "http://127.0.0.1:1234/v1", "local-model", "k", str(out))
            self.assertFalse(payload.get("ok"))
            self.assertTrue(payload.get("error"))


if __name__ == "__main__":
    unittest.main()
