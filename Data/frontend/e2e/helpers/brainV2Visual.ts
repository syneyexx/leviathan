/**
 * Playwright helper — installs Screen 1 Brain deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  BRAIN_V2_VISUAL_FIXTURE,
  BRAIN_V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/brainV2VisualFixture";

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function isControlPlaneApi(url: URL): boolean {
  return url.pathname === "/api" || url.pathname.startsWith("/api/");
}

export async function installBrainV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean }).__LV_V2_VISUAL_FIXTURE__ = true;
    },
    { frozen: BRAIN_V2_VISUAL_FROZEN_ISO },
  );

  await page.route("**/*", async (route) => {
    const reqUrl = route.request().url();
    let url: URL;
    try {
      url = new URL(reqUrl);
    } catch {
      return route.fallback();
    }
    if (!isControlPlaneApi(url)) return route.fallback();

    const path = url.pathname;
    const f = BRAIN_V2_VISUAL_FIXTURE;

    if (path === "/api/health") return json(route, f.health);
    if (path === "/api/brain/catalog") return json(route, { ...f.graph, page: {complete: true, next_source: 12, next_offset: 0} });
    if (path === "/api/brain/graph") return json(route, f.graph);
    if (path === "/api/brain/stats") {
      return json(route, { stats: f.graph.stats, truth: f.graph.truth });
    }
    if (path === "/api/evidence" || path.startsWith("/api/evidence/")) {
      return json(route, f.evidence);
    }
    if (path === "/api/memory" || path.startsWith("/api/memory/")) {
      return json(route, f.memory);
    }
    if (path === "/api/workers/dashboard") return json(route, f.workersDashboard);
    if (path === "/api/cognition/health") return json(route, f.cognitionHealth);
    if (path === "/api/jobs") {
      return json(route, { jobs: f.workersDashboard.queued_jobs });
    }

    if (path === "/api/events") return json(route, { events: [], latest_sequence: 0 });

    // Shared V2 chrome / adjacent pages
    if (path === "/api/conversations" || path.startsWith("/api/conversations/")) {
      return json(route, {
        conversations: [],
        conversation: null,
        messages: [],
        truth: { visual_fixture: true },
      });
    }
    if (path === "/api/tasks" || path.startsWith("/api/tasks/")) {
      return json(route, { tasks: [], summary: {}, truth: { visual_fixture: true } });
    }
    if (path.startsWith("/api/events/stream")) {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "event: ping\ndata: {}\n\n",
      });
    }

    return json(route, { ok: true, truth: { visual_fixture_default: true } });
  });
}
