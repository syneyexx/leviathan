# MCP host (management page)

HADES first-class MCP management lives in `backend/mcp_host/` and the UI page
`components/hades/pages/mcp-page.tsx` (nav: **MCP**, next to Plugins).

## Architecture decision (SDK vs hand-written)

| Area | Choice |
|---|---|
| Host lifecycle, secrets, policy, PluginManager mirror | HADES-owned (`McpManager`) |
| Wire protocol (stdio + Streamable HTTP) | Versioned hand-written clients in `clients.py` |
| Official MCP Python SDK (`mcp` 2.x) | **Not** adopted as a hard dependency yet |

**Why:** MCP Python SDK 2.x speaks `2026-07-28`, but pulling it into HADES currently
conflicts with FastAPI’s `starlette` pin (SDK pulls newer starlette/sse-starlette).
The SDK is also async-first while ToolEngine/PluginManager invoke paths are sync/threaded,
and HADES requires custom SSRF redirect re-validation that must not be replaced by
`follow_redirects=True`. Keeping a small versioned client preserves offline-first policy
invariants and Windows subprocess governance. Revisit SDK encapsulation after a deliberate
dependency migration.

## Supported protocol revisions

Preference order (newest first):

1. **`2026-07-28` (modern / stateless)** — `server/discover` with normative
   **`supportedVersions`**, per-request `_meta`, Streamable HTTP
   `MCP-Protocol-Version` + `Mcp-Method` / `Mcp-Name` (+ `Mcp-Param-*` when
   tools annotate `x-mcp-header`), **no** `initialize` / `Mcp-Session-Id`.
   UI status after verification: **`ready`**.
2. **Legacy:** `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`, `2024-10-07` —
   `initialize` / `notifications/initialized`, optional session id on Streamable HTTP.
   Modern routing headers are **not** emitted on legacy requests.
   UI status: **`connected`**.

Era negotiation is typed:

- Recognized modern JSON-RPC errors (`HeaderMismatch` **-32020**,
  `MissingRequiredClientCapability` **-32021**, `UnsupportedProtocolVersion` **-32022**)
  are **not** legacy evidence.
- HTTP 401/403/5xx / transport timeouts do **not** silently downgrade.
- Dual-era HTTP fallback requires a 4xx without a recognized modern body (or `-32601`).
- Stdio: bounded `server/discover` probe; on non-modern failure / process exit the child
  is restarted before legacy `initialize` (no orphan / duplicate persistent process).

Historical discover aliases (`protocolVersions`) may be read only as compatibility input;
fixtures and primary parsing use **`supportedVersions`**.

MRTR (`input_required`) is detected and returned as an unsupported protocol outcome.
HADES does **not** advertise MRTR client capability and does **not** claim full
2026-07-28 host completeness while MRTR is unsupported.

## What this host adds

- Durable server configs (`mcp_servers` / `mcp_tools` / `mcp_executions`, migrations 15–16)
- Long-lived sessions **inside the FastAPI process** (stdio + Streamable HTTP)
- Catalog: GitHub, Hugging Face, Chrome DevTools MCP, Desktop Commander MCP, Custom
- Secrets via OS keyring (`keyring`) — never plaintext SQLite; fail closed if unavailable
- OAuth PKCE (S256 only; fail closed if AS metadata omits / lacks S256) with issuer-bound
  state, replay protection, RFC 8707 `resource`, RFC 9728 PRM path discovery,
  WWW-Authenticate `resource_metadata`, and AS metadata / OIDC path candidates
- Loopback OAuth callback: `GET /api/mcp/oauth/callback` (absolute URI, **no fragment**)
- Mirror into synthetic plugins `mcp:{server_id}` so chatbot/tool_engine reuse PluginManager
- Plugin-owned servers are marked `owner_kind=plugin` and never double-started
- Request-scoped cancellation; network/subprocess policy parity with ApprovalService

## Transports / auth

| Transport | Auth |
|---|---|
| stdio | env secrets via keyring; `shell=False`; subprocess_policy enforced |
| streamable_http | none / Bearer / OAuth (PKCE); network_policy enforced (`ask` ≠ allow) |

### GitHub remote MCP

- **PAT/Bearer:** catalog → store token in keyring → Connect to
  `https://api.githubcopilot.com/mcp/`. Prefer least-privilege read-only PAT for smoke tests.
- **OAuth:** GitHub’s hosted MCP does **not** support DCR. Configure a GitHub App / OAuth App
  client id in server `metadata.oauth_client_id` before starting OAuth. Without that, OAuth
  start fails closed and documents registration_required. Bearer remains the supported default.

### Hugging Face

- Catalog → Bearer HF token in keyring → `https://huggingface.co/mcp` when network_policy allows.

### OAuth callback architecture

Registered redirect URI must be absolute and fragment-free, e.g.:

`http://127.0.0.1:8000/api/mcp/oauth/callback`

The FastAPI callback completes the code exchange server-side (code never logged, tokens
never placed in the SPA URL) and redirects the browser to the UI return URL with
`#/mcp?oauth=done|error`. Frontend and backend ports may differ.

### OAuth refresh

Access-token expiry is refreshed proactively when `oauth_expires_at` is known, and on a
proven HTTP **401** before tool side effects. Mutating tool calls are **not** blindly
replayed after ambiguous transport failures. `invalid_grant` marks `auth_required`.

## Authorization model (tools)

| Flag | Meaning |
|---|---|
| `allowed` | Global enablement (default **deny** on discovery) |
| `chatbot_enabled` | Shortlist/visibility only — never grants execution |
| `require_approval` | Autonomous path needs a validated persisted `approval_id` |
| manual + blocked tool | Requires a persisted ApprovalService decision (`approval_id`) with exact tool scope |
| `approved_by_user` | Informational/audit only — **not** authorization authority |
| autonomous + `!allowed` | Always denied |

Client-provided `approved_by_user` / `preapproved` booleans are **not** authorization authority.
Privileged MCP execution requires a validated persisted ApprovalService decision whose
scope fingerprint matches the exact tool (`mcp_tool` scope: server_id + tool_id + tool_name + effect).

Revocation is re-checked immediately before `call_managed_tool` / `invoke_tool`.

Manual invoke without `approval_id` for a blocked / approval-required tool returns **428**
with a durable approval request; after ApprovalService decide, re-invoke with `approval_id`.

## Policy

- `network_policy=block` → no external MCP HTTP / OAuth discovery
- `network_policy=ask` → creates/returns a scoped `ApprovalService` request
  (server id + endpoint + effect). Changing the endpoint invalidates the approval.
  Global magic booleans are not the primary path.
- Loopback HTTP follows local conventions
- `subprocess_policy=ask` uses the same scoped approval model for stdio start
- `GET /api/mcp/servers/{id}/auth` is **cached status only**; discovery is
  `POST .../auth/discover` or `?discover=true`
- `mcp.max_tool_calls` is enforced once per actual execution path
  (`call_managed_tool` / `_invoke_direct` / plugin-owned invoke) to avoid double-counting mirrors

## Secret storage

Deleting an MCP server enumerates all MCP-owned secret refs (bearer, stdio env,
OAuth access/refresh). If keyring deletion fails, the server row is **retained** and
the API returns `ok: false` so cleanup remains recoverable. Partial OAuth token writes
roll back newly stored access tokens when refresh storage fails.

## Cancellation / idempotency

Cancelling execution A cancels only that request’s waiter (and best-effort
`notifications/cancelled` on stdio / closes the HTTP response stream). It must not
poison later calls on the shared client.

Execution idempotency keys are scoped to `(server_id, tool_id, idempotency_key)`
(migration 16).

## Verification commands

```bash
cd backend
python3 -m unittest tests.test_mcp_host_management tests.test_mcp_host_hardening_regressions tests.test_mcp_host_integration tests.test_mcp_protocol_compliance -v
cd ..
npm run typecheck
npm run lint
npm run build
```

Live interop (opt-in, credentials required):

1. GitHub PAT → Bearer connect → read-only tool call
2. Hugging Face token → Bearer connect
3. Local plugin stdio (Chrome DevTools / Desktop Commander) → plugin-owned path, no second process

Without credentials, live interop is **NOT_VERIFIED**.

## Known limitations

- MRTR / `input_required` not completed end-to-end (explicitly unsupported)
- Official `mcp` Python SDK not vendored (dependency conflict); wire tests use strict local fixtures
- HTTP “alive” means local client open; UI uses `connection_status_effective` / `ready|connected`
- JSON Schema 2020-12 validation uses `jsonschema` Draft202012 with external `$ref` rejected (SSRF)
- CIMD / DCR not implemented as automatic registration — configured client id / metadata URL required
- Live GitHub / Hugging Face interop depends on operator credentials

## Bridge copies

Canonical plugin bridge remains `plugins/_shared/mcp_bridge.py`. Pack/generate still
copies into plugin folders. The in-process host does **not** replace that path for
plugin-owned servers.
