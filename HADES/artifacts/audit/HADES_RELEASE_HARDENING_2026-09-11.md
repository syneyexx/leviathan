# HADES deep release hardening — 2026-09-11

## Scope

This pass starts from `main` after the prior full-repository audit and MCP catalog regression fix. It focuses on security boundaries, runtime truth, persistence atomicity, secret handling, generator drift, and regressions introduced by the post-audit MCP/browser/research work.

## Confirmed issues repaired

1. Browser-backed plugin fetch paths now validate destination addresses and redirects against the shared SSRF boundary, including DNS rebinding/mixed-address cases.
2. Puppeteer no longer forces Chromium `--no-sandbox`.
3. Scrapling `extract` now uses the guarded fetch/write path and filesystem policy instead of an unguarded convenience path.
4. URL security fails closed for DNS-resolution failures and special/private/non-global destinations, including metadata/link-local and CGNAT ranges.
5. Conversation deletion and learned Knowledge/FTS cleanup are coupled transactionally for the shared production SQLite store.
6. Shared-store startup now fails closed if the conversation-forget integrity trigger cannot be installed; separate-store test/dev topologies remain supported.
7. Bridge templates for affected generated plugins were hardened so regeneration does not restore the unsafe behavior.
8. MCP authenticated HTTP redirects are restricted to the same origin before credentials are reused.
9. MCP loopback/private allowance is limited to explicit loopback context and cannot expand to LAN/metadata destinations through redirects.
10. OAuth discovery/authorization/token endpoints are revalidated; public off-host OAuth endpoints require HTTPS while explicit loopback development remains supported.
11. OAuth callback failures no longer reflect provider/backend diagnostic text into browser URL history.
12. Sensitive custom MCP headers are stored in the secure OS-backed secret store, never as plaintext SQLite values.
13. MCP custom headers reject CR/LF injection.
14. Legacy plaintext sensitive MCP headers are migrated to secure storage and migration fails closed when secure storage is unavailable.
15. MCP public/API server views hide auth secret refs and concrete env/header secret refs.
16. MCP config export masks sensitive headers, omits internal header-secret bookkeeping and runtime OAuth refs/endpoints, and preserves only portable user configuration.
17. Persisted MCP `connected`/`ready` state is downgraded unless supported by live runtime evidence.
18. Modern MCP refresh persists `ready` rather than legacy `connected`.
19. Plugin-owned MCP expansion failure cannot be converted into success by stale previously discovered tools.
20. A proven OAuth 401 forces refresh instead of resending the same rejected token merely because its stored expiry is in the future.
21. Config API input cannot inject internal OAuth runtime secret refs/endpoints/cleanup metadata.

## Regression coverage added

- `test_app_lifecycle_release_hardening.py`
- `test_bridge_template_drift_regressions.py`
- `test_browser_network_boundary_regressions.py`
- `test_conversation_forget_atomicity.py`
- `test_mcp_manager_release_hardening.py`
- `test_mcp_oauth_network_boundary.py`
- `test_mcp_redirect_security.py`
- `test_mcp_sensitive_headers.py`
- `test_url_security_fail_closed.py`

The tests cover fail-closed shared-store startup, transactional rollback, browser redirects/subrequests, OAuth network boundaries, authenticated redirect credential isolation, secure header migration/storage/export, MCP liveness/status truth, forced OAuth refresh, metadata injection, and template drift.

## MCP manager change-risk control

The original `main` MCP manager implementation was copied byte-for-byte to `backend/mcp_host/manager_core.py` (same Git blob SHA as `main/backend/mcp_host/manager.py`: `b98a6547939ab350ff8fb9f96926fa7e63d31c85`). `backend/mcp_host/manager.py` is a small subclass/hardening layer. This keeps existing execution/orchestration logic unchanged while making the new invariants reviewable.

## Release validation honesty

This document is evidence of the static/deep hardening work, not a substitute for the repository release gates. Merge/release readiness requires the pull-request release workflow to actually execute and pass its Ubuntu and Windows quick/full jobs. An Actions failure before runner allocation is an external CI blocker and must not be reported as a passing software validation.
