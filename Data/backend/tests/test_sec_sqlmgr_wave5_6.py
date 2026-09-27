"""SEC-001 + SQLMGR-001 regression tests."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.database_domains import DatabasePaths
from Data.modules.provider_io.executor import _request_from_job_args
from Data.modules.provider_io.private_host_authority import (
    resolve_allow_private_hosts_for_url,
)
from Data.modules.sqlite_manager import SqliteManager, SqliteManagerError
from Data.modules.sqlite_manager.sql_safety import classify_write_sql


class PrivateHostAuthorityTests(unittest.TestCase):
    def test_job_payload_cannot_self_grant_private_hosts(self) -> None:
        req = _request_from_job_args(
            {
                "capability": "http",
                "provider": "generic",
                "allow_private_hosts": True,
                "payload": {
                    "url": "http://169.254.169.254/latest/meta-data",
                    "allow_private_hosts": True,
                },
            },
            job_id="j1",
        )
        self.assertFalse(req.allow_private_hosts)
        self.assertNotIn("allow_private_hosts", req.payload)

    def test_allowlist_permits_configured_local_endpoint(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST": "127.0.0.1",
                "LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS": "",
            },
            clear=False,
        ):
            self.assertTrue(
                resolve_allow_private_hosts_for_url(
                    "http://127.0.0.1:11434/v1/chat",
                    settings=mock.Mock(spec=[]),  # no model.base_url
                )
            )

    def test_loopback_not_hardcoded_without_policy(self) -> None:
        """SECURITY-001: arbitrary localhost must not bypass SSRF without allowlist."""
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST": "",
                "LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS": "",
            },
            clear=False,
        ):
            # Settings with no configured private endpoints.
            settings = mock.Mock(spec=["model", "managed_serving", "llm_base_url"])
            settings.model = mock.Mock(spec=["base_url"])
            settings.model.base_url = "https://api.openai.com/v1"
            settings.managed_serving = mock.Mock(spec=["base_url"])
            settings.managed_serving.base_url = ""
            settings.llm_base_url = "https://api.openai.com/v1"
            self.assertFalse(
                resolve_allow_private_hosts_for_url(
                    "http://127.0.0.1:9/secret",
                    settings=settings,
                    request_flag=True,
                )
            )
            self.assertFalse(
                resolve_allow_private_hosts_for_url(
                    "http://localhost/admin",
                    settings=settings,
                )
            )

    def test_public_host_not_granted_via_flag(self) -> None:
        # Public hosts do not need private-host privilege; resolve may be False
        # (SSRF assert_safe_url still applies in adapters when False).
        self.assertFalse(
            resolve_allow_private_hosts_for_url(
                "http://example.com",
                request_flag=True,
            )
        )


class SqliteManagerBoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.paths = DatabasePaths(
            control=root / "c.db",
            knowledge=root / "k.db",
            market=root / "m.db",
        )
        for p in self.paths.all_canonical():
            path = p[1]
            path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
            for i in range(80):
                con.execute("INSERT INTO t(id, v) VALUES (?, ?)", (i, f"v{i}"))
            con.commit()
            con.close()
        self.manager = SqliteManager(self.paths, allow_writes=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reject_update_without_where(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            classify_write_sql("UPDATE t SET v='x'")
        self.assertEqual(str(ctx.exception), "UNBOUNDED_WRITE_FORBIDDEN")

    def test_reject_delete_without_where(self) -> None:
        with self.assertRaises(ValueError):
            classify_write_sql("DELETE FROM t")

    def test_one_row_update_ok(self) -> None:
        result = self.manager.mutate(
            "CONTROL",
            "UPDATE t SET v='z' WHERE id=1",
            confirm_domain="CONTROL",
        )
        self.assertEqual(result["rowcount"], 1)

    def test_large_affected_row_count_rolls_back(self) -> None:
        with self.assertRaises(SqliteManagerError) as ctx:
            self.manager.mutate(
                "CONTROL",
                "UPDATE t SET v='z' WHERE id >= 0",
                confirm_domain="CONTROL",
            )
        self.assertEqual(ctx.exception.code, "ROW_BOUND_EXCEEDED")
        con = sqlite3.connect(self.paths.control)
        unchanged = con.execute("SELECT COUNT(*) FROM t WHERE v LIKE 'v%'").fetchone()[0]
        con.close()
        self.assertEqual(unchanged, 80)


if __name__ == "__main__":
    unittest.main()
