/**
 * Playwright helper — installs Screen 1 Chat deterministic API fixtures (TEST ONLY).
 */
import type { Page, Route } from "@playwright/test";
import {
  CHAT_V2_ACTIVE_CONVERSATION_ID,
  CHAT_V2_VISUAL_FIXTURE,
  CHAT_V2_VISUAL_FROZEN_ISO,
} from "../../src/mocks/chatV2VisualFixture";

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

export async function installChatV2VisualFixture(page: Page): Promise<void> {
  const f = CHAT_V2_VISUAL_FIXTURE;

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

    if (path === "/api/health") return json(route, f.health);
    if (path === "/api/system/telemetry") return json(route, f.telemetry);
    if (path === "/api/models" || path === "/api/models/") return json(route, f.models);
    if (path === "/api/capabilities") return json(route, f.capabilities);
    if (path === "/api/coding/status") return json(route, f.codingStatus);
    if (path === "/api/memory" || path.startsWith("/api/memory/")) return json(route, f.memory);

    if (path === "/api/conversations") {
      return json(route, f.conversations);
    }
    if (path.startsWith("/api/conversations/")) {
      const id = path.split("/").pop();
      if (id === CHAT_V2_ACTIVE_CONVERSATION_ID) {
        return json(route, f.conversationDetail);
      }
      const listed = f.conversations.conversations.find((c) => c.id === id);
      if (listed) {
        return json(route, { conversation: listed, messages: [] });
      }
      return json(route, { detail: "not found" }, 404);
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
