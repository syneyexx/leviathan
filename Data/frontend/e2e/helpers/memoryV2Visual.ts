/**
 * Playwright helper — installs Screen 1 Memory deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  MEMORY_V2_VISUAL_FIXTURE,
  MEMORY_V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/memoryV2VisualFixture";

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

export async function installMemoryV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      const frozenMs = Date.parse(frozen);
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean }).__LV_V2_VISUAL_FIXTURE__ = true;
      if (!Number.isNaN(frozenMs)) {
        Date.now = () => frozenMs;
      }
    },
    { frozen: MEMORY_V2_VISUAL_FROZEN_ISO },
  );

  const f = MEMORY_V2_VISUAL_FIXTURE;
  let memories = JSON.parse(JSON.stringify(f.memory)) as Array<Record<string, unknown>>;

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
    if (path === "/api/memory/overview") return json(route, { overview: f.overview });
    if (path === "/api/memory/analytics") return json(route, { analytics: f.analytics });
    if (path === "/api/memory/activity") return json(route, { activity: f.activity });
    if (path === "/api/memory/semantic-index") {
      return json(route, { semantic_index: f.semantic_index });
    }
    if (path === "/api/memory/semantic-index/optimize" && method === "POST") {
      return json(route, { queued: true, job_id: "job-opt-1" }, 202);
    }
    if (path === "/api/memory/processing") {
      if (method === "PATCH") {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        Object.assign(f.processing, body);
        return json(route, { processing: f.processing });
      }
      return json(route, { processing: f.processing });
    }
    if (path === "/api/conversations") {
      return json(route, { conversations: f.conversations });
    }
    if (path === "/api/memory/search") {
      const q = url.searchParams.get("q") || "";
      const hits = memories.filter((m) =>
        String(m.content || "")
          .toLowerCase()
          .includes(q.toLowerCase()),
      );
      return json(route, {
        memory: hits,
        mode: "hybrid",
        requested_mode: url.searchParams.get("mode") || "hybrid",
        degraded: false,
        truth: { scope_filter_required_for_retrieval: true },
      });
    }
    if (path === "/api/memory" && method === "GET") {
      return json(route, {
        memory: memories,
        next_cursor: null,
        limit: 40,
        sort: "newest",
        pagination: { cursor: true },
      });
    }
    if (path === "/api/memory" && method === "POST") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const created = {
        memory_id: `mem-new-${memories.length}`,
        kind: body.kind || "NOTE",
        status: "ACTIVE",
        content: body.content,
        created_at: MEMORY_V2_VISUAL_FROZEN_ISO,
        updated_at: MEMORY_V2_VISUAL_FROZEN_ISO,
        source: body.source || "manual",
        source_normalized: "manual",
        trust: body.trust || "explicit",
        tags: body.tags || [],
        pinned: Array.isArray(body.tags) && body.tags.includes("pinned"),
        priority: 0.4,
        scope: body.scope || "GLOBAL",
        actor: null,
      };
      memories = [created, ...memories];
      return json(route, { memory: created });
    }
    if (path.startsWith("/api/memory/") && method === "GET") {
      const id = decodeURIComponent(path.slice("/api/memory/".length));
      const found = memories.find((m) => m.memory_id === id) || memories[0];
      return json(route, { memory: found });
    }
    if (path.endsWith("/pin") && method === "POST") {
      const id = decodeURIComponent(path.split("/").slice(-2)[0]);
      memories = memories.map((m) =>
        m.memory_id === id
          ? { ...m, pinned: true, tags: Array.from(new Set([...(m.tags as string[]), "pinned"])) }
          : m,
      );
      return json(route, { memory: memories.find((m) => m.memory_id === id) });
    }
    if (path.endsWith("/unpin") && method === "POST") {
      const id = decodeURIComponent(path.split("/").slice(-2)[0]);
      memories = memories.map((m) =>
        m.memory_id === id
          ? {
              ...m,
              pinned: false,
              tags: ((m.tags as string[]) || []).filter((t) => t.toLowerCase() !== "pinned"),
            }
          : m,
      );
      return json(route, { memory: memories.find((m) => m.memory_id === id) });
    }
    if (path.endsWith("/archive") && method === "POST") {
      return json(route, {
        memory: { ...memories[0], status: "ARCHIVED" },
      });
    }
    if (path.endsWith("/revoke") && method === "POST") {
      return json(route, {
        memory: { ...memories[0], status: "REVOKED" },
      });
    }
    if (path.endsWith("/correct") && method === "POST") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const created = {
        ...memories[0],
        memory_id: `mem-corr-${Date.now()}`,
        kind: "CORRECTION",
        content: body.content,
        supersedes_id: memories[0].memory_id,
      };
      memories = [created, ...memories];
      return json(route, { memory: created });
    }
    if (path === "/api/memory/from-conversation" && method === "POST") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const created = {
        memory_id: `mem-conv-${memories.length}`,
        kind: body.kind || "EPISODIC",
        status: "ACTIVE",
        content: body.content,
        created_at: MEMORY_V2_VISUAL_FROZEN_ISO,
        updated_at: MEMORY_V2_VISUAL_FROZEN_ISO,
        source: "conversation",
        source_normalized: "conversation",
        trust: body.from_assistant ? "derived" : "explicit",
        tags: ["from_conversation"],
        scope: "CONVERSATION",
        conversation_id: body.conversation_id,
        actor: "Conversation",
      };
      memories = [created, ...memories];
      return json(route, { memory: created });
    }

    // Soft-default unused APIs so the page doesn't hang.
    if (method === "GET") return json(route, {});
    return json(route, { ok: true });
  });
}
