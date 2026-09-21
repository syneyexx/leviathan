from __future__ import annotations

import importlib.util
import json
import socket
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def _load_python_bridge(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dns_answer(address: str, port: int = 443):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, port))]


class PythonBrowserNetworkBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patchright = _load_python_bridge(
            "hades_patchright_security_test",
            "plugins/patchright/hades_bridge.py",
        )
        cls.scrapling = _load_python_bridge(
            "hades_scrapling_security_test",
            "plugins/scrapling/hades_bridge.py",
        )

    def test_patchright_rejects_hostname_resolving_to_loopback(self) -> None:
        with mock.patch.object(self.patchright.socket, "getaddrinfo", return_value=_dns_answer("127.0.0.1", 80)):
            with self.assertRaises(ValueError):
                self.patchright.ensure_public_url("http://public-looking.example/")

    def test_patchright_accepts_hostname_resolving_to_public_ip(self) -> None:
        with mock.patch.object(self.patchright.socket, "getaddrinfo", return_value=_dns_answer("93.184.216.34")):
            url = self.patchright.ensure_public_url("https://example.com/path")
        self.assertEqual(url, "https://example.com/path")

    def test_scrapling_rejects_hostname_resolving_to_rfc1918(self) -> None:
        with mock.patch.object(self.scrapling.socket, "getaddrinfo", return_value=_dns_answer("10.0.0.12", 80)):
            with self.assertRaises(ValueError):
                self.scrapling.ensure_public_url("http://apparently-public.example/")

    def test_scrapling_extract_fails_before_fetch_for_private_resolution(self) -> None:
        with mock.patch.object(self.scrapling.socket, "getaddrinfo", return_value=_dns_answer("169.254.169.254", 80)):
            with mock.patch.object(self.scrapling, "_static_fetch") as fetch_mock:
                result = self.scrapling.extract("http://metadata-proxy.example/latest", "out.txt")
        self.assertFalse(result.get("ok"))
        self.assertIn("non-public", str(result.get("error") or ""))
        fetch_mock.assert_not_called()

    def test_scrapling_static_fetch_disables_automatic_redirects(self) -> None:
        source = (ROOT / "plugins/scrapling/hades_bridge.py").read_text(encoding="utf-8")
        self.assertIn("follow_redirects=False", source)
        self.assertIn("ensure_public_url(urljoin(current, location))", source)

    def test_scrapling_browser_modes_install_pre_navigation_guard(self) -> None:
        source = (ROOT / "plugins/scrapling/hades_bridge.py").read_text(encoding="utf-8")
        self.assertIn("page_setup=_page_setup", source)
        self.assertIn('page.route("**/*", guard)', source)

    def test_scrapling_extract_destination_is_visible_to_file_policy(self) -> None:
        manifest = json.loads((ROOT / "plugins/scrapling/hades-plugin.json").read_text(encoding="utf-8"))
        extract = next(tool for tool in manifest["tools"] if tool["name"] == "extract")
        self.assertIn("path", extract["input_schema"]["required"])
        self.assertIn("{path}", extract["command"])
        self.assertNotIn("{output}", extract["command"])
        self.assertIn("write_files", extract["capabilities"]["effects"])


class GeneratedBridgeSecurityDriftTests(unittest.TestCase):
    def test_scrapling_template_keeps_same_security_invariants(self) -> None:
        live = (ROOT / "plugins/scrapling/hades_bridge.py").read_text(encoding="utf-8")
        template = (ROOT / "plugins/_shared/bridge_templates/scrapling.py").read_text(encoding="utf-8")
        for needle in (
            "def ensure_public_url",
            "socket.getaddrinfo",
            "follow_redirects=False",
            "page_setup=_page_setup",
            'page.route("**/*", guard)',
            "ensure_public_url(urljoin(current, location))",
        ):
            self.assertIn(needle, live)
            self.assertIn(needle, template)


class PuppeteerSecurityContractTests(unittest.TestCase):
    def test_puppeteer_dns_and_request_interception_are_mandatory(self) -> None:
        source = (ROOT / "plugins/puppeteer/hades_bridge.mjs").read_text(encoding="utf-8")
        self.assertIn('import dns from "node:dns/promises"', source)
        self.assertIn("dns.lookup(host", source)
        self.assertIn("page.setRequestInterception(true)", source)
        self.assertIn('page.on("request"', source)
        self.assertIn("await ensurePublicUrl(page.url())", source)

    def test_puppeteer_ipv6_is_global_unicast_only_and_blocks_transition_ranges(self) -> None:
        source = (ROOT / "plugins/puppeteer/hades_bridge.mjs").read_text(encoding="utf-8")
        self.assertIn("first < 0x2000 || first > 0x3fff", source)
        self.assertIn("first === 0x2002", source)
        self.assertIn("second === 0x0db8", source)

    def test_puppeteer_does_not_disable_chromium_sandbox(self) -> None:
        source = (ROOT / "plugins/puppeteer/hades_bridge.mjs").read_text(encoding="utf-8")
        self.assertNotIn('"--no-sandbox"', source)
        self.assertNotIn('"--disable-setuid-sandbox"', source)


class PatchrightSecurityContractTests(unittest.TestCase):
    def test_patchright_guards_redirects_and_subresources(self) -> None:
        source = (ROOT / "plugins/patchright/hades_bridge.py").read_text(encoding="utf-8")
        self.assertIn('page.route("**/*", guard)', source)
        self.assertIn("ensure_public_url(request_url)", source)
        self.assertIn("ensure_public_url(page.url)", source)


if __name__ == "__main__":
    unittest.main()
