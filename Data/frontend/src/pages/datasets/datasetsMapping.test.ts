import { describe, expect, it } from "vitest";
import {
  embeddingsForDataset,
  mapStatus,
  measuredProgressPct,
  rowStatusLabel,
  semanticOperatorLabel,
  statusLabel,
} from "./datasetsMapping";
import type { DatasetJob, DatasetRecord } from "../../types/api";
import type { DhRow } from "./constants";

function ds(partial: Partial<DatasetRecord> & Pick<DatasetRecord, "datasetId" | "name">): DatasetRecord {
  return {
    sourceType: "local",
    status: "ready",
    description: "",
    schemaVersion: 1,
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    ...partial,
  };
}

describe("datasetsMapping status truth", () => {
  it("does not map unknown backend status to Ready", () => {
    expect(mapStatus("weird-new-state")).toBe("unknown");
    expect(statusLabel(mapStatus("weird-new-state"))).toBe("UNKNOWN");
    expect(mapStatus("ready")).toBe("ready");
    expect(mapStatus("")).toBe("unknown");
  });

  it("measuredProgressPct never invents a percentage", () => {
    const job = { progress: null } as DatasetJob;
    expect(measuredProgressPct(job)).toBeNull();
    expect(measuredProgressPct({ progress: 0.42 } as DatasetJob)).toBe(42);
  });
});

describe("Wave 13 embeddings / learning operator truth", () => {
  it("never treats completed INDEX job alone as indexed", () => {
    const record = ds({ datasetId: "d1", name: "x", status: "ready" });
    const jobs = [
      {
        jobId: "j1",
        datasetId: "d1",
        jobType: "INDEX",
        status: "completed",
        progress: 1,
      } as DatasetJob,
    ];
    expect(embeddingsForDataset(record, jobs).kind).toBe("not_indexed");
  });

  it("never treats metadata index string as indexed", () => {
    const record = ds({
      datasetId: "d1",
      name: "x",
      metadata: { indexStatus: "index-pending-path" },
    });
    expect(embeddingsForDataset(record, []).kind).not.toBe("indexed");
  });

  it("requires LEARNED / READY / usableIndexId for indexed chip", () => {
    const learned = ds({
      datasetId: "d1",
      name: "x",
      learningState: {
        datasetId: "d1",
        canonicalState: "LEARNED",
        brainStatus: "learned",
        learned: true,
        usableIndexId: "idx-1",
      },
    });
    expect(embeddingsForDataset(learned, []).kind).toBe("indexed");

    const queued = ds({
      datasetId: "d2",
      name: "y",
      learningState: {
        datasetId: "d2",
        canonicalState: "INDEX_QUEUED",
        brainStatus: "queued",
        learned: false,
      },
    });
    expect(embeddingsForDataset(queued, []).kind).toBe("queued");
  });

  it("distinguishes queued vs indexing in rowStatusLabel", () => {
    const queuedRow = {
      embeddings: { kind: "queued" },
      status: "processing",
    } as DhRow;
    const indexingRow = {
      embeddings: { kind: "indexing", pct: -1 },
      status: "processing",
    } as DhRow;
    expect(rowStatusLabel(queuedRow)).toBe("In wachtrij");
    expect(rowStatusLabel(indexingRow)).toBe("Indexeren");
  });

  it("does not show semantic active when embeddings unavailable", () => {
    const lexical = ds({
      datasetId: "d1",
      name: "x",
      primaryCategory: "nlp",
      learningState: {
        datasetId: "d1",
        canonicalState: "LEARNED",
        brainStatus: "learned",
        learned: true,
        embeddingMode: "lexical_only",
        semanticEmbeddings: false,
      },
    });
    expect(semanticOperatorLabel(lexical)).toContain("unavailable");
    expect(semanticOperatorLabel(lexical)).not.toContain("active");
  });

  it("keeps review-required explicit instead of pretending semantic is settled", () => {
    const pending = ds({
      datasetId: "d1",
      name: "x",
      semanticReviewRequired: true,
      semanticProfile: { primaryCategory: "code", reviewRequired: true },
    });
    expect(semanticOperatorLabel(pending)).toContain("Review required");
  });
});
