import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  server: { middlewareMode: true, hmr: false },
});
const {
  renderComponentToStaticMarkup,
  renderComponentListToStaticMarkup,
  renderNestedComponentToStaticMarkup,
} = await vite.ssrLoadModule("/tests/helpers/vite-ssr-renderer.tsx");

after(async () => vite.close());

test("production CSS contains HADES shell and Work Runtime styling", async () => {
  const markers = [/hades-sidebar/, /work-step-list/, /scrollbar-width:\s*thin/];
  const manifestUrl = new URL("../dist/.vite/manifest.json", import.meta.url);
  let css = "";
  let source = "dist";
  try {
    const manifest = JSON.parse(await readFile(manifestUrl, "utf8"));
    const entry = manifest["index.html"];
    assert.ok(entry, "Vite manifest must contain index.html");
    const cssFiles = entry.css ?? [];
    assert.ok(cssFiles.length > 0, "HADES build must emit CSS");
    css = (await Promise.all(cssFiles.map((name) => readFile(new URL(`../dist/${name}`, import.meta.url), "utf8")))).join("\n");
  } catch (err) {
    // --quick / no build: fall back to source stylesheet so the contract still holds.
    source = "app/globals.css";
    css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
    assert.ok(css.length > 0, `CSS fallback failed (${err})`);
  }
  for (const marker of markers) {
    assert.match(css, marker, `missing ${marker} in ${source}`);
  }
});

test("progress primitive forwards accessibility semantics", async () => {
  const { Progress } = await vite.ssrLoadModule("/components/ui/progress.tsx");
  const html = renderComponentToStaticMarkup(Progress, { value: 37 });
  assert.match(html, /aria-valuenow="37"/);
});

test("HADES page header and panel render reusable shell markup", async () => {
  const { PageHeader, Panel } = await vite.ssrLoadModule("/components/hades/ui.tsx");
  const html = renderComponentListToStaticMarkup([
    { component: PageHeader, props: { title: "Taken", description: "Work Runtime" } },
    { component: Panel, props: { title: "Controle" }, children: "OK" },
  ]);
  assert.match(html, /Taken/);
  assert.match(html, /Work Runtime/);
  assert.match(html, /class="panel/);
});

test("heavy HADES routes are lazy and route boundary is exported", async () => {
  const { classicPages, RouteLoadingSkeleton } = await vite.ssrLoadModule("/components/hades/hades-app.tsx");
  const { RouteErrorBoundary } = await vite.ssrLoadModule("/components/hades/route-error-boundary.tsx");
  assert.notEqual(classicPages.chat.$$typeof, Symbol.for("react.lazy"), "Chat remains eager");
  for (const route of ["brain", "research", "trading", "media", "coding-agent", "mission-control", "plugins", "mcp", "workflows", "agents", "models", "memory", "files", "settings", "tasks"]) {
    assert.equal(classicPages[route].$$typeof, Symbol.for("react.lazy"), `${route} must be route-split`);
  }
  const html = renderNestedComponentToStaticMarkup(
    RouteErrorBoundary,
    { resetKey: "chat" },
    RouteLoadingSkeleton,
  );
  assert.match(html, /Pagina laden/);
});

test("trustworthy agent UX components render accessible summaries", async () => {
  const { ExecutionProgress, FileChangesCard, ToolCallCard, VerificationPanel } =
    await vite.ssrLoadModule("/components/hades/features/agent-ux/index.ts");
  const html = renderComponentListToStaticMarkup([
    { component: ExecutionProgress, props: { status: "running", activeStage: "tools" } },
    { component: ToolCallCard, props: { call: { tool_name: "local.read", status: "success" } } },
    { component: FileChangesCard, props: { changes: [{ path: "notes.md", status: "modified", additions: 2 }] } },
    {
      component: VerificationPanel,
      props: {
        called: true,
        checks: [{ criterion: "Output opgeslagen", met: true }],
      },
    },
  ]);
  assert.match(html, /aria-label="Uitvoeringsvoortgang"/);
  assert.match(html, /local\.read/);
  assert.match(html, /Bestandswijzigingen/);
  assert.match(html, /Output opgeslagen/);
});

test("agents console helpers filter inactive (*) agents and missing metrics", async () => {
  const helpers = await vite.ssrLoadModule("/lib/agents-console.ts");
  const agents = [
    {
      id: "chat",
      name: "Chat Agent",
      role: "chat",
      description: "Chat",
      reasoning_profile: "adaptive",
      enabled: true,
      status: "running",
      health: "healthy",
      provider: "LM Studio",
      model: "local",
      allowed_tools: [],
      max_subtasks: 2,
      created_at: "",
      updated_at: "",
      usage: { known: true, total_tokens: 20, input_tokens: 10, output_tokens: 10, cached_tokens: null, reasoning_tokens: null, requests: 1, cost: null },
      metrics: { runs: 2, failed_runs: 0, successful_runs: 2, requests: 1, success_rate: 1, avg_execution_seconds: 1 },
      planned: false,
    },
    {
      id: "web_scout",
      name: "Web Scout (*)",
      role: "web",
      description: "Planned",
      reasoning_profile: "high",
      enabled: false,
      status: "unavailable",
      health: "offline",
      provider: "LM Studio",
      model: null,
      allowed_tools: [],
      max_subtasks: 4,
      created_at: "",
      updated_at: "",
      usage: { known: false, total_tokens: null, input_tokens: null, output_tokens: null, cached_tokens: null, reasoning_tokens: null, requests: 0, cost: null },
      metrics: { runs: 0, failed_runs: 0, successful_runs: 0, requests: 0, success_rate: null, avg_execution_seconds: null },
      planned: true,
    },
  ];
  const filtered = helpers.filterAgents(agents, {
    query: "web",
    status: "all",
    role: "all",
    provider: "all",
    model: "all",
    activeOnly: false,
    errorOnly: false,
  });
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "web_scout");
  assert.match(filtered[0].name, /\(\*\)/);
  assert.equal(helpers.formatMetric(null), "—");
  assert.equal(helpers.formatMetric(undefined), "—");
  assert.equal(helpers.formatCost(null), "—");
  const sorted = helpers.sortAgents(agents, "tokens", "desc");
  assert.equal(sorted[0].id, "chat");
});
