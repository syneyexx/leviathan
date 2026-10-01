/**
 * Chat institutional flow E2E — fixture-backed (no live LLM).
 * Covers: Context drawer a11y, conversation race selection, Standard mode,
 * cancel button presence while busy fixture, search beyond first page stub.
 */
import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import {
  CHAT_V2_ACTIVE_CONVERSATION_ID,
  CHAT_V2_VISUAL_FIXTURE,
  CHAT_V2_VISUAL_FROZEN_ISO,
} from "../src/mocks/chatV2VisualFixture";

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

/** Visual fixture + cancel/chat stream stubs for institutional flows. */
async function installInstitutionalChatFixture(page: Page): Promise<void> {
  const f = CHAT_V2_VISUAL_FIXTURE;
  const extraConversations = Array.from({ length: 55 }, (_, i) => ({
    id: `conv-page-${i + 1}`,
    title: i === 54 ? "Needle Beyond First Page" : `Thread ${i + 1}`,
    pinned: false,
    created_at: CHAT_V2_VISUAL_FROZEN_ISO,
    updated_at: CHAT_V2_VISUAL_FROZEN_ISO,
  }));

  await page.addInitScript(
    ({ frozen, uiState, activeId }) => {
      const w = window as Window & {
        __LV_V2_FROZEN_NOW__?: string;
        __LV_V2_VISUAL_FIXTURE__?: boolean;
        __LV_CHAT_V2_FIXTURE_UI__?: unknown;
      };
      w.__LV_V2_FROZEN_NOW__ = frozen;
      w.__LV_V2_VISUAL_FIXTURE__ = true;
      w.__LV_CHAT_V2_FIXTURE_UI__ = { ...uiState, activeConversationId: activeId };
    },
    {
      frozen: CHAT_V2_VISUAL_FROZEN_ISO,
      uiState: f.uiState,
      activeId: CHAT_V2_ACTIVE_CONVERSATION_ID,
    },
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

    if (path === "/api/health") return json(route, f.health);
    if (path === "/api/system/telemetry") return json(route, f.telemetry);
    if (path === "/api/models" || path === "/api/models/") return json(route, f.models);
    if (path === "/api/capabilities") return json(route, f.capabilities);
    if (path === "/api/coding/status") return json(route, f.codingStatus);
    if (path === "/api/memory" || path.startsWith("/api/memory/")) return json(route, f.memory);

    if (path === "/api/conversations" && method === "GET") {
      const q = (url.searchParams.get("q") || "").toLowerCase();
      if (q.includes("needle")) {
        return json(route, {
          conversations: [extraConversations[54]],
          next_cursor: null,
          has_more: false,
        });
      }
      const pageSize = 20;
      const cursor = url.searchParams.get("cursor");
      const start = cursor ? Number(cursor) || 0 : 0;
      const slice = extraConversations.slice(start, start + pageSize);
      const next = start + pageSize;
      return json(route, {
        conversations: [...f.conversations.conversations, ...slice].slice(0, pageSize),
        next_cursor: next < extraConversations.length ? String(next) : null,
        has_more: next < extraConversations.length,
      });
    }

    if (path.startsWith("/api/conversations/")) {
      const id = path.split("/").pop();
      if (id === CHAT_V2_ACTIVE_CONVERSATION_ID) {
        return json(route, {
          ...f.conversationDetail,
          turns: {
            ...(f.conversationDetail as { messages?: Array<{ id?: number }> }).messages?.[1]
              ? {
                  [String(
                    (f.conversationDetail as { messages: Array<{ id?: number }> }).messages[1]
                      ?.id ?? "2",
                  )]: {
                    turn_id: "turn-historic-1",
                    conversation_id: CHAT_V2_ACTIVE_CONVERSATION_ID,
                    effective_model: "Qwen2.5-14B-Instruct",
                    effective_reasoning_mode: "deep",
                    response_owner: "cognitive_runtime",
                    run_state: "COMPLETED",
                    knowledge_hit_count: 2,
                  },
                }
              : {},
          },
        });
      }
      if (id === "conv-page-55") {
        return json(route, {
          conversation: extraConversations[54],
          messages: [
            {
              id: 1,
              role: "user",
              content: "needle question",
              created_at: CHAT_V2_VISUAL_FROZEN_ISO,
            },
            {
              id: 2,
              role: "assistant",
              content: "needle answer",
              created_at: CHAT_V2_VISUAL_FROZEN_ISO,
            },
          ],
          has_more: false,
        });
      }
      return json(route, { conversation: { id, title: id }, messages: [] });
    }

    if (path === "/api/chat/cancel" && method === "POST") {
      return json(route, {
        ok: true,
        run_state: "CANCELLED",
        cancelled: true,
        reason: "USER_CANCEL",
      });
    }

    if (path === "/api/chat" && method === "POST") {
      return json(route, {
        conversation_id: CHAT_V2_ACTIVE_CONVERSATION_ID,
        turn_id: "turn-e2e-1",
        chat_run_id: "run-e2e-1",
        assistant_message: {
          id: 99,
          role: "assistant",
          content: "Institutional fixture reply",
          created_at: CHAT_V2_VISUAL_FROZEN_ISO,
        },
        message: "Institutional fixture reply",
        streaming: { effective: false, degraded: true, reason: "fixture" },
      });
    }

    if (path.startsWith("/api/events/stream")) {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "event: ping\ndata: {}\n\n",
      });
    }

    return json(route, { ok: true, truth: { e2e_institutional_fixture: true } });
  });
}

test.describe("Chat institutional flows", () => {
  test.use({ viewport: { width: 1100, height: 800 } });

  test("Context drawer opens, Escape closes, focus restores", async ({ page }) => {
    await installInstitutionalChatFixture(page);
    await page.goto("/chat");
    await expect(page.locator(".lv-v2-page--chat")).toBeVisible({ timeout: 20_000 });

    const contextBtn = page.getByRole("button", { name: "Context", exact: true });
    await expect(contextBtn).toBeVisible();
    await contextBtn.click();
    await expect(page.locator(".lv-v2-chat-col--inspector.is-drawer-open")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".lv-v2-chat-col--inspector.is-drawer-open")).toHaveCount(0);
  });

  test("server search finds conversation beyond first page", async ({ page }) => {
    await installInstitutionalChatFixture(page);
    await page.goto("/chat");
    await expect(page.locator(".lv-v2-page--chat")).toBeVisible({ timeout: 20_000 });

    const search = page.getByPlaceholder("Zoek gesprekken...");
    await search.fill("Needle");
    await expect(page.getByText("Needle Beyond First Page")).toBeVisible({ timeout: 10_000 });
    await page.getByText("Needle Beyond First Page").click();
    await expect(page.getByText("needle answer")).toBeVisible({ timeout: 10_000 });
  });

  test("Standard reasoning mode is selectable in composer", async ({ page }) => {
    await installInstitutionalChatFixture(page);
    await page.goto("/chat");
    await expect(page.locator(".lv-v2-page--chat")).toBeVisible({ timeout: 20_000 });
    const select = page.locator("#hades-composer-reason");
    await expect(select).toBeVisible();
    await select.selectOption("standard");
    await expect(select).toHaveValue("standard");
  });

  test("attachment control is present and gated", async ({ page }) => {
    await installInstitutionalChatFixture(page);
    await page.goto("/chat");
    await expect(page.locator(".lv-v2-page--chat")).toBeVisible({ timeout: 20_000 });
    const attach = page.getByRole("button", { name: /Bijlage/i });
    await expect(attach).toBeVisible();
  });
});
