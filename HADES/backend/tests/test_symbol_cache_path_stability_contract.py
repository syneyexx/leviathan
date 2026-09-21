from __future__ import annotations

import unittest
from pathlib import Path


class SymbolCachePathStabilityContractTests(unittest.TestCase):
    def test_workspace_symbol_cache_path_does_not_use_python_hash(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "capability_routes.py").read_text(encoding="utf-8")
        start = source.index("    def _symbol_cache_path(root: Path) -> Path:")
        end = source.index("\n    @router", start)
        helper = source[start:end]

        self.assertNotIn("hash(str(root.resolve()))", helper)
        self.assertTrue(
            "sha256" in helper or "blake2" in helper,
            "Persistent workspace cache identities must use a process-stable digest.",
        )


if __name__ == "__main__":
    unittest.main()
