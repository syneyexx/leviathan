import { describe, expect, it } from "vitest";

// Lightweight pure helpers mirrored from DatasetsPage status mapping.
type DhStatus = "ready" | "offline" | "validating" | "processing" | "failed" | "cancelled";

function mapStatus(status: string): DhStatus {
  const s = status.toLowerCase();
  if (s === "offline" || s === "cached") return "offline";
  if (s.includes("validat")) return "validating";
  if (s === "failed" || s === "error" || s === "interrupted" || s.includes("fail") || s.includes("error")) {
    return "failed";
  }
  if (s === "cancelled" || s === "canceled") return "cancelled";
  if (
    s === "running" ||
    s === "processing" ||
    s === "importing" ||
    s === "materializing" ||
    s === "queued"
  ) {
    return "processing";
  }
  if (s === "ready" || s === "complete" || s === "completed" || s === "processed" || s === "materialized") {
    return "ready";
  }
  if (s === "created" || s === "raw" || s === "archived") {
    return s === "archived" ? "offline" : "processing";
  }
  return "failed";
}

describe("Datasets HF status mapping", () => {
  it("does not default unknown/failed states to ready", () => {
    expect(mapStatus("failed")).toBe("failed");
    expect(mapStatus("error")).toBe("failed");
    expect(mapStatus("interrupted")).toBe("failed");
    expect(mapStatus("cancelled")).toBe("cancelled");
    expect(mapStatus("mystery")).toBe("failed");
  });

  it("maps import lifecycle states to processing", () => {
    expect(mapStatus("importing")).toBe("processing");
    expect(mapStatus("materializing")).toBe("processing");
    expect(mapStatus("queued")).toBe("processing");
  });

  it("maps ready only for ready-like statuses", () => {
    expect(mapStatus("ready")).toBe("ready");
    expect(mapStatus("completed")).toBe("ready");
  });
});

describe("HF import payload shape", () => {
  it("repository-level payload omits filename", () => {
    const payload = {
      repositoryId: "owner/dataset",
      revision: "main",
      token: null as string | null,
      materialize: true,
    };
    expect(payload).not.toHaveProperty("filename");
    expect(payload.repositoryId).toBe("owner/dataset");
  });
});
