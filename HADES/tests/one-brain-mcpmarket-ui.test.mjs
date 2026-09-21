import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("MCPMarket discovery lives on the existing MCP page, not a new app", async () => {
  const page = await read("components/hades/pages/mcp-page.tsx");
  const api = await read("lib/hades-api.ts");
  assert.match(page, /mcpmarket-discovery/);
  assert.match(page, /mcpmarketSearch/);
  assert.match(page, /mcpmarketPrepareConnection/);
  assert.match(page, /untrusted/);
  assert.doesNotMatch(page, /clone MCPMarket/);
  assert.match(api, /\/mcpmarket\/search/);
  assert.match(api, /\/mcpmarket\/prepare-connection/);
});

test("One Brain HTTP client is not a separate product GUI", async () => {
  const api = await read("lib/hades-api.ts");
  const app = await read("components/hades/hades-app.tsx");
  assert.doesNotMatch(app, /mcpmarket-page/);
  assert.doesNotMatch(api, /\/marketplace\/app/);
});
