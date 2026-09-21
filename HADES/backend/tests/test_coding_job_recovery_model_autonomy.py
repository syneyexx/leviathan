"""Job recovery retains model/autonomy/task settings across store reload."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_jobs import CodingJobStore
from coding_job_control import empty_checkpoint


class CodingJobRecoveryContractTests(unittest.TestCase):
    def test_persisted_params_retain_model_and_autonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_root = Path(tmp) / "jobs"
            store = CodingJobStore(jobs_root)
            try:
                params = {
                    "source_repo": "/tmp/repo",
                    "goal": "fix it",
                    "original_goal": "fix it",
                    "test_suite": "auto",
                    "test_args": [],
                    "max_attempts": 2,
                    "strategy": "fast",
                    "selector_mode": "deterministic",
                    "model_id": "ui-selected-model",
                    "use_omniroute": False,
                    "auto_repair": True,
                    "autonomy_profile": "managed_workspace_modify",
                    "task_type": "bugfix",
                    "project_id": "proj-1",
                    "edits": [],
                    "repair_waves": [],
                    "config_snapshot": {
                        "model_id": "ui-selected-model",
                        "autonomy_profile": "managed_workspace_modify",
                    },
                }
                # Avoid live worker threads: write a durable status + execution payload directly.
                jid = "cjob_recovery_model"
                job_dir = store._job_dir(jid)
                job_dir.mkdir(parents=True, exist_ok=True)
                now = time.time()
                record = {
                    "id": jid,
                    "status": "paused",
                    "created_at": now,
                    "updated_at": now,
                    "params": params,
                    "result": None,
                    "error": None,
                    "cancel_requested": False,
                    "redirect_notes": [],
                    "instructions": [],
                    "processed_instruction_version": 0,
                    "events_tail": [],
                    "event_seq": 0,
                    "checkpoint": empty_checkpoint(phase="paused"),
                    "execution_payload": {},
                    "status_evidence": [],
                }
                store._write(jid, record)
                store._persist_execution_payload(jid, params, checkpoint=record["checkpoint"])

                loaded = store.get(jid)
                payload_params = (loaded.get("execution_payload") or {}).get("params") or {}
                self.assertEqual(payload_params.get("model_id"), "ui-selected-model")
                self.assertEqual(payload_params.get("autonomy_profile"), "managed_workspace_modify")
                self.assertEqual(payload_params.get("task_type"), "bugfix")
                self.assertEqual(payload_params.get("selector_mode"), "deterministic")
                self.assertEqual(payload_params.get("test_suite"), "auto")
                self.assertFalse(payload_params.get("use_omniroute"))

                # New store instance (process recovery).
                store2 = CodingJobStore(jobs_root)
                try:
                    rec2 = store2.get(jid)
                    params2 = (rec2.get("execution_payload") or {}).get("params") or rec2.get("params") or {}
                    self.assertEqual(params2.get("model_id"), "ui-selected-model")
                    self.assertEqual(params2.get("autonomy_profile"), "managed_workspace_modify")
                    self.assertNotEqual(params2.get("autonomy_profile"), "reviewable_result")
                finally:
                    store2._executor.shutdown(wait=False, cancel_futures=True)
            finally:
                store._executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
