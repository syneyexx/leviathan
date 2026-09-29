/**
 * Playwright helper — installs Screen 1 deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  V2_VISUAL_FIXTURE,
  V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/dashboardV2VisualFixture";

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

export async function installDashboardV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean }).__LV_V2_VISUAL_FIXTURE__ = true;
    },
    { frozen: V2_VISUAL_FROZEN_ISO },
  );

  await page.route("**/*", async (route) => {
    const reqUrl = route.request().url();
    let url: URL;
    try {
      url = new URL(reqUrl);
    } catch {
      return route.continue();
    }
    if (!isControlPlaneApi(url)) return route.continue();

    const path = url.pathname;
    const f = V2_VISUAL_FIXTURE;

    if (path === "/api/health") return json(route, f.health);
    if (path === "/api/system/telemetry") return json(route, f.telemetry);
    if (path === "/api/agents/summary") return json(route, f.fleet);
    if (path === "/api/workers/dashboard") return json(route, f.workersDashboard);
    if (path === "/api/research") return json(route, f.research);
    if (path === "/api/market-sim/status") return json(route, f.marketStatus);
    if (path === "/api/market-sim/data") return json(route, f.marketSources);
    if (path === "/api/market-sim/strategies") return json(route, f.strategies);
    if (path === "/api/market-sim/market/bars") {
      const symbol = url.searchParams.get("symbol") || "BTC/USDT";
      return json(route, f.bars(symbol));
    }
    if (path === "/api/host/source-ingestion") return json(route, f.ingestion);
    if (path === "/api/host/overview") return json(route, f.hostOverview);
    if (path === "/api/models/status") return json(route, f.modelsStatus);
    if (path === "/api/models/providers") return json(route, f.providers);
    if (path === "/api/models/hardware") {
      return json(route, {
        hardware: { devices: f.telemetry.gpu.devices },
        reservations: [],
        residency: [],
      });
    }
    if (path === "/api/tasks/activity") return json(route, f.taskActivity);
    if (path === "/api/tasks/summary") return json(route, f.taskSummary);
    if (path === "/api/jobs") return json(route, { jobs: f.workersDashboard.queued_jobs });

    // Chat / Tasks pages share V2 chrome — return honest empty shapes so they mount.
    if (path === "/api/conversations" || path.startsWith("/api/conversations/")) {
      return json(route, { conversations: [], conversation: null, messages: [], truth: { visual_fixture: true } });
    }
    if (path === "/api/models" || path === "/api/models/") {
      return json(route, { models: [], truth: { visual_fixture: true } });
    }
    if (path === "/api/coding/status") {
      return json(route, { enabled: false, agents_enabled: false, truth: { visual_fixture: true } });
    }
    if (path === "/api/capabilities") {
      return json(route, { capabilities: [], truth: { visual_fixture: true } });
    }
    if (path === "/api/tasks" || path.startsWith("/api/tasks/")) {
      if (path === "/api/tasks/activity") return json(route, f.taskActivity);
      if (path === "/api/tasks/summary") return json(route, f.taskSummary);
      return json(route, {
        tasks: [],
        summary: f.taskSummary.summary,
        truth: { visual_fixture: true },
      });
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
