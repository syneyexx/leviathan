/**
 * Adversarial chat stream / contract tests (Wave 1).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import {
  displayMessageContent,
  normalizeMessage,
  parseChatDonePayload,
} from "./chatContract";

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

describe("chatContract runtime guards", () => {
  it("normalizeMessage handles null / missing / object content", () => {
    expect(normalizeMessage(null)).toBeNull();
    expect(normalizeMessage({ role: "assistant" })?.content).toBe("");
    expect(normalizeMessage({ role: "assistant", content: null })?.content).toBe("");
    expect(normalizeMessage({ role: "assistant", content: { text: "x" } })).toBeNull();
    expect(normalizeMessage({ role: "user", content: "hi", created_at: "t" })?.content).toBe(
      "hi",
    );
  });

  it("displayMessageContent never throws", () => {
    expect(displayMessageContent(undefined)).toBe("");
    expect(displayMessageContent(null)).toBe("");
    expect(displayMessageContent({ x: 1 })).toBe("");
    expect(displayMessageContent("ok")).toBe("ok");
  });

  it("parseChatDonePayload: done without assistant_message", () => {
    const parsed = parseChatDonePayload({ conversation_id: "c1" });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) expect(parsed.failure.reason).toBe("missing_assistant_message");
  });

  it("parseChatDonePayload: assistant_message=null", () => {
    const parsed = parseChatDonePayload({ conversation_id: "c1", assistant_message: null });
    expect(parsed.ok).toBe(false);
  });

  it("parseChatDonePayload: assistant_message={}", () => {
    // empty object → content defaults to "" → valid message shape
    const parsed = parseChatDonePayload({ conversation_id: "c1", assistant_message: {} });
    expect(parsed.ok).toBe(true);
    if (parsed.ok) expect(parsed.response.assistant_message.content).toBe("");
  });

  it("parseChatDonePayload: assistant_message without content", () => {
    const parsed = parseChatDonePayload({
      conversation_id: "c1",
      assistant_message: { role: "assistant", created_at: "t" },
    });
    expect(parsed.ok).toBe(true);
    if (parsed.ok) expect(parsed.response.assistant_message.content).toBe("");
  });

  it("parseChatDonePayload: TEAM legacy message field promotes", () => {
    const parsed = parseChatDonePayload({
      conversation_id: "c1",
      message: { id: 1, role: "assistant", content: "team ok", created_at: "t" },
      team: { status: "completed" },
    });
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.response.assistant_message.content).toBe("team ok");
      expect(parsed.response.team).toEqual({ status: "completed" });
    }
  });
});

describe("chatStream adversarial payloads", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("done without assistant_message returns protocol_failure without throwing crash", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: token\ndata: {"text":"partial","sequence":1}\n\n',
          'event: done\ndata: {"conversation_id":"c1"}\n\n',
        ]),
      ),
    );
    const result = await api.chatStream("x", {}, {});
    expect(result.protocol_failure).toBe("missing_assistant_message");
    expect(result.provisional).toBe(true);
    expect(result.assistant_message.content).toBe("");
  });

  it("assistant_message=null is protocol failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: done\ndata: {"conversation_id":"c1","assistant_message":null}\n\n',
        ]),
      ),
    );
    const result = await api.chatStream("x", {}, {});
    expect(result.protocol_failure).toBeTruthy();
  });

  it("malformed JSON SSE is ignored; valid done still wins", async () => {
    const tokens: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          "event: token\ndata: {not-json\n\n",
          'event: token\ndata: {"text":"ok","sequence":1}\n\n',
          'event: done\ndata: {"assistant_message":{"content":"ok","created_at":"t"},"conversation_id":"c1"}\n\n',
        ]),
      ),
    );
    const result = await api.chatStream("x", {}, { onToken: (t) => tokens.push(t) });
    expect(tokens).toEqual(["ok"]);
    expect(result.assistant_message.content).toBe("ok");
    expect(result.protocol_failure).toBeUndefined();
  });

  it("duplicate done is idempotent", async () => {
    let doneCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: done\ndata: {"assistant_message":{"content":"A","created_at":"t"},"conversation_id":"c1"}\n\n',
          'event: done\ndata: {"assistant_message":{"content":"B","created_at":"t"},"conversation_id":"c1"}\n\n',
        ]),
      ),
    );
    const result = await api.chatStream("x", {}, { onDone: () => { doneCount += 1; } });
    expect(doneCount).toBe(1);
    expect(result.assistant_message.content).toBe("A");
  });

  it("token after done is ignored", async () => {
    const tokens: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: done\ndata: {"assistant_message":{"content":"final","created_at":"t"},"conversation_id":"c1"}\n\n',
          'event: token\ndata: {"text":"late","sequence":99}\n\n',
        ]),
      ),
    );
    await api.chatStream("x", {}, { onToken: (t) => tokens.push(t) });
    expect(tokens).toEqual([]);
  });

  it("duplicate sequence ignored", async () => {
    const tokens: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: token\ndata: {"text":"A","sequence":1}\n\n',
          'event: token\ndata: {"text":"A","sequence":1}\n\n',
          'event: done\ndata: {"assistant_message":{"content":"A","created_at":"t"},"conversation_id":"c1"}\n\n',
        ]),
      ),
    );
    await api.chatStream("x", {}, { onToken: (t) => tokens.push(t) });
    expect(tokens).toEqual(["A"]);
  });

  it("error after partial tokens throws without inventing success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: token\ndata: {"text":"hi","sequence":1}\n\n',
          'event: error\ndata: {"detail":"upstream failed"}\n\n',
        ]),
      ),
    );
    await expect(api.chatStream("x", {}, {})).rejects.toThrow(/upstream failed/);
  });

  it("TEAM legacy JSON without assistant_message promotes message field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: async () => ({
          conversation_id: "c1",
          message: { id: 2, role: "assistant", content: "team reply", created_at: "t" },
          team: { status: "completed" },
          collaboration_strategy: "team",
        }),
      })),
    );
    const result = await api.chatStream("x", { collaborationStrategy: "team" }, {});
    expect(result.assistant_message.content).toBe("team reply");
    expect(result.team).toEqual({ status: "completed" });
    expect(result.protocol_failure).toBeUndefined();
  });
});
