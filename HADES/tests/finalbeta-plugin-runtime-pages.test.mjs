import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA Plugin & Runtime pages are wired as pixel-locked shells", async () => {
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");
  const indexCss = await read("components/hades/styles/finalbeta/index.css");

  const performance = await read("components/hades/finalbeta/pages/performance-page.tsx");
  const plugins = await read("components/hades/finalbeta/pages/tools-page.tsx");
  const mcp = await read("components/hades/finalbeta/pages/mcp-page.tsx");
  const workflows = await read("components/hades/finalbeta/pages/workflows-page.tsx");
  const consolePage = await read("components/hades/finalbeta/pages/settings-console-page.tsx");

  const perfMocks = await read("components/hades/finalbeta/mocks/pr-performance.ts");
  const pluginsMocks = await read("components/hades/finalbeta/mocks/pr-plugins.ts");
  const mcpMocks = await read("components/hades/finalbeta/mocks/pr-mcp.ts");
  const workflowsMocks = await read("components/hades/finalbeta/mocks/pr-workflows.ts");
  const consoleMocks = await read("components/hades/finalbeta/mocks/pr-console.ts");

  const perfCss = await read("components/hades/styles/finalbeta/v2/pr-performance.css");
  const pluginsCss = await read("components/hades/styles/finalbeta/v2/pr-plugins.css");
  const mcpCss = await read("components/hades/styles/finalbeta/v2/pr-mcp.css");
  const workflowsCss = await read("components/hades/styles/finalbeta/v2/pr-workflows.css");
  const consoleCss = await read("components/hades/styles/finalbeta/v2/pr-console.css");

  assert.match(indexCss, /@import "\.\/v2\/pr-performance\.css"/);
  assert.match(indexCss, /@import "\.\/v2\/pr-plugins\.css"/);
  assert.match(indexCss, /@import "\.\/v2\/pr-mcp\.css"/);
  assert.match(indexCss, /@import "\.\/v2\/pr-workflows\.css"/);
  assert.match(indexCss, /@import "\.\/v2\/pr-console\.css"/);

  assert.match(perfCss, /\.fb-root \.prp-page/);
  assert.match(pluginsCss, /\.fb-root \.pr-plugins-page/);
  assert.match(mcpCss, /\.fb-root \.mcp-page/);
  assert.match(workflowsCss, /\.fb-root \.prw-page|\.fb-root \.pr-app \.prw-page/);
  assert.match(consoleCss, /\.fb-root \.prc-page/);

  assert.match(app, /page === "performance"/);
  assert.match(app, /page === "tools"/);
  assert.match(app, /page === "mcp"/);
  assert.match(app, /page === "workflows"/);
  assert.match(app, /page === "settings-console"/);
  assert.match(app, /SettingsConsolePage/);

  assert.match(performance, /data-page="performance"/);
  assert.match(performance, /Realtime monitoring, systeemtelemetrie/);
  assert.match(performance, /PR_PERF_SERVICES/);
  assert.match(perfMocks, /PR_PERF_KPIS/);
  assert.match(perfMocks, /NVIDIA RTX 4090/);

  assert.match(plugins, /data-page="plugins"/);
  assert.match(plugins, /Geïnstalleerde plugins/);
  assert.match(plugins, /Plugin installeren/);
  assert.match(plugins, /useHadesPlugins/);
  assert.match(plugins, /data-live="plugins"/);
  assert.match(plugins, /setEnabled/);
  assert.match(plugins, /More plugins\. More possibilities/);
  assert.match(plugins, /Ready betekent niet automatisch enabled/);
  assert.doesNotMatch(plugins, /PR_INSTALLED_PLUGINS/);
  assert.doesNotMatch(plugins, /PR_PLUGINS_STATS/);
  assert.match(pluginsMocks, /HADES-Chat/);
  assert.match(pluginsMocks, /VisionStudio/);
  // Presentation-only tab labels may still come from mocks until moved to ui-constants.
  assert.match(plugins, /PR_PLUGINS_TABS/);

  assert.match(mcp, /data-page="mcp"/);
  assert.match(mcp, /MCP servers/);
  assert.match(mcp, /Verbinden met marktplaats/);
  assert.match(mcp, /useHadesMcp/);
  assert.match(mcp, /data-live="mcp"/);
  assert.match(mcp, /connect|disconnect|reconnect/);
  assert.doesNotMatch(mcp, /MCP_SERVERS/);
  assert.doesNotMatch(mcp, /MCP_TOOLS/);
  assert.doesNotMatch(mcp, /MCP_TEST_RESULT/);
  assert.doesNotMatch(mcp, /MCP_STATUS/);
  assert.match(mcp, /MCP_TABS/);
  assert.match(mcp, /More tools\. Greater possibilities/);
  assert.match(mcp, /network_policy/);
  assert.match(mcpMocks, /Brave Search/);
  assert.match(mcpMocks, /filesystem/);

  assert.match(workflows, /data-page="workflows"/);
  assert.match(workflows, /Nieuwe workflow/);
  assert.match(workflows, /prw-canvas|Workflow canvas/);
  assert.match(workflows, /Bouw, beheer en automatiseer/);
  assert.match(workflowsMocks, /Nieuws analyse/);

  assert.match(consolePage, /data-page="console"/);
  assert.match(consolePage, /Log exporteren/);
  assert.match(consolePage, /PR_CONSOLE_LOGS/);
  assert.match(consolePage, /prc-page/);
  assert.match(consoleMocks, /PR_CONSOLE_LOGS/);
  assert.match(consoleMocks, /Observe\. Diagnose\. Control/);
});
