/**
 * Playwright helper — Screen 1 Dataset Management visual fixture (TEST ONLY).
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
      const frozenMs = Date.parse(frozen);
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: string; __LV_V2_FROZEN_NOW__?: string }).__LV_V2_VISUAL_FIXTURE__ =
        "dataset-management";
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      if (!Number.isNaN(frozenMs)) {
        Date.now = () => frozenMs;
      }
    },
    { frozen: DATASET_MGMT_V2_VISUAL_FROZEN_ISO },
  );

  const f = DATASET_MGMT_V2_VISUAL_FIXTURE;

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
    if (path === "/api/datasets/overview") return json(route, { overview: f.overview });
    if (path === "/api/datasets" && method === "GET") {
      return json(route, {
        datasets: f.datasets,
        total: f.overview.totalDatasets,
        limit: 50,
        offset: 0,
        hasMore: false,
        sort: "newest",
      });
    }
    if (path === "/api/datasets/jobs") {
      return json(route, { jobs: f.jobs });
    }
    if (path === "/api/datasets/catalog") {
      return json(route, { valid: true, catalog: { entryCount: 248, generatedAt: f.overview.catalogStatus.lastReconcileAt } });
    }
    if (path === "/api/datasets/learning/activity") {
      return json(route, { activity: [] });
    }

    const dsMatch = path.match(/^\/api\/datasets\/([^/]+)(?:\/(recovery|versions|semantic(?:\/analyze)?))?$/);
    if (dsMatch && method === "GET") {
      const id = decodeURIComponent(dsMatch[1]);
      if (id === "overview" || id === "jobs" || id === "catalog") return route.continue();
      if (dsMatch[2] === "recovery") {
        return json(route, { recovery: f.recovery[id] ?? f.recovery.nl_wiki_2024 });
      }
      const dataset = f.datasets.find((d) => d.datasetId === id) ?? f.detail;
      const versions = f.versions[id] ?? f.versions.nl_wiki_2024 ?? [];
      return json(route, { dataset, versions, files: [], indexes: [] });
    }

    const previewMatch = path.match(/^\/api\/datasets\/versions\/([^/]+)\/preview$/);
    if (previewMatch) {
      const vid = decodeURIComponent(previewMatch[1]);
      return json(route, {
        rows: f.preview[vid] ?? f.previewDefault,
        versionId: vid,
      });
    }

    // Allow other GETs to fall through empty-ish to avoid hard errors
    if (method === "GET" && path.startsWith("/api/")) {
      return json(route, {});
    }
    return route.continue();
  });
}

export function assertDatasetManagementFrozenClockContract() {
  return DATASET_MGMT_V2_VISUAL_FROZEN_ISO.startsWith("2025-05-25T14:38");
}
