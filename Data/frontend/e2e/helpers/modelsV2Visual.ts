/**
 * Playwright helper — installs Screen 1 Models (LM Studio control plane)
 * deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  MODELS_V2_VISUAL_FIXTURE,
  MODELS_V2_VISUAL_FROZEN_ISO,
  buildOptimizationRun,
} from "../../src/mocks/modelsV2VisualFixture";

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

export async function installModelsV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean }).__LV_V2_VISUAL_FIXTURE__ = true;
    },
    { frozen: MODELS_V2_VISUAL_FROZEN_ISO },
  );

  // Mutable state so PUT /hardware/policy + load/unload feel real across a test run.
  let hardware: Record<string, unknown> = JSON.parse(JSON.stringify(MODELS_V2_VISUAL_FIXTURE.hardware));
  let models = JSON.parse(JSON.stringify(MODELS_V2_VISUAL_FIXTURE.models)) as Array<Record<string, unknown>>;
  let latestOptimization: Record<string, unknown> | null = buildOptimizationRun("BEST");

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
    const f = MODELS_V2_VISUAL_FIXTURE;

    if (path === "/api/health") {
      return json(route, { ok: true, llm: { available: true }, database: "ok" });
    }

    if (path === "/api/models" && method === "GET") {
      return json(route, { models, status: f.status });
    }
    if (path === "/api/models/refresh" && method === "POST") {
      return json(route, { summary: { refreshed: true }, models, status: f.status });
    }
    if (path === "/api/models/hardware" && method === "GET") {
      return json(route, { hardware, reservations: [], residency: [] });
    }
    if (path === "/api/models/hardware/policy" && method === "PUT") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      hardware = {
        ...hardware,
        policy: {
          ...(hardware.policy as Record<string, unknown>),
          displayGpuReserveBytes: body.displayGpuReserveBytes,
          auxGpuReserveBytes: body.auxGpuReserveBytes,
          ramHeadroomBytes: body.ramHeadroomBytes,
        },
      };
      return json(route, { policy: hardware.policy, hardware });
    }
    if (path === "/api/models/gateway" && method === "GET") {
      return json(route, { gateway: f.gateway });
    }
    if (path === "/api/models/router" && method === "GET") {
      return json(route, { router: f.router });
    }
    if (path === "/api/models/router" && method === "PUT") {
      return json(route, { router: { ...f.router, ...(route.request().postDataJSON() as object) } });
    }
    if (path === "/api/model-providers" && method === "GET") {
      return json(route, { providers: [f.provider] });
    }
    const providerTestMatch = path.match(/^\/api\/model-providers\/([^/]+)\/test$/);
    if (providerTestMatch && method === "POST") {
      return json(route, {
        connected: true,
        providerId: decodeURIComponent(providerTestMatch[1]),
        provider: f.provider.name,
        modelsFound: models.length,
        latencyMs: 38,
        health: "healthy",
        error: null,
      });
    }
    const capsMatch = path.match(/^\/api\/models\/providers\/([^/]+)\/capabilities$/);
    if (capsMatch && method === "GET") {
      return json(route, f.capabilities);
    }

    const estimateMatch = path.match(/^\/api\/models\/([^/]+)\/estimate$/);
    if (estimateMatch && method === "POST") {
      const modelId = decodeURIComponent(estimateMatch[1]);
      return json(route, { ...f.estimate, modelId, timestamp: Date.now() });
    }

    const startOptMatch = path.match(/^\/api\/models\/([^/]+)\/optimization$/);
    if (startOptMatch && method === "POST") {
      const modelId = decodeURIComponent(startOptMatch[1]);
      latestOptimization = { ...buildOptimizationRun("RUNNING"), modelId, candidates: [] };
      return json(route, { queued: true, optimization: latestOptimization });
    }
    if (startOptMatch && method === "GET") {
      const modelId = decodeURIComponent(startOptMatch[1]);
      return json(route, { optimizations: latestOptimization ? [{ ...buildOptimizationRun("BEST"), modelId }] : [] });
    }

    const loadMatch = path.match(/^\/api\/models\/([^/]+)\/load$/);
    if (loadMatch && method === "POST") {
      const modelId = decodeURIComponent(loadMatch[1]);
      models = models.map((m) => (m.id === modelId ? { ...m, loaded: true, active: true } : m));
      return json(route, { loaded: true, modelId });
    }
    const unloadMatch = path.match(/^\/api\/models\/([^/]+)\/unload$/);
    if (unloadMatch && method === "POST") {
      const modelId = decodeURIComponent(unloadMatch[1]);
      models = models.map((m) => (m.id === modelId ? { ...m, loaded: false, active: false } : m));
      return json(route, { unloaded: true, modelId });
    }

    const optPollMatch = path.match(/^\/api\/models\/optimization\/([^/]+)$/);
    if (optPollMatch && method === "GET") {
      latestOptimization = buildOptimizationRun("BEST");
      return json(route, { optimization: latestOptimization });
    }
    const optCancelMatch = path.match(/^\/api\/models\/optimization\/([^/]+)\/cancel$/);
    if (optCancelMatch && method === "POST") {
      latestOptimization = buildOptimizationRun("CANCELLED");
      return json(route, { optimization: latestOptimization });
    }

    const residencyPolicyMatch = path.match(/^\/api\/models\/([^/]+)\/residency-policy$/);
    if (residencyPolicyMatch && method === "PUT") {
      return json(route, { policy: f.modelDetail.residencyPolicy });
    }

    const modelDetailMatch = path.match(/^\/api\/models\/([^/]+)$/);
    if (modelDetailMatch && method === "GET") {
      const modelId = decodeURIComponent(modelDetailMatch[1]);
      const found = models.find((m) => m.id === modelId);
      if (modelId === f.modelDetail.model.id) {
        return json(route, { ...f.modelDetail, model: found ?? f.modelDetail.model });
      }
      return json(route, {
        model: found ?? null,
        profile: null,
        capabilities: [],
        provider: { id: f.provider.id, name: f.provider.name },
        preflight: {},
        runtimeBinding: null,
        residency: null,
        residencyPolicy: null,
        resourceEstimate: null,
      });
    }

    if (path === "/api/model-providers" || path.startsWith("/api/model-providers/")) {
      return json(route, { providers: [f.provider] });
    }

    return json(route, { ok: true, truth: { visual_fixture_default: true } });
  });
}
