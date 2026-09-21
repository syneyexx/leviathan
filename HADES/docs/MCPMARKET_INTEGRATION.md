# MCPMarket integration

MCPMarket.com is an **external capability discovery** source. HADES remains authoritative.

```text
MCPMarket public pages
  → MCPMarketConnector (metadata only)
  → normalize CanonicalCapability (untrusted)
  → operator approval
  → HADES MCP Host create/connect
  → tools/list
  → Capability Intelligence
  → HADES Brain
```

The connector **does not** execute tools, install packages, clone repositories, or grant credentials.

## Verified official surface (2026-09-14)

Inspected live public pages. **No official REST management API, search API, auth API, install API, Toolkit catalog API, or rate-limit documentation was published.**

| Item | Contract |
|---|---|
| Directory | `https://mcpmarket.com/` |
| Server page | `https://mcpmarket.com/server/{slug}` — name, publisher (`by X`), description, features |
| Skills index | `https://mcpmarket.com/tools/skills` |
| Skill page | `https://mcpmarket.com/tools/skills/{slug}` — Agent Skills / SKILL.md-style guidance |
| Hosting | Vercel; automated clients may receive HTTP 429 challenge |
| Skills vs MCP | Skills teach *how*; MCP servers connect to tools/data |
| Toolkits | No first-class official Toolkit API. Toolkit-**shaped** listings normalize as `mcp_provider` with a focused tool surface when metadata says so |
| JSON-LD | Parsed when present; not required |
| HADES → marketplace export | Out of scope |

Lookup uses those public pages (slugified requirement). There is no invented `/api/search`.

## Trust pipeline

`discovered → untrusted → inspect schema/side effects/credentials → HADES policy → operator approval → MCP Host draft`

Trust ladder remains `untrusted / manual / verified / trusted`. MCPMarket cannot climb it.

HADES never silently:

- install an arbitrary package
- run a Docker image
- clone and execute an unknown repository
- grant credentials
- enable autonomous tool use

because a listing exists.

Prompt-like skill content is untrusted external context (`instruction_authority=false`). It is never system authority.

## Caching

Identical unresolved requirement + mission id is served from `DiscoveryCache` (default TTL 900s). Invalidate on explicit refresh. Marketplace failure states: `available`, `degraded`, `unavailable`, `auth_required`, `needs_setup`, `policy_blocked`, `unknown`.

Local HADES continues if MCPMarket is offline. Startup does not call MCPMarket.

## Secrets

Connection tokens use HADES MCP Host secret storage. Marketplace metadata must not appear in agent prompts as credentials. No marketplace API key is required today because no official auth API exists.

## Provenance

Normalized records keep marketplace entry, URL, publisher, last discovery, trust=`untrusted`, connection_state=`discovered`.

## GUI

Minimal controls on the existing MCP catalog tab: search, inspect, prepare draft, trust/status. Not a clone of mcpmarket.com.

## Outbound HADES MCP server

Not part of this campaign.
