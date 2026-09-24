/**
 * Chat stream client contract: cumulative snapshots, duplicate seq, done-once.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";

function sseResponse(blocks: string[], contentType = "text/event-stream") {
  const body = blocks.join("");
  const encoder = new TextEncoder();
  let sent = false;
  return {
    ok: true,
    status: 200,
    headers: { get: (k: string) => (k.toLowerCase() === "content-type" ? contentType : null) },
    body: {
      getReader() {
        return {
          async read() {
            if (sent) return { done: true, value: undefined };
            sent = true;
            return { done: false, value: encoder.encode(body) };
          },
        };
      },
    },
  };
}

describe("chatStream normalization", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("appends delta tokens and ignores duplicate sequences", async () => {
    const tokens: string[] = [];
    const snaps: string[] = [];
    let doneCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: token\ndata: {"text":"AP","sequence":1,"kind":"delta"}\n\n',
          'event: token\ndata: {"text":"AP","sequence":1,"kind":"delta"}\n\n',
          'event: token\ndata: {"text":"PEL","sequence":2,"kind":"delta"}\n\n',
          'event: done\ndata: {"assistant_message":{"content":"APPEL","created_at":"t"},"conversation_id":"c1","model":"m"}\n\n',
          'event: done\ndata: {"assistant_message":{"content":"APPEL","created_at":"t"},"conversation_id":"c1","model":"m"}\n\n',
        ]),
      ),
    );
    const result = await api.chatStream(
      "x",
      {},
      {
        onToken: (t) => tokens.push(t),
        onSnapshot: (t) => snaps.push(t),
        onDone: () => {
          doneCount += 1;
        },
      },
    );
    expect(tokens.join("")).toBe("APPEL");
    expect(doneCount).toBe(1);
    expect(result.assistant_message.content).toBe("APPEL");
  });

  it("replaces on snapshot events instead of appending", async () => {
    const tokens: string[] = [];
    const snaps: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: snapshot\ndata: {"text":"A","sequence":1,"kind":"snapshot"}\n\n',
          'event: token\ndata: {"text":"P","sequence":2,"kind":"delta"}\n\n',
          'event: token\ndata: {"text":"PEL","sequence":3,"kind":"delta"}\n\n',
          'event: done\ndata: {"assistant_message":{"content":"APPEL","created_at":"t"},"conversation_id":"c1"}\n\n',
        ]),
      ),
    );
    await api.chatStream(
      "x",
      {},
      {
        onToken: (t) => tokens.push(t),
        onSnapshot: (t) => snaps.push(t),
      },
    );
    expect(snaps).toEqual(["A"]);
    expect(tokens.join("")).toBe("PPEL");
  });

  it("parses CRLF-framed SSE", async () => {
    const tokens: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: token\r\ndata: {"text":"OK","sequence":1}\r\n\r\n',
          'event: done\r\ndata: {"assistant_message":{"content":"OK","created_at":"t"},"conversation_id":"c1"}\r\n\r\n',
        ]),
      ),
    );
    await api.chatStream("x", {}, { onToken: (t) => tokens.push(t) });
    expect(tokens).toEqual(["OK"]);
  });
});

describe("behavior settings client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("patchBehaviorProfile round-trips values", async () => {
    const capture: { url?: string; init?: RequestInit } = {};
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
        capture.url = String(url);
        capture.init = init;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            profile: { assistant_display_name: "ORCA", hash: "abc" },
            effective: { assistant_display_name: "ORCA", system_prompt: "You are ORCA.", hash: "abc" },
          }),
        };
      }),
    );
    const res = await api.patchBehaviorProfile({ assistant_display_name: "ORCA" });
    expect(capture.url).toBe("/api/settings/behavior-profile");
    expect(capture.init?.method).toBe("PATCH");
    expect(res.effective.assistant_display_name).toBe("ORCA");
  });
});
