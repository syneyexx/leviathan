/**
 * Shared API stubs for bounded operator E2E.
 * Returns honest empty/fixture payloads — never pretends production health.
 * Only intercepts HTTP `/api/...` control-plane paths (not `/src/api/*.ts` modules).
 */
import type { Page, Route } from "@playwright/test";

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function isControlPlaneApi(url: URL): boolean {
  // Exact control-plane prefix — do not match frontend source `/src/api/...`.
  return url.pathname === "/api" || url.pathname.startsWith("/api/");
}

export async function installApiStubs(page: Page): Promise<void> {
  await page.route("**/*", async (route) => {
    const reqUrl = route.request().url();
    let url: URL;
    try {
      url = new URL(reqUrl);
    } catch {
      return route.continue();
    }
    if (!isControlPlaneApi(url)) {
      return route.continue();
    }
    const path = url.pathname;

    if (path === "/api/health") {
      return json(route, {
        status: "ok",
        truth: { e2e_stub: true, not_production_health: true },
      });
    }
    if (path.startsWith("/api/brain/graph") || path === "/api/brain/catalog") {
      return json(route, {
        nodes: [
          {
            id: "e2e:node:1",
            type: "knowledge.document",
            label: "E2E Node",
            created_at: null,
            meta: {},
          },
        ],
        edges: [],
        stats: { node_count: 1, edge_count: 0 },
        page: {complete: true, next_source: 12, next_offset: 0},
        truth: { e2e_stub: true },
      });
    }
    if (path.startsWith("/api/brain/stats")) {
      return json(route, { stats: { node_count: 1 }, truth: { e2e_stub: true } });
    }
    if (path === "/api/workers/dashboard") {
      return json(route, {
        supervisor: { health: "RUNNING" },
        pools: [],
        workers: [],
        truth: { e2e_stub: true },
      });
    }
    if (path === "/api/workers") {
      return json(route, { workers: [], truth: { e2e_stub: true } });
    }
    if (path.startsWith("/api/agents")) {
      return json(route, {
        agents: [],
        summary: {},
        system: [],
        missions: [],
        events: [],
        truth: { e2e_stub: true },
      });
    }
    if (path.startsWith("/api/system/telemetry") || path.startsWith("/api/performance")) {
      return json(route, { dashboard: {}, truth: { e2e_stub: true } });
    }
    if (path.startsWith("/api/events/stream")) {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "event: ping\ndata: {}\n\n",
      });
    }
    // Default: empty JSON so pages can render without a live backend.
    return json(route, { ok: true, truth: { e2e_stub: true } });
  });
}
