/**
 * MessageList historic turn hydration + load-older contract + tool receipts.
 */
import { describe, expect, it } from "vitest";
import type { ChatTurn } from "../../types/api";
import type { ChatDisplayMessage } from "../../pages/chat/MessageList";
import {
  resolveHistoricActivity,
  resolveHistoricArtifactIds,
  resolveHistoricToolCalls,
  resolveTurnForMessage,
} from "./historicTurn";

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
    expect(resolveTurnForMessage(msg, { "7": mapped })?.turn_id).toBe("t-embed");
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
    const turn = resolveTurnForMessage(msg, { "42": mapped });
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
    expect(resolveTurnForMessage(msg, {})).toBeNull();
  });
});

describe("historic tool receipts", () => {
  it("renders tool_calls from durable turn for non-last messages", () => {
    const turn: ChatTurn = {
      turn_id: "t1",
      conversation_id: "c1",
      tool_calls: [
        {
          capability_id: "web.search",
          status: "COMPLETED",
          success: true,
          receipt_id: "r1",
          duration_ms: 12,
        },
      ],
    };
    const calls = resolveHistoricToolCalls(turn, {
      isLast: false,
      liveToolCalls: [{ capability_id: "live.only", status: "RUNNING" }],
    });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.capability_id).toBe("web.search");
    expect(calls[0]?.receipt_id).toBe("r1");
  });

  it("prefers live telemetry for the last message", () => {
    const turn: ChatTurn = {
      turn_id: "t1",
      conversation_id: "c1",
      tool_calls: [{ capability_id: "historic", status: "COMPLETED" }],
    };
    const calls = resolveHistoricToolCalls(turn, {
      isLast: true,
      liveToolCalls: [{ capability_id: "live.tool", status: "COMPLETED", success: true }],
    });
    expect(calls[0]?.capability_id).toBe("live.tool");
  });

  it("reads metadata.tool_calls when top-level absent", () => {
    const turn: ChatTurn = {
      turn_id: "t1",
      conversation_id: "c1",
      metadata: {
        tool_calls: [{ capability_id: "from.meta", status: "OK", module_id: "mod" }],
      },
    };
    const calls = resolveHistoricToolCalls(turn);
    expect(calls[0]?.capability_id).toBe("from.meta");
  });

  it("does not invent tool cards from receipt ids alone", () => {
    const turn: ChatTurn = {
      turn_id: "t1",
      conversation_id: "c1",
      tool_receipt_ids: ["r-only"],
    };
    expect(resolveHistoricToolCalls(turn)).toEqual([]);
  });
});

describe("historic activity", () => {
  it("surfaces activity only when present on the turn", () => {
    const turn: ChatTurn = {
      turn_id: "t1",
      conversation_id: "c1",
      activity: {
        operationId: "op-1",
        highestSequence: 1,
        tree: [],
        events: [
          {
            eventId: "e1",
            operationId: "op-1",
            sequence: 1,
            actorType: "system",
            category: "chat",
            phase: "complete",
            lifecycle: "completed",
            title: "turn complete",
          },
        ],
      },
    };
    const activity = resolveHistoricActivity(turn);
    expect(activity?.operationId).toBe("op-1");
  });

  it("does not invent activity from activity_ref alone", () => {
    const turn: ChatTurn = {
      turn_id: "t1",
      conversation_id: "c1",
      activity_ref: "run-123",
    };
    expect(resolveHistoricActivity(turn)).toBeNull();
  });

  it("surfaces durable artifact_ids without inventing paths", () => {
    const turn: ChatTurn = {
      turn_id: "t1",
      conversation_id: "c1",
      artifact_ids: ["abc-123-uuid", "  ", "def-456"],
    };
    expect(resolveHistoricArtifactIds(turn)).toEqual(["abc-123-uuid", "def-456"]);
    expect(resolveHistoricArtifactIds(null)).toEqual([]);
  });
});
