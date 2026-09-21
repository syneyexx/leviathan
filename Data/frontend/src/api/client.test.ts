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
});
