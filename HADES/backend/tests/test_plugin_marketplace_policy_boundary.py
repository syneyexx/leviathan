from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class PluginMarketplacePolicyBoundaryTests(unittest.TestCase):
    def _exercise(self, *, file_write_policy: str, network_policy: str, install_dependencies: bool):
        client = TestClient(main.app)
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "audit-plugin"
            source.mkdir()
            catalog = {
                "items": [
                    {
                        "id": "audit-plugin",
                        "source_path": str(source),
                    }
                ]
            }
            settings = {
                "file_read_policy": "allow",
                "file_write_policy": file_write_policy,
                "network_policy": network_policy,
            }
            with patch.object(main.database, "get_settings", return_value=settings), patch(
                "plugin_marketplace.scan_local_marketplace",
                return_value=catalog,
            ), patch.object(
                main.plugin_manager,
                "import_local_folder",
                return_value={"plugin": {"id": "audit-plugin", "status": "ready"}},
            ) as install:
                response = client.post(
                    f"/api/plugins/marketplace/audit-plugin/install?install_dependencies={'true' if install_dependencies else 'false'}"
                )
        return response, install

    @unittest.expectedFailure
    def test_marketplace_install_respects_file_write_block(self) -> None:
        response, install = self._exercise(
            file_write_policy="block",
            network_policy="allow",
            install_dependencies=False,
        )
        self.assertEqual(response.status_code, 403)
        install.assert_not_called()

    @unittest.expectedFailure
    def test_marketplace_dependency_install_respects_network_block(self) -> None:
        response, install = self._exercise(
            file_write_policy="allow",
            network_policy="block",
            install_dependencies=True,
        )
        self.assertEqual(response.status_code, 403)
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
