import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Database


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(str(Path(self.temp_dir.name) / "hades-test.db"))
        self.database.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_conversation_and_messages_are_persistent(self) -> None:
        conversation = self.database.create_conversation()
        self.database.add_message(conversation["id"], "user", "Hallo lokaal model")
        messages = self.database.list_messages(conversation["id"])
        self.assertEqual(messages[0]["content"], "Hallo lokaal model")
        self.assertEqual(messages[0]["role"], "user")

    def test_conversation_can_be_renamed_and_keep_prompt_override(self) -> None:
        conversation = self.database.create_conversation("Origineel")
        updated = self.database.update_conversation(
            conversation["id"], title="Project HADES", system_prompt_override="Je bent de projectarchitect.", update_prompt=True
        )
        self.assertEqual(updated["title"], "Project HADES")
        self.assertEqual(updated["system_prompt_override"], "Je bent de projectarchitect.")
        self.database.add_message(conversation["id"], "user", "Eerste bericht")
        self.assertEqual(self.database.get_conversation(conversation["id"])["title"], "Project HADES")

    def test_memory_crud_and_stats(self) -> None:
        memory = self.database.save_memory(
            {
                "title": "Testgeheugen",
                "content": "Dit wordt lokaal bewaard.",
                "summary": "Lokale test",
                "collection": "Tests",
                "tags": ["sqlite", "test"],
                "source": "Unittest",
            }
        )
        self.assertEqual(self.database.get_memory(memory["id"])["tags"], ["sqlite", "test"])
        memory["content"] = "Bijgewerkt"
        updated = self.database.save_memory(memory, memory["id"])
        self.assertEqual(updated["content"], "Bijgewerkt")
        self.assertTrue(self.database.delete_memory(memory["id"]))

    def test_memory_supersession_keeps_history_but_only_new_version_active(self) -> None:
        old = self.database.save_memory({
            "title": "Endpoint",
            "content": "Endpoint is poort 1111",
            "summary": "oude waarde",
            "collection": "Tests",
            "tags": ["config"],
            "source": "Unittest",
        })
        new = self.database.supersede_memory(old["id"], {
            "title": "Endpoint",
            "content": "Endpoint is poort 2222",
            "summary": "gecorrigeerde waarde",
            "collection": "Tests",
            "tags": ["config"],
            "source": "Correctie",
        })
        self.assertEqual(self.database.get_memory(old["id"])["status"], "superseded")
        self.assertEqual(new["supersedes"], old["id"])
        active = self.database.list_memories(query="Endpoint")
        self.assertEqual([item["id"] for item in active], [new["id"]])
        history = self.database.memory_history(new["id"])
        self.assertEqual({item["id"] for item in history}, {old["id"], new["id"]})

    def test_memory_scope_filter_and_supersede_preserves_scope(self) -> None:
        project = self.database.save_memory({
            "title": "Project note",
            "content": "Alleen project",
            "summary": "project",
            "collection": "Tests",
            "tags": [],
            "source": "Unittest",
            "scope": "project",
        })
        global_item = self.database.save_memory({
            "title": "Global note",
            "content": "Globaal feit",
            "summary": "global",
            "collection": "Tests",
            "tags": [],
            "source": "Unittest",
            "scope": "global",
        })
        session = self.database.save_memory({
            "title": "Session note",
            "content": "Sessie feit",
            "summary": "session",
            "collection": "Tests",
            "tags": ["conv_abc"],
            "source": "Unittest",
            "scope": "session",
        })
        self.assertEqual({item["id"] for item in self.database.list_memories(scope="global")}, {global_item["id"]})
        self.assertEqual({item["id"] for item in self.database.list_memories(scope="session")}, {session["id"]})
        self.assertIn(project["id"], {item["id"] for item in self.database.list_memories(scope="project")})
        replaced = self.database.supersede_memory(project["id"], {
            "title": "Project note",
            "content": "Alleen project v2",
            "summary": "project",
            "collection": "Tests",
            "tags": [],
            "source": "Correctie",
        })
        self.assertEqual(replaced["scope"], "project")
        self.assertEqual(self.database.get_memory(project["id"])["status"], "superseded")

    def test_task_transitions_and_events(self) -> None:
        task = self.database.create_task("Controle", "Controleer dit", "Tester", "high", None)
        self.database.update_task(task["id"], status="running", progress=50)
        completed = self.database.update_task(task["id"], status="completed", progress=100, result="Gereed")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"], "Gereed")
        self.assertGreaterEqual(len(self.database.task_events(task["id"])), 1)

    def test_settings_are_updated_without_losing_defaults(self) -> None:
        settings = self.database.update_settings({"language": "en", "max_concurrent_tasks": 3})
        self.assertEqual(settings["language"], "en")
        self.assertEqual(settings["max_concurrent_tasks"], 3)
        self.assertIn("lm_studio_base_url", settings)
        self.assertEqual(settings["expert_max_cycles"], 6)

    def test_expert_research_settings_persist(self) -> None:
        settings = self.database.update_settings({"expert_mastery_target": 95, "expert_max_cycles": 12})
        self.assertEqual(settings["expert_mastery_target"], 95)
        self.assertEqual(settings["expert_max_cycles"], 12)
        reloaded = self.database.get_settings()
        self.assertEqual(reloaded["expert_mastery_target"], 95)
        self.assertEqual(reloaded["expert_max_cycles"], 12)


class DatabaseMigrationTests(unittest.TestCase):
    def test_initialize_upgrades_legacy_task_schema_without_losing_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy-hades.db"
            with sqlite3.connect(path) as db:
                db.executescript(
                    """
                    CREATE TABLE tasks (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        prompt TEXT NOT NULL,
                        agent TEXT NOT NULL,
                        priority TEXT NOT NULL CHECK(priority IN ('low', 'normal', 'high')),
                        status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
                        model_id TEXT,
                        progress INTEGER NOT NULL DEFAULT 0,
                        result TEXT,
                        error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT
                    );
                    INSERT INTO tasks(
                        id, title, prompt, agent, priority, status, model_id, progress,
                        result, error, created_at, updated_at, started_at, finished_at
                    ) VALUES (
                        'task_legacy', 'Legacy task', 'Behoud mij', 'Generalist', 'normal',
                        'queued', NULL, 0, NULL, NULL,
                        '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', NULL, NULL
                    );
                    """
                )

            database = Database(str(path))
            database.initialize()

            with database.connection() as db:
                columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)").fetchall()}
            self.assertTrue({"control_state", "plan_version", "redirect_instruction"}.issubset(columns))

            task = database.get_task("task_legacy")
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task["title"], "Legacy task")
            self.assertEqual(task["prompt"], "Behoud mij")
            self.assertEqual(task["control_state"], "active")
            self.assertEqual(task["plan_version"], 1)
            self.assertIsNone(task["redirect_instruction"])


if __name__ == "__main__":
    unittest.main()
