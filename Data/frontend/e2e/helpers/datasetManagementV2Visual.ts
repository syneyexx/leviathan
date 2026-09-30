/**
 * Playwright helper — installs Screen 1 Dataset Management deterministic API
 * fixtures (TEST ONLY). Never used by production data paths.
 */
import type { Page, Route } from "@playwright/test";
import {
  DATASET_MGMT_V2_VISUAL_FIXTURE,
  DATASET_MGMT_V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/datasetManagementV2VisualFixture";

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

export async function installDatasetManagementV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      const frozenMs = Date.parse(frozen);
      try {
        window.localStorage.setItem(
          "lv.ui.preferences.v1",
          JSON.stringify({
            app_display_name: "Leviathan AI Control Center",
            timezone: "UTC",
            locale: "nl",
            theme: "dark_leviathan",
            auto_refresh_seconds: 30,
            sound_notifications: true,
            desktop_notifications: true,
            prefer_local_data: true,
            optional_diagnostics_share: false,
            crash_reports_enabled: true,
          }),
        );
      } catch {
        /* ignore */
      }
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean | string }).__LV_V2_VISUAL_FIXTURE__ =
        "dataset-management";
      if (!Number.isNaN(frozenMs)) {
        Date.now = () => frozenMs;
      }
    },
    { frozen: DATASET_MGMT_V2_VISUAL_FROZEN_ISO },
  );

  const f = DATASET_MGMT_V2_VISUAL_FIXTURE;
  let jobs = JSON.parse(JSON.stringify(f.jobs)) as Array<Record<string, unknown>>;
  const datasets = JSON.parse(JSON.stringify(f.datasets)) as Array<Record<string, unknown>>;

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
      const q = (url.searchParams.get("q") || "").toLowerCase();
      const source = url.searchParams.get("source") || "";
      const category = url.searchParams.get("category") || "";
      const split = url.searchParams.get("split") || "";
      const offset = Number(url.searchParams.get("offset") || "0");
      const limit = Number(url.searchParams.get("limit") || "100");

      let rows = datasets.slice();
      if (q) {
        rows = rows.filter((d) => {
          const hay = `${d.name} ${d.displayName} ${(d.semanticTags as string[] | undefined)?.join(" ") || ""}`.toLowerCase();
          return hay.includes(q);
        });
      }
      if (source && source !== "Alle bronnen") {
        rows = rows.filter((d) => String(d.sourceType || "").toLowerCase().includes(source.toLowerCase().slice(0, 4)));
      }
      if (category && category !== "Alle categorieën") {
        rows = rows.filter((d) => String(d.primaryCategory || "") === category);
      }
      // split filter is version-backed; fixture ignores shape and keeps page rows
      void split;

      const pageRows = rows.slice(offset, offset + limit);
      const total = f.total;
      const nextOffset = offset + pageRows.length < rows.length ? offset + pageRows.length : null;
      return json(route, {
        datasets: pageRows,
        total,
        limit,
        offset,
        sort: url.searchParams.get("sort") || "created_at_desc",
        hasMore: nextOffset != null,
        nextOffset,
        truth: { fixtureOnly: true, pageSizeDoesNotDefineTotals: true },
      });
    }

    if (path === "/api/datasets/jobs" && method === "GET") {
      return json(route, { jobs });
    }

    const cancelMatch = path.match(/^\/api\/datasets\/jobs\/([^/]+)\/cancel$/);
    if (cancelMatch && method === "POST") {
      const jobId = decodeURIComponent(cancelMatch[1]);
      jobs = jobs.map((j) =>
        j.jobId === jobId ? { ...j, status: "cancelling", cancelRequested: true } : j,
      );
      return json(route, { job: jobs.find((j) => j.jobId === jobId) || jobs[0] });
    }

    const jobMatch = path.match(/^\/api\/datasets\/jobs\/([^/]+)$/);
    if (jobMatch && method === "GET") {
      const jobId = decodeURIComponent(jobMatch[1]);
      const job = jobs.find((j) => j.jobId === jobId) || jobs[0];
      return json(route, { job });
    }

    const previewMatch = path.match(/^\/api\/datasets\/versions\/([^/]+)\/preview$/);
    if (previewMatch && method === "GET") {
      return json(route, { rows: f.preview, preview: f.preview });
    }

    const versionsMatch = path.match(/^\/api\/datasets\/([^/]+)\/versions$/);
    if (versionsMatch && method === "GET") {
      const dsId = decodeURIComponent(versionsMatch[1]);
      return json(route, { versions: f.versions[dsId] || [] });
    }

    const recoveryMatch = path.match(/^\/api\/datasets\/([^/]+)\/recovery$/);
    if (recoveryMatch && method === "GET") {
      const dsId = decodeURIComponent(recoveryMatch[1]);
      return json(route, {
        recovery: { ...f.recovery, datasetId: dsId },
      });
    }

    const datasetMatch = path.match(/^\/api\/datasets\/([^/]+)$/);
    if (datasetMatch && method === "GET") {
      const dsId = decodeURIComponent(datasetMatch[1]);
      const dataset = datasets.find((d) => d.datasetId === dsId) || datasets[0];
      const versions = f.versions[String(dataset.datasetId)] || [];
      return json(route, {
        dataset,
        versions,
        files: [],
        indexes: [],
        learningState: dataset.learningState,
        brain: dataset.brain,
        brainStatus: dataset.brainStatus,
        learned: dataset.learned,
        canonicalState: dataset.canonicalState,
      });
    }

    if (datasetMatch && method === "DELETE") {
      return json(route, { ok: true, deleted: true });
    }

    // Soft-default unused APIs so the page doesn't hang on refresh/sidebar probes.
    if (method === "GET") return json(route, {});
    return json(route, { ok: true });
  });
}
