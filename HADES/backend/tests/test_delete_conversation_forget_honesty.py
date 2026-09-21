"""Conversation delete must not 204 when knowledge-forget fails."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException


class DeleteConversationForgetHonestyTests(unittest.TestCase):
    def test_forget_failure_raises_500(self) -> None:
        import main as main_mod

        with patch.object(main_mod, "ensure_platform_services", return_value=None), patch.object(
            main_mod.database, "delete_conversation", return_value=True
        ), patch.object(
            main_mod.platform_db,
            "mark_knowledge_forgotten",
            side_effect=RuntimeError("db locked"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(main_mod.delete_conversation("conv_test"))
            self.assertEqual(ctx.exception.status_code, 500)
            detail = str(ctx.exception.detail).lower()
            self.assertIn("knowledge-forget", detail)


if __name__ == "__main__":
    unittest.main()
