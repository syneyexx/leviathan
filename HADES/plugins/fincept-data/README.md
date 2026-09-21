# Fincept Data — HADES plugin

Native HADES integration for the Fincept Data API. This adapter deliberately **does not vendor or import FinceptTerminal source code**. FinceptTerminal is AGPL-3.0; HADES talks to the hosted Fincept API over its documented authentication boundary instead.

## What this gives HADES

- Secure API access to `https://api.fincept.in` with `FINCEPT_API_KEY` from the process environment.
- Official documentation discovery through `https://docs.fincept.in/llms.txt`.
- Autonomous, read-only `GET` access for research/data retrieval.
- Manual `POST` access for endpoints such as analytics and QuantLib computations.
- Manual bounded multi-GET evidence packs (maximum five requests).
- Provenance on every successful data response: exact request URI, retrieval time, endpoint, status, content hash and Fincept rate-limit headers.
- A `hades_knowledge` evidence envelope in API results so source identity is preserved when HADES uses Fincept output in research and knowledge workflows.

## Security model

The adapter is intentionally narrower than a generic HTTP client:

1. The host is pinned to `api.fincept.in` and HTTPS.
2. Redirects are not followed, so `X-API-Key` cannot be forwarded to another host.
3. Ambient HTTP proxy variables are ignored by this plugin.
4. API keys are read from environment variables only and never accepted as tool arguments.
5. Generic data tools block `/user`, `/guest`, `/auth`, `/billing`, `/payment`, `/subscription` and `/admin` paths.
6. Responses and POST bodies are size bounded.
7. HADES' normal plugin network policy still applies.

## Configuration

Set the Fincept key in the environment of the HADES backend/desktop process:

```text
FINCEPT_API_KEY=fk_user_...
```

Optional, only when the Fincept session requires it:

```text
FINCEPT_SESSION_TOKEN=...
```

Never place either value in `hades-plugin.json`, a tool input, Git, screenshots or logs.

## Tools

| Tool | Autonomous | Purpose |
|---|---:|---|
| `fincept_catalog` | yes | Search Fincept's official docs index for capabilities/endpoints. |
| `fincept_get` | yes | Read one non-sensitive relative API endpoint with query parameters. |
| `fincept_batch_get` | no | Fetch up to five curated GET endpoints with a bounded delay. |
| `fincept_post` | no | Call a relative POST endpoint with a JSON body. Kept manual because calls can consume credits or run expensive analytics. |
| `fincept_doctor` | no | Verify configuration; optional `/user/profile` connectivity probe without returning profile contents. |

HADES v0.4.1 originally treated autonomy at plugin level. This integration adds per-tool autonomy filtering so `fincept_post`, `fincept_batch_get` and `fincept_doctor` cannot be selected by the autonomous tool loop even though the read-only plugin surface is autonomous.

## Examples

Read-only endpoint:

```json
{
  "path": "/some/data/endpoint",
  "query": {"symbol": "AAPL"}
}
```

Manual POST:

```json
{
  "path": "/some/analytics/endpoint",
  "query": {},
  "body": {"input": 123}
}
```

Use `fincept_catalog` first when the exact current Fincept endpoint path is unknown. The plugin intentionally does not hard-code an invented list of the advertised source catalog; the upstream API/documentation remains the source of truth.

## Evidence contract

Successful API calls include:

```json
{
  "hades_knowledge": [
    {
      "title": "Fincept API GET /...",
      "uri": "https://api.fincept.in/...",
      "source_type": "fincept_api",
      "content": "...",
      "metadata": {
        "provider": "Fincept",
        "endpoint": "/...",
        "retrieved_at": "...",
        "content_sha256": "...",
        "rate_limit": {}
      }
    }
  ]
}
```

This is evidence, not model-weight training. HADES should retain the source URI and timestamp whenever Fincept output becomes reusable knowledge.

## Tests

```text
python -m unittest discover -s tests -v
```

The test suite covers host escape/path traversal prevention, sensitive endpoint blocking, API-key non-disclosure, bounded responses and documentation filtering without credentials.
