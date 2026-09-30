/**
 * Playwright helper — installs Screen 1 Training deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  TRAINING_V2_VISUAL_FIXTURE,
  TRAINING_V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/trainingV2VisualFixture";

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

export async function installTrainingV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean }).__LV_V2_VISUAL_FIXTURE__ = true;
    },
    { frozen: TRAINING_V2_VISUAL_FROZEN_ISO },
  );

  let jobs = JSON.parse(JSON.stringify(TRAINING_V2_VISUAL_FIXTURE.jobs)) as Array<Record<string, unknown>>;

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
    const f = TRAINING_V2_VISUAL_FIXTURE;

    if (path === "/api/health") return json(route, f.health);
    if (path === "/api/system/telemetry" || path === "/api/telemetry/system") {
      return json(route, f.telemetry);
    }

    if (path === "/api/training/capabilities") {
      return json(route, { capabilities: f.capabilities });
    }
    if (path === "/api/training/hardware") {
      return json(route, { hardware: f.hardware });
    }
    if (path === "/api/training/preflight" && method === "POST") {
      return json(route, { preflight: f.preflight });
    }
    if (path === "/api/training/plan" && method === "POST") {
      return json(route, { plan: f.plan });
    }
    if (path === "/api/training/jobs" && method === "GET") {
      return json(route, { jobs });
    }
    if (path === "/api/training/jobs" && method === "POST") {
      const body = (route.request().postDataJSON() as Record<string, unknown>) || {};
      const created = {
        ...f.jobs[0],
        jobId: `job-new-${jobs.length + 1}`,
        name: body.name || "training-run",
        method: body.method || "lora",
        baseModelRef: body.base_model_ref || "unspecified",
        datasetVersionId: body.dataset_version_id || null,
        status: body.auto_start ? "running" : "queued",
        progress: body.auto_start ? 0.01 : 0,
        config: body,
        createdAt: TRAINING_V2_VISUAL_FROZEN_ISO,
        updatedAt: TRAINING_V2_VISUAL_FROZEN_ISO,
        startedAt: body.auto_start ? TRAINING_V2_VISUAL_FROZEN_ISO : null,
        finishedAt: null,
      };
      jobs = [created, ...jobs];
      return json(route, { job: created });
    }

    const jobMatch = path.match(/^\/api\/training\/jobs\/([^/]+)(?:\/(start|cancel|resume|checkpoints|metrics|logs|evaluate|export))?$/);
    if (jobMatch) {
      const jobId = decodeURIComponent(jobMatch[1]);
      const action = jobMatch[2];
      const job = jobs.find((j) => j.jobId === jobId) || f.jobs[0];

      if (!action && method === "GET") return json(route, { job });
      if (action === "start" && method === "POST") {
        const updated = { ...job, status: "running", startedAt: TRAINING_V2_VISUAL_FROZEN_ISO };
        jobs = jobs.map((j) => (j.jobId === jobId ? updated : j));
        return json(route, { job: updated });
      }
      if (action === "cancel" && method === "POST") {
        const updated = { ...job, status: "cancelling", cancelRequested: true };
        jobs = jobs.map((j) => (j.jobId === jobId ? updated : j));
        return json(route, { job: updated });
      }
      if (action === "resume" && method === "POST") {
        const updated = { ...job, status: "running" };
        jobs = jobs.map((j) => (j.jobId === jobId ? updated : j));
        return json(route, { job: updated });
      }
      if (action === "checkpoints" && method === "GET") {
        return json(route, f.checkpoints);
      }
      if (action === "metrics" && method === "GET") {
        return json(route, { metrics: f.metrics.map((m) => ({ ...m, jobId })) });
      }
      if (action === "logs" && method === "GET") {
        return json(route, { ...f.logs, jobId });
      }
      if ((action === "evaluate" || action === "export") && method === "POST") {
        return json(route, { [action]: { ok: true } });
      }
    }

    if (path === "/api/training/reconcile" && method === "POST") {
      return json(route, { reconciled: 0 });
    }

    if (path === "/api/datasets" && method === "GET") return json(route, f.datasets);
    const versionsMatch = path.match(/^\/api\/datasets\/([^/]+)\/versions$/);
    if (versionsMatch && method === "GET") {
      const dsId = decodeURIComponent(versionsMatch[1]);
      return json(route, f.versions[dsId] || { versions: [] });
    }

    if (path === "/api/models" && method === "GET") return json(route, f.models);
    if (path === "/api/models/refresh" && method === "POST") return json(route, f.models);

    // Unmatched control-plane calls get an empty-ish success to avoid page errors.
    if (method === "GET") return json(route, {});
    return json(route, { ok: true });
  });
}
