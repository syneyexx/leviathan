from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reasoning.long_task_resume import RunIdentity, SideEffectLedger, make_idempotency_key


class SideEffectLedgerPersistenceHonestyTests(unittest.TestCase):
    def test_record_intent_does_not_claim_success_when_snapshot_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            persist_path = Path(temp_dir) / "ledger.json"
            ledger = SideEffectLedger(str(persist_path))
            identity = RunIdentity(run_id="run-1", step_id="step-1", generation=1)
            payload = {"value": 1}
            key = make_idempotency_key(
                run_id="run-1",
                step_id="step-1",
                effect_kind="fixture_effect",
                payload=payload,
            )

            real_write_text = Path.write_text

            def fail_ledger_write(path: Path, *args, **kwargs):
                if path.name.endswith(".tmp") and path.parent == persist_path.parent:
                    raise OSError("simulated durable ledger write failure")
                return real_write_text(path, *args, **kwargs)

            with patch.object(Path, "write_text", new=fail_ledger_write):
                result = ledger.record_intent(
                    identity=identity,
                    effect_kind="fixture_effect",
                    payload=payload,
                )

            self.assertFalse(result.get("ok"), "durable intent must not report success after snapshot write failure")
            self.assertEqual(result.get("reason"), "persistence_failed")
            self.assertFalse(persist_path.exists(), "fault injection must leave no durable snapshot")
            self.assertIsNone(ledger.get_by_key(key), "failed persistence must roll back in-memory intent state")


if __name__ == "__main__":
    unittest.main()
