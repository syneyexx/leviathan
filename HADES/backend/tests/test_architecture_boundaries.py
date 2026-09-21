"""Architecture dependency direction tests.

Desired direction: API → Application → Domain ← Infrastructure

These tests are lightweight static guards, not a full import-linter suite.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


class DependencyDirectionTests(unittest.TestCase):
    def test_errors_package_does_not_import_fastapi(self) -> None:
        for path in (BACKEND / "errors").rglob("*.py"):
            imports = _imports_of(path)
            self.assertNotIn("fastapi", imports, f"{path} must stay HTTP-free")

    def test_infrastructure_native_does_not_import_fastapi(self) -> None:
        for path in (BACKEND / "infrastructure" / "native").rglob("*.py"):
            imports = _imports_of(path)
            self.assertNotIn("fastapi", imports, f"{path} must stay transport-free")
            self.assertNotIn("main", imports, f"{path} must not import main")

    def test_native_runtime_shim_reexports_facade(self) -> None:
        source = (BACKEND / "native_runtime.py").read_text(encoding="utf-8")
        self.assertIn("infrastructure.native", source)
        self.assertIn("NativeRuntimeFacade", source)

    def test_no_unbounded_thread_per_request_in_native_main(self) -> None:
        main_cpp = BACKEND.parents[0] / "native" / "src" / "main.cpp"
        text = main_cpp.read_text(encoding="utf-8")
        self.assertIn("BoundedExecutor", text)
        self.assertNotIn("workers.emplace_back", text)
        self.assertNotIn("std::vector<std::thread> workers", text)


if __name__ == "__main__":
    unittest.main()
