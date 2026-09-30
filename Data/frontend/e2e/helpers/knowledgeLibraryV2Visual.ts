/**
 * Playwright helper — installs Knowledge Library V2 deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  KNOWLEDGE_LIBRARY_V2_VISUAL_FIXTURE,
  KNOWLEDGE_LIBRARY_V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/knowledgeLibraryV2VisualFixture";

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

export async function installKnowledgeLibraryV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      const frozenMs = Date.parse(frozen);
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean | string }).__LV_V2_VISUAL_FIXTURE__ =
        "knowledge";
      if (!Number.isNaN(frozenMs)) {
        Date.now = () => frozenMs;
      }
    },
    { frozen: KNOWLEDGE_LIBRARY_V2_VISUAL_FROZEN_ISO },
  );

  const f = KNOWLEDGE_LIBRARY_V2_VISUAL_FIXTURE;
  const selected = f.library.items[0];

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
    if (path === "/api/knowledge/library/overview" && method === "GET") {
      return json(route, { overview: f.overview });
    }
    if (path === "/api/knowledge/library" && method === "GET") {
      return json(route, f.library);
    }
    if (path === "/api/knowledge/library/ingestion/recent" && method === "GET") {
      return json(route, f.recentIngestions);
    }
    if (/^\/api\/knowledge\/library\/ingestion\/[^/]+$/.test(path) && method === "GET") {
      return json(route, { source_id: "ing-active", progress: f.activeProgress });
    }
    if (/^\/api\/knowledge\/library\/[^/]+$/.test(path) && method === "GET") {
      return json(route, { document: selected });
    }
    if (path.endsWith("/preview") && method === "GET") {
      return json(route, {
        preview: {
          preview_kind: "text",
          text: "Options Trading Strategies Handbook\n\nFixture preview page.",
          truncated: false,
          mime_type: "application/pdf",
          content_url: "/api/knowledge/library/opts-handbook/content",
          download_url: "/api/knowledge/library/opts-handbook/download",
        },
        document: selected,
      });
    }
    if (path.endsWith("/embeddings") && method === "GET") {
      return json(route, {
        embeddings: {
          document_id: selected.id,
          document_status: "READY",
          indexed: true,
          chunks_total: 342,
          chunks_embedded: 342,
          chunks_missing: 0,
          coverage_percent: 100,
          embedding_status: "OK",
          provider_id: "fixture",
          dimensions: 768,
          provider_configured: true,
          provider_available: true,
        },
      });
    }
    if (path.endsWith("/content-chunks") && method === "GET") {
      return json(route, {
        document_id: selected.id,
        chunks: [
          {
            chunk_id: "c1",
            chunk_index: 0,
            content: "Chapter 1 — Introduction to options.",
            token_estimate: 40,
          },
        ],
        total: 342,
        offset: 0,
        limit: 20,
        has_more: true,
        next_offset: 20,
      });
    }
    if (path.endsWith("/relations") && method === "GET") {
      return json(route, { document_id: selected.id, relations: [], total: 0 });
    }
    if (path.endsWith("/related") && method === "GET") {
      return json(route, { document_id: selected.id, related: f.related, total: f.related.length });
    }
    if (path === "/api/knowledge/health") {
      return json(route, { health: { documents_total: 124532, embedding_coverage_percent: 100 } });
    }
    if (path === "/api/knowledge" && method === "GET") {
      return json(route, { documents: [] });
    }

    return json(route, { ok: true });
  });
}
