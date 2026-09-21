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
const { renderComponentToStaticMarkup } = await vite.ssrLoadModule("/tests/helpers/vite-ssr-renderer.tsx");

after(async () => vite.close());

test("Brain graph adapter honors backend edit and layout permissions", async () => {
  const { apiNodesToGraph } = await vite.ssrLoadModule("/components/hades/pages/brain-graph-adapter.ts");
  const now = "2026-09-11T12:00:00+00:00";
  const graph = apiNodesToGraph([
    {
      id: "node_backend_locked",
      label: "Backend locked",
      kind: "note",
      description: "policy test",
      tags: [],
      source: "test",
      created_at: now,
      updated_at: now,
      content_editable: false,
      layout_movable: false,
      pinned: true,
    },
    {
      id: "node_fallback",
      label: "Fallback",
      kind: "note",
      description: "fallback test",
      tags: [],
      source: "test",
      created_at: now,
      updated_at: now,
    },
  ]);

  assert.equal(graph[0].contentEditable, false);
  assert.equal(graph[0].layoutMovable, false);
  assert.equal(graph[0].pinned, true);
  assert.equal(graph[1].contentEditable, true);
  assert.equal(graph[1].layoutMovable, true);
});

test("Brain page guards persisted viewport hydration and failed drag rollback", async () => {
  const source = await readFile(
    new URL("../components/hades/pages/brain-page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /viewportHydratedRef\.current = true/);
  assert.match(source, /if \(!viewportHydratedRef\.current\) return;/);
  assert.match(source, /dragOriginRef\.current = \{ nodeId: node\.id, x: node\.x, y: node\.y \}/);
  assert.match(source, /event\.type === "pointercancel"/);
  assert.match(source, /item\.id === nodeId && item\.x === x && item\.y === y/);
  assert.match(source, /connect_to: selectedNode\?\.id/);
  assert.doesNotMatch(source, /const snapshot = links/);
});

test("Brain selection changes clear stale edit and relation target state", async () => {
  const source = await readFile(
    new URL("../components/hades/pages/brain-page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(
    source,
    /useEffect\(\(\) => \{[\s\S]*?setEditing\(false\);[\s\S]*?setRelationTargetId\(""\);[\s\S]*?\}, \[selectedId\]\);/,
  );
});

test("Brain cluster and compact view modes have real rendering behavior", async () => {
  const source = await readFile(
    new URL("../components/hades/pages/brain-graph.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /const clusterRegions = useMemo/);
  assert.match(source, /viewMode === "clusters"/);
  assert.match(source, /cluster\.label} · \{cluster\.count/);
  assert.match(source, /const compact = viewMode === "compact"/);
  assert.match(source, /!compact \? <path className="b2-link-flow"/);
  assert.match(source, /MAX_DECORATED_NODES = 180/);
  assert.match(source, /visibleNodes\.slice\(0, MAX_DECORATED_NODES\)/);
  assert.match(source, /visibleLinks\.map\(\(link\) =>/);
  assert.doesNotMatch(source, /import \{ CLUSTERS,/);

  const { BrainGraph } = await vite.ssrLoadModule("/components/hades/pages/brain-graph.tsx");
  const baseNode = {
    description: "test",
    source: "test",
    persistent: true,
    createdAt: "11-09-2026",
    updatedAt: "11-09-2026",
    tags: [],
    contentEditable: false,
    layoutMovable: true,
    pinned: false,
  };
  const nodes = [
    {
      ...baseNode,
      id: "core_hades",
      label: "HADES",
      kind: "core",
      icon: "core",
      x: 500,
      y: 325,
      cluster: "Architectuur",
    },
    {
      ...baseNode,
      id: "memory_demo",
      label: "Demo memory",
      kind: "memory",
      icon: "memory",
      x: 650,
      y: 360,
      cluster: "Geheugen & Kennis",
    },
  ];
  const links = [
    {
      id: "core-memory",
      source: "core_hades",
      target: "memory_demo",
      relation: "onthoudt",
    },
  ];
  const commonProps = {
    nodes,
    links,
    visibleNodes: nodes,
    visibleLinks: links,
    selectedId: "core_hades",
    hoveredId: null,
    viewport: { x: 0, y: 0, zoom: 1 },
    drag: null,
    kindFilter: "all",
    surfaceRef: { current: null },
    svgRef: { current: null },
    onWheel: () => {},
    onSurfacePointerDown: () => {},
    onPointerMove: () => {},
    onPointerEnd: () => {},
    onNodePointerDown: () => {},
    onSelectNode: () => {},
    onHoverNode: () => {},
    onZoom: () => {},
    onResetView: () => {},
    onFitView: () => {},
    onFullscreen: () => {},
    onLegendFilter: () => {},
  };

  const clusterHtml = renderComponentToStaticMarkup(BrainGraph, { ...commonProps, viewMode: "clusters" });
  assert.match(clusterHtml, /Architectuur · 1/);
  assert.match(clusterHtml, /Geheugen &amp; Kennis · 1/);
  assert.match(clusterHtml, /b2-cluster/);

  const compactHtml = renderComponentToStaticMarkup(BrainGraph, { ...commonProps, viewMode: "compact" });
  assert.match(compactHtml, /b2-link/);
  assert.doesNotMatch(compactHtml, /b2-link-flow/);
  assert.doesNotMatch(compactHtml, /b2-node-orbit/);
  assert.doesNotMatch(compactHtml, /b2-node-chip/);
});
