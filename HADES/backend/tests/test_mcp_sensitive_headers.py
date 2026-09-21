from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from mcp_host.header_secrets import (
    HEADER_SECRET_PREFIX,
    is_sensitive_header_name,
    migrate_plaintext_sensitive_headers,
    normalize_sensitive_headers,
    resolve_sensitive_headers,
)
from mcp_host.secrets import secret_store


class _MiniPlatformDb:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connection(self):
        class _Ctx:
            def __init__(self, path: Path) -> None:
                self.path = path
                self.db = None

            def __enter__(self):
                self.db = sqlite3.connect(self.path)
                self.db.row_factory = sqlite3.Row
                self.db.execute("PRAGMA foreign_keys=ON")
                self.db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                return self.db

            def __exit__(self, exc_type, exc, tb):
                assert self.db is not None
                if exc_type is None:
                    self.db.commit()
                else:
                    self.db.rollback()
                self.db.close()
        return _Ctx(self.path)


class SensitiveHeaderHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        secret_store.enable_memory_backend_for_tests()

    def test_secret_shaped_header_names_are_detected(self) -> None:
        for name in ("Authorization", "X-API-Key", "x_api_key", "X-Token", "Credential", "Password"):
            with self.subTest(name=name):
                self.assertTrue(is_sensitive_header_name(name))
        self.assertFalse(is_sensitive_header_name("Accept"))
        self.assertFalse(is_sensitive_header_name("X-Client-Version"))

    def test_sensitive_value_is_masked_and_resolved_only_at_request_time(self) -> None:
        clean, refs = normalize_sensitive_headers(
            server_id="srv-1",
            headers={"Accept": "application/json", "X-API-Key": "super-secret"},
        )
        self.assertEqual(clean["X-API-Key"], "***")
        self.assertNotIn("super-secret", repr(clean))
        self.assertEqual(len([k for k in refs if k.startswith(HEADER_SECRET_PREFIX)]), 1)
        resolved = resolve_sensitive_headers(clean, refs)
        self.assertEqual(resolved["X-API-Key"], "super-secret")
        self.assertEqual(resolved["Accept"], "application/json")

    def test_masked_edit_preserves_secret_and_header_removal_deletes_it(self) -> None:
        clean, refs = normalize_sensitive_headers(
            server_id="srv-1",
            headers={"X-Token": "token-one"},
        )
        original_ref = next(iter(refs.values()))
        clean2, refs2 = normalize_sensitive_headers(
            server_id="srv-1",
            headers={"X-Token": "***"},
            existing_secret_refs=refs,
        )
        self.assertEqual(refs2, refs)
        self.assertEqual(resolve_sensitive_headers(clean2, refs2)["x-token"], "token-one")
        clean3, refs3 = normalize_sensitive_headers(
            server_id="srv-1",
            headers={},
            existing_secret_refs=refs2,
        )
        self.assertEqual(clean3, {})
        self.assertEqual(refs3, {})
        self.assertIsNone(secret_store.get(original_ref))

    def test_header_newlines_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_sensitive_headers(server_id="srv", headers={"X-Test\r\nInjected": "value"})
        with self.assertRaises(ValueError):
            normalize_sensitive_headers(server_id="srv", headers={"X-Test": "value\r\nInjected: yes"})

    def test_legacy_plaintext_header_is_migrated_out_of_sqlite(self) -> None:
        from mcp_host.store import McpStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hades.db"
            db = _MiniPlatformDb(path)
            store = McpStore(db)
            store.upsert_server(
                {
                    "id": "srv-legacy",
                    "name": "Legacy",
                    "transport": "streamable_http",
                    "endpoint_url": "https://example.com/mcp",
                    "headers": {"X-API-Key": "legacy-secret", "Accept": "application/json"},
                    "env": {"plain": {}, "secret_refs": {}},
                }
            )
            result = migrate_plaintext_sensitive_headers(store)
            self.assertEqual(result["headers"], 1)
            migrated = store.get_server("srv-legacy")
            assert migrated is not None
            self.assertEqual(migrated["headers"]["X-API-Key"], "***")
            self.assertNotIn("legacy-secret", repr(migrated))
            resolved = resolve_sensitive_headers(migrated["headers"], migrated["env"]["secret_refs"])
            self.assertEqual(resolved["x-api-key"], "legacy-secret")
            with sqlite3.connect(path) as raw:
                stored_headers = raw.execute("SELECT headers_json FROM mcp_servers WHERE id='srv-legacy'").fetchone()[0]
            self.assertNotIn("legacy-secret", stored_headers)


if __name__ == "__main__":
    unittest.main()
