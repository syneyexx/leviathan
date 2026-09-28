"""Central mutation auth — non-loopback default-deny for state-changing /api routes."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from Data.modules.common.http_auth import (
    OPERATOR_TOKEN_HEADER,
    SAFE_METHODS,
    assert_operator_mutation_allowed,
    classify_http_methods,
    mutation_requires_operator_auth,
    tokens_match,
    validate_non_loopback_security_posture,
)


class HttpAuthUnitTests(unittest.TestCase):
    def test_loopback_never_requires_token(self) -> None:
        self.assertFalse(
            mutation_requires_operator_auth(
                method="POST", path="/api/settings/x", loopback_only=True
            )
        )

    def test_non_loopback_mutations_require_token(self) -> None:
        self.assertTrue(
            mutation_requires_operator_auth(
                method="POST", path="/api/modules/install", loopback_only=False
            )
        )
        self.assertTrue(
            mutation_requires_operator_auth(
                method="PUT", path="/api/models/m1/activate", loopback_only=False
            )
        )
        self.assertFalse(
            mutation_requires_operator_auth(
                method="GET", path="/api/health", loopback_only=False
            )
        )

    def test_compare_digest_rejects_mismatch_and_empty(self) -> None:
        self.assertTrue(tokens_match("abc", "abc"))
        self.assertFalse(tokens_match("abc", "abd"))
        self.assertFalse(tokens_match("", "abc"))
        self.assertFalse(tokens_match("abc", ""))

    def test_validate_startup_fails_without_token(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEVIATHAN_OPERATOR_TOKEN", None)
            with self.assertRaises(RuntimeError):
                validate_non_loopback_security_posture(loopback_only=False)
        validate_non_loopback_security_posture(loopback_only=True)

    def test_assert_allows_matching_token(self) -> None:
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/chat"
        req.headers = {OPERATOR_TOKEN_HEADER: "secret-token"}
        with patch.dict(os.environ, {"LEVIATHAN_OPERATOR_TOKEN": "secret-token"}, clear=False):
            assert_operator_mutation_allowed(req, loopback_only=False)

    def test_assert_denies_missing_token(self) -> None:
        from Data.modules.common.http_auth import MutationAuthError

        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/chat"
        req.headers = {}
        with patch.dict(os.environ, {"LEVIATHAN_OPERATOR_TOKEN": "secret-token"}, clear=False):
            with self.assertRaises(MutationAuthError):
                assert_operator_mutation_allowed(req, loopback_only=False)

    def test_classify_methods(self) -> None:
        info = classify_http_methods({"GET", "POST", "DELETE"})
        self.assertEqual(info["mutating_methods"], ["DELETE", "POST"])
        self.assertTrue(info["requires_operator_auth_when_non_loopback"])
        safe = classify_http_methods(SAFE_METHODS)
        self.assertEqual(safe["mutating_methods"], [])


class OpenApiMutationCoverageTests(unittest.TestCase):
    """Enumerate FastAPI routes and prove mutations are covered by central policy."""

    def test_every_mutating_api_route_is_classified(self) -> None:
        from Data.backend.main import app

        uncovered: list[str] = []
        mutating: list[str] = []
        for route in app.routes:
            path = getattr(route, "path", "") or ""
            methods = getattr(route, "methods", None)
            if not path.startswith("/api/") or not methods:
                continue
            info = classify_http_methods(methods)
            if not info["mutating_methods"]:
                continue
            mutating.append(f"{sorted(info['mutating_methods'])} {path}")
            # Central policy: every /api mutation requires auth when non-loopback.
            for method in info["mutating_methods"]:
                if not mutation_requires_operator_auth(
                    method=method, path=path, loopback_only=False
                ):
                    uncovered.append(f"{method} {path}")
        self.assertTrue(mutating, "expected at least one mutating /api route")
        self.assertEqual(uncovered, [], f"mutations outside central policy: {uncovered}")

    def test_middleware_registered(self) -> None:
        from Data.backend.main import app

        names = [getattr(m, "name", None) or type(m).__name__ for m in app.user_middleware]
        # Starlette wraps pure functions; ensure our middleware function is present.
        middleware_callables = []
        for m in app.user_middleware:
            opts = getattr(m, "kwargs", {}) or {}
            dispatch = opts.get("dispatch")
            if dispatch is not None:
                middleware_callables.append(getattr(dispatch, "__name__", ""))
            cls = getattr(m, "cls", None)
            if cls is not None:
                middleware_callables.append(getattr(cls, "__name__", str(cls)))
        self.assertIn(
            "_operator_mutation_auth_middleware",
            middleware_callables,
            f"middleware stack={middleware_callables} names={names}",
        )


if __name__ == "__main__":
    unittest.main()
