import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./client";

describe("ApiError", () => {
  it("preserves HTTP status", () => {
    const error = new ApiError(503, "LLM unavailable");
    expect(error.status).toBe(503);
    expect(error.message).toBe("LLM unavailable");
  });
});

describe("api client — datasets / training / research / model test", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function mockFetch(status: number, body: unknown, capture?: { init?: RequestInit; url?: string }) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
        if (capture) {
          capture.url = String(url);
          capture.init = init;
        }
        return {
          ok: status >= 200 && status < 300,
          status,
          json: async () => body,
        };
      }),
    );
  }

  it("listDatasets returns typed payload", async () => {
    mockFetch(200, { datasets: [] });
    const res = await api.listDatasets();
    expect(res.datasets).toEqual([]);
  });

  it("uploadDataset omits Content-Type for FormData", async () => {
    const capture: { init?: RequestInit; url?: string } = {};
    mockFetch(200, { job: { jobId: "j1" }, bytes: 10, filename: "a.jsonl" }, capture);
    const form = new FormData();
    form.append("file", new Blob(["x"]), "a.jsonl");
    await api.uploadDataset(form);
    const headers = new Headers(capture.init?.headers);
    expect(headers.has("Content-Type")).toBe(false);
    expect(capture.init?.body).toBe(form);
  });

  it("json requests still set Content-Type application/json", async () => {
    const capture: { init?: RequestInit } = {};
    mockFetch(200, { dataset: { datasetId: "d1", name: "n" } }, capture);
    await api.createDataset({ name: "n" });
    const headers = new Headers(capture.init?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("trainingCapabilities hits /api/training/capabilities", async () => {
    const capture: { url?: string } = {};
    mockFetch(
      200,
      {
        capabilities: {
          packages: [],
          canRunFixture: true,
          canRunLora: false,
          canRunQlora: false,
          canRunDpo: false,
          ready: false,
          missingForLora: ["torch"],
          notes: [],
        },
      },
      capture,
    );
    const res = await api.trainingCapabilities();
    expect(capture.url).toBe("/api/training/capabilities");
    expect(res.capabilities.canRunFixture).toBe(true);
  });

  it("listResearchProjects returns empty list honestly", async () => {
    mockFetch(200, { projects: [] });
    const res = await api.listResearchProjects();
    expect(res.projects).toEqual([]);
  });

  it("testModel posts to /api/models/{id}/test", async () => {
    const capture: { url?: string; init?: RequestInit } = {};
    mockFetch(
      200,
      {
        result: {
          ok: true,
          modelId: "m1",
          providerId: "p1",
          preview: "pong",
        },
      },
      capture,
    );
    const res = await api.testModel("m1", { prompt: "ping", maxTokens: 16 });
    expect(capture.url).toBe("/api/models/m1/test");
    expect(capture.init?.method).toBe("POST");
    expect(res.result.preview).toBe("pong");
  });

  it("surfaces nested research error detail", async () => {
    mockFetch(400, {
      detail: { error: { code: "web_blocked", message: "Web disabled" } },
    });
    await expect(api.runResearchProject("p1")).rejects.toMatchObject({
      status: 400,
      message: "web_blocked: Web disabled",
    });
  });

  it("chat sends model_id when selected and omits it for Auto", async () => {
    const capture: { url?: string; init?: RequestInit } = {};
    mockFetch(200, { conversation_id: "c1" }, capture);
    await api.chat("hi", { conversationId: "c1", modelId: "model-a" });
    expect(JSON.parse(String(capture.init?.body))).toMatchObject({
      message: "hi",
      conversation_id: "c1",
      model_id: "model-a",
    });

    const captureAuto: { init?: RequestInit } = {};
    mockFetch(200, { conversation_id: "c1" }, captureAuto);
    await api.chat("hi", { conversationId: "c1" });
    const body = JSON.parse(String(captureAuto.init?.body)) as Record<string, unknown>;
    expect(body.model_id).toBeUndefined();
  });

  it("coding create/turn emit camelCase contract fields", async () => {
    const createCap: { init?: RequestInit } = {};
    mockFetch(200, { session: { session_id: "s1" } }, createCap);
    await api.createCodingSession({
      goal: "fix",
      mission: "FIX",
      workspaceRoot: "/ws",
      modelId: "m1",
    });
    expect(JSON.parse(String(createCap.init?.body))).toEqual({
      goal: "fix",
      mission: "FIX",
      workspaceRoot: "/ws",
      modelId: "m1",
    });

    const turnCap: { init?: RequestInit; url?: string } = {};
    mockFetch(200, { session: { session_id: "s1", status: "RUNNING" } }, turnCap);
    const turn = await api.codingTurn("s1", { approvalId: "a1", capabilityId: "file.write" });
    expect(turnCap.url).toBe("/api/coding/sessions/s1/turn");
    expect(JSON.parse(String(turnCap.init?.body))).toEqual({
      approvalId: "a1",
      capabilityId: "file.write",
    });
    expect(turn.session.session_id).toBe("s1");
  });

  it("updateConversation and deleteConversation hit conversation routes", async () => {
    const patchCap: { url?: string; init?: RequestInit } = {};
    mockFetch(200, { conversation: { id: "c1", title: "T", pinned: true } }, patchCap);
    await api.updateConversation("c1", { pinned: true, title: "T" });
    expect(patchCap.url).toBe("/api/conversations/c1");
    expect(patchCap.init?.method).toBe("PATCH");

    const delCap: { url?: string; init?: RequestInit } = {};
    mockFetch(200, { deleted: true, id: "c1" }, delCap);
    await api.deleteConversation("c1");
    expect(delCap.url).toBe("/api/conversations/c1");
    expect(delCap.init?.method).toBe("DELETE");
  });

  it("systemTelemetry hits /api/system/telemetry", async () => {
    const capture: { url?: string } = {};
    mockFetch(
      200,
      {
        collectedAt: "now",
        ageMs: 1,
        cpu: { available: true, utilizationPct: 1 },
        memory: {
          available: true,
          totalBytes: 1,
          usedBytes: 1,
          availableBytes: 0,
          utilizationPct: 100,
        },
        gpu: { available: false, devices: [] },
        truth: { measured: true, synthetic: false },
        dashboard: { cpuPct: 1, ramPct: 100, gpuPct: null, vramPct: null },
      },
      capture,
    );
    const res = await api.systemTelemetry();
    expect(capture.url).toBe("/api/system/telemetry");
    expect(res.dashboard.gpuPct).toBeNull();
  });
});
