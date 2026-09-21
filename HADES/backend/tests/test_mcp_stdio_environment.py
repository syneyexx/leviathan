from __future__ import annotations

import unittest

from mcp_host import clients
from mcp_host import clients_legacy


class McpStdioEnvironmentTests(unittest.TestCase):
    def test_ambient_credentials_are_removed_but_runtime_environment_survives(self) -> None:
        ambient = {
            "PATH": "C:/Windows/System32",
            "SYSTEMROOT": "C:/Windows",
            "TEMP": "C:/Temp",
            "HTTP_PROXY": "http://127.0.0.1:8888",
            "HADES_DATA_DIR": "C:/HADES/data",
            "HADES_LM_STUDIO_API_KEY": "hades-secret",
            "OPENAI_API_KEY": "openai-secret",
            "FINCEPT_SESSION_TOKEN": "fincept-secret",
            "CUSTOM_PASSWORD": "password-secret",
        }

        child = clients.build_stdio_child_environment(ambient=ambient)

        self.assertEqual(child["PATH"], ambient["PATH"])
        self.assertEqual(child["SYSTEMROOT"], ambient["SYSTEMROOT"])
        self.assertEqual(child["TEMP"], ambient["TEMP"])
        self.assertEqual(child["HTTP_PROXY"], ambient["HTTP_PROXY"])
        self.assertEqual(child["HADES_DATA_DIR"], ambient["HADES_DATA_DIR"])
        self.assertNotIn("HADES_LM_STUDIO_API_KEY", child)
        self.assertNotIn("OPENAI_API_KEY", child)
        self.assertNotIn("FINCEPT_SESSION_TOKEN", child)
        self.assertNotIn("CUSTOM_PASSWORD", child)

    def test_manager_explicit_server_secret_is_the_only_secret_reentry_path(self) -> None:
        ambient = {
            "PATH": "C:/Windows/System32",
            "OPENAI_API_KEY": "unrelated-parent-secret",
            "SERVER_TOKEN": "unrelated-parent-token",
        }
        explicit = {
            "SERVER_TOKEN": "server-specific-keyring-secret",
            "SERVER_MODE": "stdio",
        }

        child = clients.build_stdio_child_environment(explicit, ambient=ambient)

        self.assertNotIn("OPENAI_API_KEY", child)
        self.assertEqual(child["SERVER_TOKEN"], "server-specific-keyring-secret")
        self.assertEqual(child["SERVER_MODE"], "stdio")

    def test_public_stdio_client_uses_hardened_wrapper(self) -> None:
        self.assertTrue(issubclass(clients.StdioMcpClient, clients_legacy.StdioMcpClient))
        self.assertIsNot(clients.StdioMcpClient, clients_legacy.StdioMcpClient)


if __name__ == "__main__":
    unittest.main()
