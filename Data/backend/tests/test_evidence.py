from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.artifacts import ArtifactStore
from Data.modules.evidence import (
    EvidenceKind,
    EvidenceService,
    EvidenceStatus,
    EvidenceStore,
)
from Data.modules.observations import ObservationStore


class EvidenceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "ev.db"
        self.artifacts = ArtifactStore(self.db_path, self.root / "artifacts")
        self.artifacts.initialize()
        self.observations = ObservationStore(self.db_path)
        self.observations.initialize()
        self.store = EvidenceStore(self.db_path)
        self.store.initialize()
        self.service = EvidenceService(
            self.store,
            artifacts=self.artifacts,
            observations=self.observations,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_artifact_hash_verified(self) -> None:
        artifact = self.artifacts.create_from_bytes(
            data=b"evidence-bytes",
            artifact_type="text",
            producer="test",
            filename="ev.txt",
        )
        record = self.service.claim_artifact_hash(artifact_id=artifact.artifact_id)
        self.assertEqual(record.kind, EvidenceKind.ARTIFACT_HASH)
        self.assertEqual(record.status, EvidenceStatus.VERIFIED)
        self.assertTrue(record.public_dict()["truth"]["observation_is_not_evidence"])

    def test_artifact_hash_fails_on_tamper(self) -> None:
        artifact = self.artifacts.create_from_bytes(
            data=b"clean",
            artifact_type="text",
            producer="test",
            filename="t.txt",
        )
        Path(artifact.path).write_bytes(b"tampered")
        record = self.service.claim_artifact_hash(artifact_id=artifact.artifact_id)
        self.assertEqual(record.status, EvidenceStatus.FAILED)

    def test_file_exists_and_missing(self) -> None:
        path = self.root / "present.txt"
        path.write_text("x", encoding="utf-8")
        ok = self.service.claim_file_exists(path=str(path))
        self.assertEqual(ok.status, EvidenceStatus.VERIFIED)
        bad = self.service.claim_file_exists(path=str(self.root / "missing.txt"))
        self.assertEqual(bad.status, EvidenceStatus.FAILED)

    def test_observation_ref_existence_only(self) -> None:
        obs, _ = self.observations.record_execution(
            request_id="r1",
            capability_id="file.read",
            status="COMPLETED",
            side_effects=["READ"],
            output={"ok": True},
        )
        record = self.service.claim_observation_ref(observation_id=obs.observation_id)
        self.assertEqual(record.status, EvidenceStatus.VERIFIED)
        self.assertTrue(record.metadata.get("existence_only"))
        missing = self.service.claim_observation_ref(observation_id="nope")
        self.assertEqual(missing.status, EvidenceStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
