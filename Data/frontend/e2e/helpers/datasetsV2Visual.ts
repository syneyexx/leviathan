/**
 * Playwright helper — installs Screen 1 Datasets deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  DATASETS_V2_VISUAL_FIXTURE,
  DATASETS_V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/datasetsV2VisualFixture";

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

export async function installDatasetsV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      const frozenMs = Date.parse(frozen);
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean | string }).__LV_V2_VISUAL_FIXTURE__ =
        "datasets";
      if (!Number.isNaN(frozenMs)) {
        Date.now = () => frozenMs;
      }
    },
    { frozen: DATASETS_V2_VISUAL_FROZEN_ISO },
  );

  const f = DATASETS_V2_VISUAL_FIXTURE;
  const datasets = JSON.parse(JSON.stringify(f.datasets)) as Array<Record<string, unknown>>;
  const jobs = JSON.parse(JSON.stringify(f.jobs)) as Array<Record<string, unknown>>;

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

    if (path === "/api/health") return json(route, f.health);
    if (path === "/api/datasets/overview" && method === "GET") {
      return json(route, { overview: f.overview });
    }
    if (path === "/api/datasets" && method === "GET") {
      return json(route, {
        datasets,
        total: 2134,
        limit: 50,
        offset: 0,
        hasMore: true,
        nextOffset: 50,
      });
    }
    if (path === "/api/datasets/jobs" && method === "GET") {
      return json(route, { jobs });
    }
    if (path.includes("/preview") && method === "GET") {
      return json(route, { rows: f.previewRows, limit: 20 });
    }
    if (/^\/api\/datasets\/versions\/[^/]+$/.test(path) && method === "GET") {
      const versionId = decodeURIComponent(path.split("/").pop() || "");
      const version = f.versions.find((v) => v.versionId === versionId) ?? f.versions[0];
      return json(route, { version });
    }
    if (path.endsWith("/cancel") && method === "POST") {
      const parts = path.split("/");
      const jobId = parts[parts.indexOf("jobs") + 1];
      const job = jobs.find((j) => j.jobId === jobId);
      if (job) job.status = "cancelled";
      return json(route, { job });
    }
    if (path.startsWith("/api/datasets/") && method === "GET") {
      const id = decodeURIComponent(path.replace("/api/datasets/", "").split("/")[0] || "");
      if (["overview", "jobs", "bulk", "upload", "import", "huggingface"].includes(id)) {
        return json(route, { ok: true });
      }
      const dataset = datasets.find((d) => d.datasetId === id) ?? datasets[0];
      const versions = f.versions.filter((v) => v.datasetId === dataset?.datasetId);
      return json(route, {
        dataset,
        versions,
        files: [],
        indexes: [],
      });
    }
    return json(route, { ok: true });
  });
}
