import { describe, expect, it } from "vitest";
import type { DatasetJob } from "../../types/api";
import {
  downloadSummary,
  entriesFromJob,
  entriesToPlainText,
  estimatedRemainingSeconds,
  filterEntries,
  formatBytes,
  isActiveJob,
  mergeActivityEntries,
  observedTransferRate,
  pickActiveJob,
  pollingIntervalMs,
  progressRatio,
  redactActivityText,
} from "./datasetActivity";

function job(partial: Partial<DatasetJob> & Pick<DatasetJob, "jobId" | "jobType" | "status">): DatasetJob {
  return {
    createdAt: "2026-09-23T17:48:21.000Z",
    updatedAt: "2026-09-23T17:48:23.000Z",
    ...partial,
  };
}

describe("datasetActivity helpers", () => {
  it("loads and reconstructs entries for an active HF download", () => {
    const active = job({
      jobId: "j1",
      jobType: "import_hf",
      status: "running",
      phase: "downloading",
      startedAt: "2026-09-23T17:48:21.500Z",
      checkpoint: {
        repositoryId: "org/ds",
        filename: "train.parquet",
        bytesDownloaded: 83_000_000,
        totalBytes: 201_000_000,
        attempts: 1,
      },
    });
    expect(isActiveJob(active)).toBe(true);
    const entries = entriesFromJob(active);
    expect(entries.some((e) => e.stage === "QUEUED")).toBe(true);
    expect(entries.some((e) => e.stage === "DOWNLOAD")).toBe(true);
    expect(entries.find((e) => e.stage === "DOWNLOAD")?.message).toContain(formatBytes(83_000_000));
    expect(entries.find((e) => e.stage === "DOWNLOAD")?.message).toContain(formatBytes(201_000_000));
    expect(progressRatio(active)).toBeCloseTo(83_000_000 / 201_000_000, 5);
  });

  it("shows unknown total size without fabricating a denominator", () => {
    const active = job({
      jobId: "j2",
      jobType: "import_hf",
      status: "running",
      phase: "downloading",
      checkpoint: {
        repositoryId: "org/ds",
        filename: "a.parquet",
        bytesDownloaded: 438_000_000,
        totalBytes: null,
      },
    });
    const dl = downloadSummary(active);
    expect(dl?.bytesTotal).toBeNull();
    expect(progressRatio(active)).toBeNull();
    const msg = entriesFromJob(active).find((e) => e.stage === "DOWNLOAD")?.message ?? "";
    expect(msg).toContain("total size unknown");
    expect(msg).not.toMatch(/\d+(\.\d+)?%/);
  });

  it("surfaces retry / rate-limit events from checkpoint", () => {
    const active = job({
      jobId: "j3",
      jobType: "import_hf",
      status: "running",
      phase: "rate_limited",
      checkpoint: {
        filename: "train-00004.parquet",
        bytesDownloaded: 10,
        totalBytes: 100,
        attempts: 2,
        lastStatus: 429,
        rateLimitEvents: 1,
      },
    });
    const retry = entriesFromJob(active).find((e) => e.stage === "RETRY");
    expect(retry?.level).toBe("warning");
    expect(retry?.message).toContain("429");
    expect(retry?.message).toContain("attempt 2");
  });

  it("distinguishes completed, failed, cancelled, and queued truthfully", () => {
    const completed = entriesFromJob(
      job({
        jobId: "c",
        jobType: "import_local",
        status: "completed",
        phase: "done",
        finishedAt: "2026-09-23T17:49:00.000Z",
      }),
    );
    expect(completed.some((e) => e.stage === "COMPLETED" && e.level === "success")).toBe(true);

    const failed = entriesFromJob(
      job({
        jobId: "f",
        jobType: "import_hf",
        status: "failed",
        phase: "downloading",
        error: "Rate limit exceeded",
        checkpoint: { filename: "x.parquet", lastStatus: 429, attempts: 5 },
        finishedAt: "2026-09-23T17:49:00.000Z",
      }),
    );
    const fail = failed.find((e) => e.stage === "FAILED");
    expect(fail?.level).toBe("error");
    expect(fail?.message).toContain("Rate limit exceeded");
    expect(fail?.message).toContain("HTTP 429");

    const cancelled = entriesFromJob(
      job({
        jobId: "k",
        jobType: "materialize",
        status: "cancelled",
        finishedAt: "2026-09-23T17:49:00.000Z",
      }),
    );
    expect(cancelled.some((e) => e.stage === "CANCELLED")).toBe(true);

    const queued = job({ jobId: "q", jobType: "validate", status: "queued" });
    expect(entriesFromJob(queued).some((e) => e.message.toLowerCase().includes("successful"))).toBe(false);
    expect(entriesFromJob(queued).every((e) => e.stage !== "COMPLETED")).toBe(true);
  });

  it("keeps materialization phase visible after download", () => {
    const mat = job({
      jobId: "m1",
      jobType: "import_hf",
      status: "running",
      phase: "materializing",
      checkpoint: {
        filename: "train.parquet",
        bytesDownloaded: 100,
        totalBytes: 100,
      },
    });
    expect(entriesFromJob(mat).some((e) => e.stage === "MATERIALIZING")).toBe(true);
    expect(entriesFromJob(mat).some((e) => e.stage === "COMPLETED")).toBe(false);
  });

  it("filters activity and picks active jobs", () => {
    const jobs = [
      job({ jobId: "a", jobType: "import_hf", status: "running", phase: "downloading" }),
      job({ jobId: "b", jobType: "export", status: "completed", phase: "done" }),
      job({ jobId: "c", jobType: "validate", status: "failed", error: "x" }),
    ];
    expect(pickActiveJob(jobs)?.jobId).toBe("a");
    const merged = mergeActivityEntries([], jobs, new Map());
    expect(filterEntries(merged, "errors", "all").every((e) => e.level === "error" || e.level === "warning")).toBe(
      true,
    );
    expect(filterEntries(merged, "completed", "b").some((e) => e.jobId === "b")).toBe(true);
  });

  it("redacts secrets and never renders tokens in plain text export", () => {
    const dirty = redactActivityText("Authorization: Bearer hf_SECRETtoken1234567890 and token=abc");
    expect(dirty).not.toContain("hf_SECRET");
    expect(dirty).toContain("[REDACTED]");
    const entries = entriesFromJob(
      job({
        jobId: "sec",
        jobType: "import_hf",
        status: "failed",
        error: "failed with Bearer hf_ABCDEFGHIJKLMNOPQRST",
      }),
    );
    const text = entriesToPlainText(entries);
    expect(text).not.toMatch(/hf_[A-Za-z0-9]{10,}/);
    expect(text).not.toMatch(/Bearer\s+(?!\[REDACTED\])\S+/i);
    expect(text).toContain("[REDACTED]");
  });

  it("computes observed transfer rate and hides weak ETA", () => {
    const rate = observedTransferRate([
      { atMs: 1000, bytes: 0 },
      { atMs: 2000, bytes: 8_400_000 },
    ]);
    expect(rate).toBeCloseTo(8_400_000, -2);
    expect(estimatedRemainingSeconds(100, 200, 10)).toBeNull(); // rate too low / unstable threshold
    expect(estimatedRemainingSeconds(100_000_000, 200_000_000, 50_000_000)).toBeCloseTo(2, 5);
  });

  it("backs off polling on failures and slows when idle", () => {
    expect(pollingIntervalMs({ hasActive: true, hasJobs: true, consecutiveFailures: 0 })).toBe(1000);
    expect(pollingIntervalMs({ hasActive: false, hasJobs: true, consecutiveFailures: 0 })).toBe(2500);
    expect(pollingIntervalMs({ hasActive: false, hasJobs: false, consecutiveFailures: 0 })).toBe(12_000);
    expect(pollingIntervalMs({ hasActive: true, hasJobs: true, consecutiveFailures: 3 })).toBeGreaterThan(1000);
  });

  it("formats bytes without inventing values", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(1024)).toBe("1.0 KB");
  });

  it("handles empty job list", () => {
    expect(pickActiveJob([])).toBeNull();
    expect(mergeActivityEntries([], [], new Map())).toEqual([]);
  });
});
