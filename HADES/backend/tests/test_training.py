import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_routes import mount_training_routes
from training_service import TrainingWorkspace, format_training_example


class _FakeDatabase:
    def __init__(self, path: Path, *, file_read_policy: str = "ask", network_policy: str = "ask") -> None:
        self.path = path
        self.values = {
            "file_read_policy": file_read_policy,
            "network_policy": network_policy,
        }

    def get_settings(self) -> dict[str, str]:
        return dict(self.values)


class TrainingWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = TrainingWorkspace(self.root / "training")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_from_database_uses_production_path_contract(self) -> None:
        database = _FakeDatabase(self.root / "state" / "hades.db")
        workspace = TrainingWorkspace.from_database(database)
        self.assertEqual(workspace.root, (database.path.parent / "training").resolve())

    def test_common_sft_shapes_are_formatted_without_inventing_content(self) -> None:
        self.assertEqual(format_training_example({"text": "  hello  "}), "hello")
        self.assertEqual(
            format_training_example({"prompt": "Vraag: ", "completion": "antwoord"}),
            "Vraag: antwoord",
        )
        rendered = format_training_example(
            {"instruction": "Vat samen", "input": "bron", "output": "samenvatting"}
        )
        self.assertIn("Vat samen", rendered)
        self.assertIn("bron", rendered)
        self.assertIn("samenvatting", rendered)
        chat = format_training_example(
            {"messages": [{"role": "user", "content": "Hoi"}, {"role": "assistant", "content": "Hallo"}]}
        )
        self.assertIn("<user>\nHoi", chat)
        self.assertIn("<assistant>\nHallo", chat)
        self.assertEqual(format_training_example({"text": "one", "custom": "two"}, {"text_field": "custom"}), "two")

    def test_jsonl_registration_is_zero_copy_and_persistent(self) -> None:
        source = self.root / "large-source.jsonl"
        source.write_text(
            "\n".join(
                [
                    json.dumps({"prompt": "p1", "completion": "c1"}),
                    json.dumps({"prompt": "p2", "completion": "c2"}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        registered = self.workspace.register_local(source, name="Dataset A")
        self.assertEqual(registered["path"], str(source.resolve()))
        self.assertEqual(registered["source_type"], "local")
        self.assertEqual(registered["columns"], ["prompt", "completion"])
        self.assertFalse((self.workspace.uploads_dir / source.name).exists())

        reopened = TrainingWorkspace(self.workspace.root)
        loaded = reopened.get_dataset(registered["id"])
        self.assertEqual(loaded["name"], "Dataset A")
        self.assertEqual(loaded["path"], str(source.resolve()))
        self.assertEqual(len(reopened.list_datasets()), 1)

    def test_jsonl_invalid_record_fails_with_line_number(self) -> None:
        source = self.root / "bad.jsonl"
        source.write_text('{"text":"ok"}\nnot-json\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "regel 2"):
            self.workspace.inspect_local(source)

    def test_mapping_must_reference_preview_column(self) -> None:
        source = self.root / "train.csv"
        source.write_text("question,answer\nq,a\n", encoding="utf-8")
        registered = self.workspace.register_local(source)
        updated = self.workspace.update_mapping(registered["id"], text_field="answer")
        self.assertEqual(updated["mapping"], {"text_field": "answer"})
        with self.assertRaises(ValueError):
            self.workspace.update_mapping(registered["id"], text_field="missing")

    def test_registry_ids_cannot_escape_workspace(self) -> None:
        with self.assertRaises(KeyError):
            self.workspace.get_dataset("../../outside")
        with self.assertRaises(KeyError):
            self.workspace.get_job("../../outside")

    def test_parquet_without_pyarrow_still_registers_metadata_without_loading_file(self) -> None:
        source = self.root / "huge.parquet"
        source.write_bytes(b"PAR1placeholder")
        real_find_spec = __import__("importlib").util.find_spec

        def fake_find_spec(name: str):
            if name == "pyarrow":
                return None
            return real_find_spec(name)

        with patch("training_service.importlib.util.find_spec", side_effect=fake_find_spec):
            inspected = self.workspace.inspect_local(source)
        self.assertEqual(inspected["format"], "parquet")
        self.assertEqual(inspected["preview"], [])
        self.assertFalse(inspected["preview_available"])

    def test_invalid_huggingface_id_is_rejected_before_network(self) -> None:
        async def run() -> None:
            with self.assertRaises(ValueError):
                await self.workspace.inspect_huggingface("not-a-repo-id")

        import asyncio

        asyncio.run(run())


class TrainingRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = _FakeDatabase(self.root / "hades.db")
        app = FastAPI()
        app.include_router(mount_training_routes({"database": self.db}), prefix="/api")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_local_path_requires_explicit_approval_when_policy_is_ask(self) -> None:
        source = self.root / "dataset.jsonl"
        source.write_text('{"text":"hello"}\n', encoding="utf-8")
        denied = self.client.post("/api/training/datasets/local", json={"path": str(source)})
        self.assertEqual(denied.status_code, 409)

        allowed = self.client.post(
            "/api/training/datasets/local",
            json={"path": str(source), "approved_file_read": True},
        )
        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(allowed.json()["path"], str(source.resolve()))

    def test_block_policy_cannot_be_overridden_by_request_flag(self) -> None:
        self.db.values["file_read_policy"] = "block"
        source = self.root / "dataset.jsonl"
        source.write_text('{"text":"hello"}\n', encoding="utf-8")
        response = self.client.post(
            "/api/training/datasets/local",
            json={"path": str(source), "approved_file_read": True},
        )
        self.assertEqual(response.status_code, 403)

    def test_capability_endpoint_does_not_require_training_packages(self) -> None:
        response = self.client.get("/api/training/capabilities")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("trainer_ready", body)
        self.assertIn("torch", body["packages"])


if __name__ == "__main__":
    unittest.main()
