/**
 * Playwright helper — installs Screen 1 Research deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  RESEARCH_V2_VISUAL_FIXTURE,
  RESEARCH_V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/researchV2VisualFixture";

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

export async function installResearchV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean }).__LV_V2_VISUAL_FIXTURE__ = true;
    },
    { frozen: RESEARCH_V2_VISUAL_FROZEN_ISO },
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
    const method = route.request().method();
    const f = RESEARCH_V2_VISUAL_FIXTURE;

    if (path === "/api/health") return json(route, f.health);
    if (path === "/api/research/budgets") return json(route, f.budgets);
    if (path === "/api/research/web/readiness") return json(route, f.webReadiness);
    if (path === "/api/research/web/probe" && method === "POST") {
      return json(route, { probe: { status: "ok" }, truth: { visual_fixture: true } });
    }
    if (path === "/api/research" && method === "GET") {
      return json(route, { projects: f.projects });
    }
    if (path === "/api/research" && method === "POST") {
      return json(route, { project: f.projects[0] });
    }
    const projectMatch = path.match(/^\/api\/research\/([^/]+)$/);
    if (projectMatch && method === "GET") {
      const id = decodeURIComponent(projectMatch[1]);
      const proj = f.projects.find((p) => p.project_id === id) ?? f.projects[0];
      return json(route, { project: { ...proj, workers: f.projectWorkers.workers } });
    }
    if (projectMatch && (method === "PUT" || method === "PATCH")) {
      const id = decodeURIComponent(projectMatch[1]);
      const proj = f.projects.find((p) => p.project_id === id) ?? f.projects[0];
      return json(route, { project: proj });
    }
    const runMatch = path.match(/^\/api\/research\/([^/]+)\/(run|cancel|resume|plan|deepen)$/);
    if (runMatch && method === "POST") {
      const id = decodeURIComponent(runMatch[1]);
      const proj = f.projects.find((p) => p.project_id === id) ?? f.projects[0];
      const status = runMatch[2] === "cancel" ? "cancelling" : "researching";
      return json(route, {
        project: { ...proj, status, workers: f.projectWorkers.workers },
      });
    }
    const nested = path.match(/^\/api\/research\/([^/]+)\/(workers|sources|evidence|claims|conflicts|gaps|report)$/);
    if (nested && method === "GET") {
      const kind = nested[2];
      if (kind === "workers") return json(route, f.projectWorkers);
      if (kind === "sources") return json(route, { sources: f.sources });
      if (kind === "evidence") return json(route, { evidence: f.evidence });
      if (kind === "claims") return json(route, { claims: f.claims });
      if (kind === "conflicts") return json(route, f.conflicts);
      if (kind === "gaps") return json(route, f.gaps);
      if (kind === "report") return json(route, f.report);
    }

    if (path === "/api/workers/dashboard") return json(route, f.workersDashboard);
    if (path === "/api/knowledge") return json(route, f.knowledgeDocuments);
    if (path === "/api/models" || path === "/api/models/refresh") return json(route, f.models);
    if (path === "/api/datasets" || path.startsWith("/api/datasets")) {
      return json(route, { datasets: [], jobs: [], truth: { visual_fixture: true } });
    }
    if (path === "/api/conversations" || path.startsWith("/api/conversations/")) {
      return json(route, {
        conversations: [],
        conversation: null,
        messages: [],
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
