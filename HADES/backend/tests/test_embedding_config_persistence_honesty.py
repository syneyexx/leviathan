from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from embeddings import PersistentEmbeddingIndex


class EmbeddingConfigPersistenceHonestyTests(unittest.TestCase):
    def test_failed_model_config_persistence_does_not_mutate_live_index_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = PersistentEmbeddingIndex(
                Path(temp_dir) / "embeddings.sqlite3",
                model_id="model-a",
                index_version=1,
                dimension=3,
            )
            before = index.to_dict()

            with patch.object(index, "_set_meta", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    index.configure_model("model-b", dimension=4)

            after = index.to_dict()
            self.assertEqual(after["model_id"], before["model_id"])
            self.assertEqual(after["index_version"], before["index_version"])
            self.assertEqual(after["dimension"], before["dimension"])
            self.assertEqual(after["indexed_count"], before["indexed_count"])
            self.assertEqual(after["deleted_count"], before["deleted_count"])


if __name__ == "__main__":
    unittest.main()
