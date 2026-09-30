/**
 * Playwright helper — installs Screen 1 Agents deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  AGENTS_V2_VISUAL_FIXTURE,
  AGENTS_V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/agentsV2VisualFixture";

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

export async function installAgentsV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean }).__LV_V2_VISUAL_FIXTURE__ = true;
    },
    { frozen: AGENTS_V2_VISUAL_FROZEN_ISO },
  );

  let agents = JSON.parse(JSON.stringify(AGENTS_V2_VISUAL_FIXTURE.roster.agents)) as Array<
    Record<string, unknown>
  >;
  let missions = JSON.parse(JSON.stringify(AGENTS_V2_VISUAL_FIXTURE.missions.missions)) as Array<
    Record<string, unknown>
  >;

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
    const f = AGENTS_V2_VISUAL_FIXTURE;

    if (path === "/api/health") return json(route, f.health);
    if (path === "/api/system/telemetry" || path === "/api/telemetry/system") {
      return json(route, f.telemetry);
    }
    if (path === "/api/agents/roster") {
      return json(route, {
        agents,
        system: f.roster.system,
        summary: { ...f.roster.summary, agentCount: agents.filter((a) => !a.archived).length },
        entries: [...agents, ...f.roster.system],
      });
    }
    if (path === "/api/agents/summary") return json(route, { summary: f.roster.summary });
    if (path === "/api/agents/dashboard") return json(route, f.dashboard);
    if (path === "/api/agents/missions" && method === "GET") return json(route, { missions });
    if (path === "/api/agents/events") return json(route, f.events);
    if (path === "/api/agents/dataset-learning") return json(route, f.datasetLearning);
    if (path === "/api/capabilities" || path.startsWith("/api/capabilities")) {
      return json(route, f.capabilities);
    }
    if (path === "/api/models" || path === "/api/models/refresh") return json(route, f.models);
    if (path === "/api/knowledge") return json(route, f.knowledge);
    if (path === "/api/datasets" || path.startsWith("/api/datasets")) return json(route, f.datasets);
    if (path === "/api/workers") return json(route, f.workers);
    if (path === "/api/workers/dashboard") return json(route, f.workersDashboard);

    if (path === "/api/agents" && method === "POST") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const created = {
        ...agents[0],
        agentId: `agent_new_${agents.length}`,
        id: `agent_new_${agents.length}`,
        name: body.name || "New Agent",
        kind: body.kind || "research",
        role: body.role || "Specialist",
        origin: "user",
        mutable: true,
      };
      agents = [...agents, created];
      return json(route, { agent: created });
    }

    const agentMatch = path.match(/^\/api\/agents\/([^/]+)$/);
    if (agentMatch && method === "PATCH") {
      const id = decodeURIComponent(agentMatch[1]);
      const body = route.request().postDataJSON() as Record<string, unknown>;
      agents = agents.map((a) => (a.agentId === id ? { ...a, ...body, agentId: id, id } : a));
      const agent = agents.find((a) => a.agentId === id);
      return json(route, { agent });
    }

    const enableMatch = path.match(/^\/api\/agents\/([^/]+)\/(enable|disable|clone|archive)$/);
    if (enableMatch && method === "POST") {
      const id = decodeURIComponent(enableMatch[1]);
      const action = enableMatch[2];
      if (action === "clone") {
        const src = agents.find((a) => a.agentId === id) || agents[0];
        const cloned = {
          ...src,
          agentId: `agent_clone_${agents.length}`,
          id: `agent_clone_${agents.length}`,
          name: `${src.name} copy`,
          origin: "user",
          mutable: true,
          systemKey: undefined,
        };
        agents = [...agents, cloned];
        return json(route, { agent: cloned });
      }
      agents = agents.map((a) => {
        if (a.agentId !== id) return a;
        if (action === "enable") return { ...a, enabled: true, health: "idle" };
        if (action === "disable") return { ...a, enabled: false, health: "disabled" };
        if (action === "archive") return { ...a, archived: true, health: "archived" };
        return a;
      });
      return json(route, { agent: agents.find((a) => a.agentId === id) });
    }

    const launchMatch = path.match(/^\/api\/agents\/([^/]+)\/missions$/);
    if (launchMatch && method === "POST") {
      const agentId = decodeURIComponent(launchMatch[1]);
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const mission = {
        missionId: `mission_${missions.length + 1}`,
        agentId,
        title: body.title || "Nieuwe missie",
        request: body.request || "",
        status: body.dryRun ? "completed" : "queued",
        priority: body.priority || "normal",
        progress: body.dryRun ? 1 : 0,
        jobIds: body.dryRun ? [] : [`job_${missions.length + 1}`],
        createdAt: AGENTS_V2_VISUAL_FROZEN_ISO,
        startedAt: null,
        updatedAt: AGENTS_V2_VISUAL_FROZEN_ISO,
        finishedAt: body.dryRun ? AGENTS_V2_VISUAL_FROZEN_ISO : null,
      };
      missions = [mission, ...missions];
      return json(route, { mission });
    }

    const missionMatch = path.match(/^\/api\/agents\/missions\/([^/]+)$/);
    if (missionMatch && method === "GET") {
      const id = decodeURIComponent(missionMatch[1]);
      const mission = missions.find((m) => m.missionId === id) || missions[0];
      return json(route, { mission, children: [], events: f.events.events });
    }
    const cancelMatch = path.match(/^\/api\/agents\/missions\/([^/]+)\/cancel$/);
    if (cancelMatch && method === "POST") {
      const id = decodeURIComponent(cancelMatch[1]);
      missions = missions.map((m) =>
        m.missionId === id ? { ...m, status: "cancelling", cancelRequested: true } : m,
      );
      return json(route, { mission: missions.find((m) => m.missionId === id) });
    }

    if (path === "/api/agents/reconcile" && method === "POST") {
      return json(route, { count: 1, missions: [] });
    }
    if (path === "/api/agents/fleet/start-all" && method === "POST") {
      return json(route, { changed: ["agent_research"], skipped: ["agent_hades"] });
    }
    if (path === "/api/agents/fleet/pause-all" && method === "POST") {
      return json(route, { changed: ["agent_research"], skipped: ["agent_hades"] });
    }

    const scaleMatch = path.match(/^\/api\/workers\/pools\/([^/]+)\/scale$/);
    if (scaleMatch && method === "POST") {
      const poolId = decodeURIComponent(scaleMatch[1]);
      const body = route.request().postDataJSON() as { desiredCount?: number };
      return json(route, {
        override: { poolId, desiredCount: body.desiredCount ?? 1, updatedAt: AGENTS_V2_VISUAL_FROZEN_ISO },
      });
    }

    if (path.startsWith("/api/agents/signals")) {
      return json(route, { signals: [], metrics: {}, graph: { nodes: [], edges: [] }, deadLetters: [], deliveries: [], chain: [] });
    }

    if (path.startsWith("/api/trade") || path.startsWith("/api/trading")) {
      return json(route, { orchestras: [], decisions: [], truth: { visual_fixture: true } });
    }

    // Soft-fail unknown control-plane GETs so the page stays usable.
    if (method === "GET") {
      return json(route, { truth: { visual_fixture: true } });
    }
    return json(route, { ok: true, truth: { visual_fixture: true } });
  });
}
