import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  server: { middlewareMode: true },
});

test.after(async () => vite.close());

test("brain adapter separates content edit vs layout rights", async () => {
  const adapter = await vite.ssrLoadModule("/components/hades/pages/brain-graph-adapter.ts");
  assert.equal(adapter.contentEditableForId("memory_1"), false);
  assert.equal(adapter.layoutMovableForId("memory_1"), true);
  assert.equal(adapter.contentEditableForId("core_hades"), false);
  assert.equal(adapter.layoutMovableForId("core_hades"), true);
  assert.equal(adapter.contentEditableForId("node_manual"), true);
});

test("fitViewportToNodes uses visible bounds instead of fixed zoom", async () => {
  const adapter = await vite.ssrLoadModule("/components/hades/pages/brain-graph-adapter.ts");
  const tight = adapter.fitViewportToNodes([
    { x: 100, y: 100 },
    { x: 200, y: 180 },
  ]);
  const wide = adapter.fitViewportToNodes([
    { x: 0, y: 0 },
    { x: 900, y: 600 },
  ]);
  assert.ok(tight.zoom > wide.zoom, "tight cluster should zoom in more than wide spread");
  assert.notEqual(tight.zoom, 0.88);
});

test("relation validation blocks self-link and duplicates", async () => {
  const adapter = await vite.ssrLoadModule("/components/hades/pages/brain-graph-adapter.ts");
  assert.match(adapter.validateRelationCreate("a", "a", []) || "", /zichzelf/i);
  assert.match(adapter.validateRelationCreate("a", "b", [{ source: "a", target: "b" }]) || "", /bestaat/i);
  assert.equal(adapter.validateRelationCreate("a", "b", []), null);
});

test("hash deeplink helpers select c/t/id", async () => {
  const helpers = await vite.ssrLoadModule("/lib/hash-query.ts");
  assert.equal(helpers.readHashSelection(["c", "id"], "#/chat?c=conv-1"), "conv-1");
  assert.equal(helpers.readHashSelection(["t", "id"], "#/tasks?t=task-9"), "task-9");
  assert.equal(helpers.readHashSelection(["id"], "#/memory?id=mem-3"), "mem-3");
  assert.equal(helpers.readHashSelection(["c", "id"], "#/chat"), null);
});

test("brain graph wires pointercancel and zoom controls", async () => {
  const source = await vite.ssrLoadModule("/components/hades/pages/brain-graph.tsx");
  assert.equal(typeof source.BrainGraph, "function");
  const fs = await import("node:fs/promises");
  const graphSrc = await fs.readFile(new URL("../components/hades/pages/brain-graph.tsx", import.meta.url), "utf8");
  assert.match(graphSrc, /onPointerCancel/);
  assert.match(graphSrc, /preserveAspectRatio/);
  const pageSrc = await fs.readFile(new URL("../components/hades/pages/brain-page.tsx", import.meta.url), "utf8");
  assert.match(pageSrc, /fitViewportToNodes/);
  assert.match(pageSrc, /saveBrainLayoutPosition/);
  assert.match(pageSrc, /layoutMovable/);
  assert.doesNotMatch(pageSrc, /brain-mock-data/);
});

test("brain node click opens on-demand full detail dialog without turning drags into clicks", async () => {
  const fs = await import("node:fs/promises");
  const graphSrc = await fs.readFile(new URL("../components/hades/pages/brain-graph.tsx", import.meta.url), "utf8");
  const hookSrc = await fs.readFile(new URL("../components/hades/pages/use-brain-node-detail.tsx", import.meta.url), "utf8");
  const dialogSrc = await fs.readFile(new URL("../components/hades/pages/brain-node-detail-dialog.tsx", import.meta.url), "utf8");
  const apiSrc = await fs.readFile(new URL("../lib/brain-node-detail-api.ts", import.meta.url), "utf8");
  const routeSrc = await fs.readFile(new URL("../backend/brain_routes.py", import.meta.url), "utf8");

  assert.match(graphSrc, /NODE_CLICK_TOLERANCE_PX/);
  assert.match(graphSrc, /Math\.hypot/);
  assert.match(graphSrc, /openNodeDetail\(node\)/);
  assert.match(hookSrc, /fetchBrainNodeDetail/);
  assert.match(dialogSrc, /detail\.sections/);
  assert.match(dialogSrc, /Open gekoppelde pagina/);
  assert.match(apiSrc, /\/brain\/nodes\/\$\{encodeURIComponent\(nodeId\)\}\/detail/);
  assert.match(routeSrc, /\/brain\/nodes\/\{node_id\}\/detail/);
  assert.match(routeSrc, /build_brain_node_detail/);
});
