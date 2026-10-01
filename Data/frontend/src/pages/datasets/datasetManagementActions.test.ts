/**
 * Dataset Management action wiring — regression tests (handlers, gating, console).
 * Canonical surface is `/datasets` (useDatasetsWorkspace + mutations).
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  isActiveJob,
  mergeActivityEntries,
  pollingIntervalMs,
  progressRatio,
} from "./datasetActivity";
import type { DatasetActivityEntry, DatasetJob } from "../../types/api";

const OFFLINE = resolve(__dirname, "../pixel/OfflineDatasetsPixelPage.tsx");
const DM_REDIRECT = resolve(__dirname, "../DatasetManagementPage.tsx");
const CANONICAL = resolve(__dirname, "./useDatasetsWorkspace.ts");
const MUTATIONS = resolve(__dirname, "./useDatasetMutations.ts");
const HOOK = resolve(__dirname, "./useDatasetActivity.ts");
const CLIENT = resolve(__dirname, "../../api/client.ts");
const FLEET = resolve(__dirname, "./useDatasetLearningFleet.ts");

function offlineSource(): string {
  return readFileSync(OFFLINE, "utf8");
}

function dmRedirectSource(): string {
  return readFileSync(DM_REDIRECT, "utf8");
}

function canonicalSource(): string {
  return readFileSync(CANONICAL, "utf8") + "\n" + readFileSync(MUTATIONS, "utf8");
}

function hookSource(): string {
  return readFileSync(HOOK, "utf8");
}

function clientSource(): string {
  return readFileSync(CLIENT, "utf8");
}

function job(partial: Partial<DatasetJob> & Pick<DatasetJob, "jobId" | "jobType" | "status">): DatasetJob {
  return {
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:01Z",
    ...partial,
  };
}

describe("Canonical /datasets workspace action wiring", () => {
  const src = canonicalSource();

  it("wires DM-parity mutations through useDatasetMutations", () => {
    for (const name of [
      "onValidate",
      "onDedupe",
      "onTransform",
      "onSplit",
      "onTokenize",
      "onScanPii",
      "onContaminationScan",
      "onMaterialize",
      "onLearn",
      "onDuplicate",
      "onRefreshLibrary",
      "onExportDownload",
      "onSaveSemantic",
    ]) {
      expect(src).toContain(name);
    }
    expect(src).not.toContain("processDatasetJobs");
    expect(src).not.toContain("onProcessQueue");
  });

  it("uses MutationOutcome instead of naive always-success toasts", () => {
    expect(src).toContain("MutationOutcome");
    expect(src).toContain("startedJob");
    expect(src).toContain("blocked(");
  });

  it("does not fabricate progress when backend progress is unknown", () => {
    expect(progressRatio(job({ jobId: "1", jobType: "export", status: "running", progress: null }))).toBeNull();
  });
});

describe("Legacy /dataset-management redirect", () => {
  it("redirects to /datasets?mode=manage", () => {
    const src = dmRedirectSource();
    expect(src).toContain('Navigate to="/datasets?mode=manage"');
  });
});

describe("OfflineDatasetsPixelPage redirect to canonical learning mode", () => {
  const src = offlineSource();

  it("redirects to /datasets?mode=learning and does not N+1 getDataset", () => {
    expect(src).toContain('Navigate to="/datasets?mode=learning"');
    expect(src).not.toContain("listLearnedDatasets");
    expect(src).not.toContain("api.getDataset");
  });
});

describe("Learning fleet hook", () => {
  it("calls listLearningFleet only", () => {
    const src = readFileSync(FLEET, "utf8");
    expect(src).toContain("listLearningFleet");
    expect(src).not.toContain("getDataset");
  });
});

describe("API client dataset action additions", () => {
  const src = clientSource();

  it("exposes duplicateDataset and downloadDatasetExport", () => {
    expect(src).toContain("duplicateDataset(");
    expect(src).toContain("downloadDatasetExport(");
    expect(src).toContain("requestBlob(");
    expect(src).toContain("/duplicate");
    expect(src).toContain("/download");
  });

  it("exposes learnDataset and refreshDatasetLibrary", () => {
    expect(src).toContain("learnDataset(");
    expect(src).toContain("refreshDatasetLibrary(");
    expect(src).toContain("listLearnedDatasets(");
    expect(src).toContain("listLearningFleet(");
    expect(src).toContain("/learn");
    expect(src).toContain("/library/refresh");
    expect(src).toContain("/learning/fleet");
  });

  it("passes rebuild on indexDatasetVersion", () => {
    expect(src).toContain("rebuild?: boolean");
  });
});

describe("useDatasetActivity shared hook", () => {
  const src = hookSource();

  it("reuses mergeActivityEntries + adaptive pollingIntervalMs and accepts createdAfter", () => {
    expect(src).toContain("mergeActivityEntries");
    expect(src).toContain("pollingIntervalMs");
    expect(src).toContain("preferredJobId");
    expect(src).toContain("clearActivityView");
    expect(src).toContain("onLifecycleChange");
    expect(src).toContain("createdAfter");
    expect(src).toContain("datasetId");
  });

  it("guards overlapping polls and skips when document is hidden", () => {
    expect(src).toContain("inFlightRef");
    expect(src).toContain("document.hidden");
    expect(src).toContain("visibilitychange");
  });

  it("merges activity and backs off on API failures", () => {
    const prev = new Map<string, DatasetJob>();
    const b = job({
      jobId: "j1",
      jobType: "import_local",
      status: "running",
      phase: "copying",
      progress: 0.4,
      updatedAt: "2026-01-01T00:00:02Z",
    });
    const entries: DatasetActivityEntry[] = [];
    const merged = mergeActivityEntries(entries, [b], prev);
    expect(merged.length).toBeGreaterThan(0);
    expect(isActiveJob(b)).toBe(true);
    expect(pollingIntervalMs({ hasActive: true, hasJobs: true, consecutiveFailures: 0 })).toBe(1000);
    expect(pollingIntervalMs({ hasActive: false, hasJobs: false, consecutiveFailures: 3 })).toBeGreaterThan(
      2000,
    );
  });
});
