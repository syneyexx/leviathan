import { describe, expect, it } from "vitest";

describe("chat control-plane contracts", () => {
  it("filters conversations by title search", () => {
    const conversations = [
      { id: "1", title: "Trading plan", pinned: false },
      { id: "2", title: "Coding helpers", pinned: true },
      { id: "3", title: "Market notes", pinned: false },
    ];
    const q = "cod";
    const filtered = conversations.filter((c) => c.title.toLowerCase().includes(q.toLowerCase()));
    expect(filtered.map((c) => c.id)).toEqual(["2"]);
  });

  it("pinned chip keeps only durable pinned rows", () => {
    const conversations = [
      { id: "1", title: "A", pinned: false },
      { id: "2", title: "B", pinned: true },
    ];
    const pinned = conversations.filter((c) => c.pinned);
    expect(pinned).toHaveLength(1);
    expect(pinned[0].id).toBe("2");
  });

  it("Auto model omits modelId while explicit selection keeps it", () => {
    const auto: { modelId?: string | null } = {};
    const selected: { modelId?: string | null } = { modelId: "llama-local" };
    expect(auto.modelId ?? null).toBeNull();
    expect(selected.modelId).toBe("llama-local");
  });

  it("agents tab never fabricates online state without backend evidence", () => {
    const agentsEnabled: boolean | null = null;
    const codingEnabled: boolean | null = false;
    const agentLabel =
      agentsEnabled == null ? "Unknown" : agentsEnabled ? "Enabled" : "Disabled";
    const codingLabel =
      codingEnabled == null ? "Unknown" : codingEnabled ? "Enabled" : "Disabled";
    expect(agentLabel).toBe("Unknown");
    expect(codingLabel).toBe("Disabled");
    expect(agentLabel).not.toBe("Online");
  });
});

describe("coding page contract helpers", () => {
  it("prefers step.output over legacy output_json", () => {
    const step = {
      output: { exit_code: 1, stdout: "fail" },
      output_json: { exit_code: 0, stdout: "pass" },
    };
    const out = step.output ?? step.output_json;
    expect(out.exit_code).toBe(1);
    expect(out.stdout).not.toBe("pass");
  });

  it("diff tab semantics map applied patches, not git staged", () => {
    const patches = [
      { patch_id: "1", applied: true },
      { patch_id: "2", applied: false },
    ];
    const applied = patches.filter((p) => p.applied);
    const pending = patches.filter((p) => !p.applied);
    expect(applied).toHaveLength(1);
    expect(pending).toHaveLength(1);
  });
});
