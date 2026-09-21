from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.artifacts import ArtifactStore
from Data.modules.evidence import EvidenceService, EvidenceStore
from Data.modules.verification import (
    VerificationEngine,
    VerificationOutcome,
    VerificationRequirement,
)


class VerificationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "v.db"
        self.artifacts = ArtifactStore(self.db, root / "artifacts")
        self.artifacts.initialize()
        self.evidence_store = EvidenceStore(self.db)
        self.evidence_store.initialize()
        self.evidence = EvidenceService(self.evidence_store, artifacts=self.artifacts)
        self.engine = VerificationEngine(self.evidence_store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_empty_requirements_are_unmeasured(self) -> None:
        report = self.engine.verify([])
        self.assertEqual(report.outcome, VerificationOutcome.UNMEASURED)
        self.assertTrue(report.public_dict()["truth"]["unmeasured_is_not_passed"])

    def test_missing_evidence_is_unmeasured_not_passed(self) -> None:
        req = VerificationEngine.require_file(str(Path(self.tmp.name) / "missing.txt"))
        report = self.engine.verify([req])
        self.assertEqual(report.outcome, VerificationOutcome.UNMEASURED)
        self.assertEqual(report.requirements[0].outcome, VerificationOutcome.UNMEASURED)

    def test_verified_artifact_passes(self) -> None:
        artifact = self.artifacts.create_from_bytes(
            data=b"ok",
            artifact_type="text",
            producer="test",
            filename="a.txt",
            run_id="run-1",
        )
        self.evidence.claim_artifact_hash(artifact_id=artifact.artifact_id, run_id="run-1")
        req = VerificationEngine.require_artifact(artifact.artifact_id)
        report = self.engine.verify([req], run_id="run-1")
        self.assertEqual(report.outcome, VerificationOutcome.PASSED)

    def test_failed_file_evidence_fails(self) -> None:
        missing = str(Path(self.tmp.name) / "nope.txt")
        self.evidence.claim_file_exists(path=missing, run_id="run-2")
        req = VerificationRequirement(
            requirement_id="file",
            description="need file",
            evidence_kind="FILE_EXISTS",
            path=missing,
        )
        report = self.engine.verify([req], run_id="run-2")
        self.assertEqual(report.outcome, VerificationOutcome.FAILED)


if __name__ == "__main__":
    unittest.main()
