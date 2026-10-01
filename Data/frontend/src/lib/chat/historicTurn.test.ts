/**
 * MessageList historic turn hydration + load-older contract.
 */
import { describe, expect, it } from "vitest";
import type { ChatTurn } from "../../types/api";
import type { ChatDisplayMessage } from "../../pages/chat/MessageList";

function resolveTurn(
  message: ChatDisplayMessage,
  turnsByMessageId: Record<string, ChatTurn>,
): ChatTurn | null {
  return (
    message.turn ||
    (message.id != null ? turnsByMessageId[String(message.id)] ?? null : null) ||
    null
  );
}

describe("historic turn hydration", () => {
  it("prefers message.turn over turnsByMessageId", () => {
    const embedded: ChatTurn = {
      turn_id: "t-embed",
      conversation_id: "c1",
      effective_model: "embedded-model",
      run_state: "COMPLETED",
    };
    const mapped: ChatTurn = {
      turn_id: "t-map",
      conversation_id: "c1",
      effective_model: "mapped-model",
      run_state: "COMPLETED",
    };
    const msg: ChatDisplayMessage = {
      id: 7,
      role: "assistant",
      content: "hi",
      created_at: null,
      turn: embedded,
    };
    expect(resolveTurn(msg, { "7": mapped })?.turn_id).toBe("t-embed");
  });

  it("hydrates from turnsByMessageId when message.turn absent", () => {
    const mapped: ChatTurn = {
      turn_id: "t-map",
      conversation_id: "c1",
      effective_model: "m1",
      effective_reasoning_mode: "deep",
      knowledge_hit_count: 2,
      run_state: "COMPLETED",
    };
    const msg: ChatDisplayMessage = {
      id: 42,
      role: "assistant",
      content: "answer",
      created_at: "2026-01-01T00:00:00Z",
    };
    const turn = resolveTurn(msg, { "42": mapped });
    expect(turn?.effective_model).toBe("m1");
    expect(turn?.knowledge_hit_count).toBe(2);
  });

  it("does not invent turn metadata for old messages", () => {
    const msg: ChatDisplayMessage = {
      id: 1,
      role: "assistant",
      content: "legacy",
      created_at: null,
    };
    expect(resolveTurn(msg, {})).toBeNull();
  });
});
