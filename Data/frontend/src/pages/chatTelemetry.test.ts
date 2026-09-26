import { describe, expect, it } from "vitest";
import type { AssistantTurnTelemetry, ChatResponse } from "../types/api";
import { buildDiagnosticStrip, deriveAssistantTelemetry } from "./chatTelemetry";

function baseChat(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    conversation_id: "c1",
    user_message: {
      id: 1,
      conversation_id: "c1",
      role: "user",
      content: "hi",
      created_at: "2026-01-01T00:00:00Z",
    },
    assistant_message: {
      id: 2,
      conversation_id: "c1",
      role: "assistant",
      content: "hello",
      created_at: "2026-01-01T00:00:01Z",
    },
    model: "local-model",
    reasoning: { intent: "chat", complexity: "low", use_knowledge: false, steps: [] },
    knowledge_sources: [],
    ...overrides,
  };
}

describe("chatTelemetry", () => {
  it("prefers assistant_telemetry and keeps tool receipts/duration", () => {
    const tel = deriveAssistantTelemetry(
      baseChat({
        assistant_telemetry: {
          model: "real-model",
          behavior_version: "3",
          behavior_hash: "abc123def456",
          brain_hits: 2,
          knowledge_hits: 2,
          memory_hits: 1,
          evidence_hits: 0,
          tools_invoked: ["web.search"],
          tool_calls: [
            {
              capability_id: "web.search",
              status: "COMPLETED",
              duration_ms: 42,
              receipt_id: "rcpt_1",
              success: true,
            },
          ],
          agent_delegations: [
            { agent_kind: "gi_web_research", status: "SELECTED", success: null },
          ],
          gi_specialists: ["gi_web_research"],
          web_sources: [{ title: "Example", url: "https://example.test", source: "web.search" }],
          execution_class: "TOOL_REQUIRED",
          verification_mode: "REQUIRED",
          verification_passed: true,
          context_budget: 4000,
          context_used: 1200,
          latency_ms: 88,
          web_used: true,
          truth: { telemetry_is_backend_backed: true },
        },
      }),
    );
    expect(tel.model).toBe("real-model");
    expect(tel.tool_calls?.[0]?.receipt_id).toBe("rcpt_1");
    expect(tel.tool_calls?.[0]?.duration_ms).toBe(42);
    expect(tel.agent_delegations?.[0]?.agent_kind).toBe("gi_web_research");
    expect(tel.web_sources).toHaveLength(1);
    expect(tel.behavior_version).toBe("3");
    expect(tel.truth?.no_hidden_cot).toBe(true);
  });

  it("derives from cognition when assistant_telemetry missing", () => {
    const tel = deriveAssistantTelemetry(
      baseChat({
        model: "m1",
        knowledge_sources: [{ id: "k1", title: "A", source: "brain" }],
        cognition: {
          run_id: "r1",
          status: "COMPLETED_UNVERIFIED",
          mode: "STANDARD",
          execution_class: "CURRENT_INFO",
          verification_mode: "REQUIRED",
          tools_invoked: ["web.search"],
          tool_calls: [
            {
              capability_id: "web.search",
              status: "COMPLETED",
              duration_ms: 5,
              receipt_id: null,
              success: true,
            },
          ],
          gi_specialists: ["gi_web_research"],
          retrieval_hits: { brain: 1, knowledge: 1, memory: 0, evidence: 0 },
          behavior_hash: "hashhash",
          context_budget: 3000,
          context_used: 900,
        },
      }),
    );
    expect(tel.execution_class).toBe("CURRENT_INFO");
    expect(tel.web_used).toBe(true);
    expect(tel.tools_invoked).toContain("web.search");
    expect(tel.tool_calls?.[0]?.capability_id).toBe("web.search");
    expect(tel.brain_hits).toBe(1);
    expect(tel.context_used).toBe(900);
  });

  it("diagnostic strip uses measured fields only — never invents brain %", () => {
    const tel: AssistantTurnTelemetry = {
      model: "m1",
      execution_class: "DIRECT",
      brain_hits: 0,
      web_used: false,
      tools_invoked: [],
      tool_calls: [],
      agents: [],
      gi_specialists: [],
      behavior_version: "3",
      context_used: 100,
      context_budget: 2000,
      latency_ms: 42,
    };
    const strip = buildDiagnosticStrip(tel);
    const labels = strip.map((s) => s.label);
    expect(labels).toEqual(
      expect.arrayContaining([
        "mode",
        "model",
        "brain",
        "web",
        "tools",
        "agents",
        "context",
        "latency",
        "behavior",
      ]),
    );
    expect(strip.find((s) => s.label === "brain")?.value).toBe("0 hits");
    expect(strip.find((s) => s.label === "context")?.value).toBe("100/2000");
    expect(strip.find((s) => s.label === "behavior")?.value).toBe("v3");
    expect(strip.every((s) => !/chain.of.thought|thinking/i.test(s.value))).toBe(true);
  });

  it("does not invent tool or agent rows without backend evidence", () => {
    const tel = deriveAssistantTelemetry(baseChat({ model: "m1" }));
    expect(tel.tool_calls ?? []).toHaveLength(0);
    expect(tel.agent_delegations ?? []).toHaveLength(0);
    expect(tel.web_used).toBe(false);
  });
});
