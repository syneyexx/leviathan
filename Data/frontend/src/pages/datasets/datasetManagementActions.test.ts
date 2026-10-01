/**
 * Dataset Management action wiring — regression tests (handlers, gating, console).
 * Canonical surface is `/datasets` (useDatasetsWorkspace + mutations).
 * Legacy Pixel DM remains as transitional reference until fully removed.
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

const PAGE = resolve(__dirname, "../pixel/DatasetManagementPixelPage.tsx");
const OFFLINE = resolve(__dirname, "../pixel/OfflineDatasetsPixelPage.tsx");
const CANONICAL = resolve(__dirname, "./useDatasetsWorkspace.ts");
const MUTATIONS = resolve(__dirname, "./useDatasetMutations.ts");
const HOOK = resolve(__dirname, "./useDatasetActivity.ts");
const CLIENT = resolve(__dirname, "../../api/client.ts");
const FLEET = resolve(__dirname, "./useDatasetLearningFleet.ts");

function pageSource(): string {
  return readFileSync(PAGE, "utf8");
}

function offlineSource(): string {
  return readFileSync(OFFLINE, "utf8");
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
});

describe("DatasetManagementPixelPage action wiring (legacy transitional)", () => {
  const src = pageSource();

  it("maps every Dataset Action to a real handler (no hard-disabled stubs)", () => {
    for (const id of [
      "upload",
      "hf",
      "local",
      "create",
      "rescan",
      "delete",
      "learn",
      "dup",
      "index",
      "validate",
      "export",
    ]) {
      expect(src).toContain(`case "${id}"`);
    }
    expect(src).not.toContain("Converteren naar offline");
    expect(src).not.toContain("onConvertOffline");
    expect(src).not.toContain("Offline-conversie wordt niet ondersteund door DatasetService");
    expect(src).not.toContain("Dupliceren is nog niet beschikbaar via de API");
    expect(src).not.toMatch(/disabled:\s*true/);
  });

  it("exposes Kennis leren and Opnieuw scannen", () => {
    expect(src).toContain('label: "Kennis leren"');
    expect(src).toContain('label: "Opnieuw scannen"');
    expect(src).toContain("api.learnDataset");
    expect(src).toContain("api.refreshDatasetLibrary");
  });

  it("gates selection-dependent actions and keeps create/import/rescan ungated by selection", () => {
    expect(src).toContain('const needsSelection = ["delete", "learn", "dup", "index", "validate", "export"]');
    expect(src).toContain('const needsVersion = ["index", "validate", "export"]');
  });

  it("treats Hugging Face filename as optional", () => {
    expect(src).toContain("filename: hfFilename.trim() || null");
    expect(src).toContain("leeg = volledige repo");
  });

  it("sets preferred console job for newly returned jobs", () => {
    expect(src).toContain("setPreferredJobId(job.jobId)");
    expect(src).toContain("await trackJob(res.job");
  });

  it("renders DatasetActivityConsole under Dataset Management content", () => {
    expect(src).toContain("import { DatasetActivityConsole }");
    expect(src).toContain("useDatasetActivity");
    expect(src).toContain("<DatasetActivityConsole");
    const footerIdx = src.indexOf("lv-px-footer-bar");
    const consoleIdx = src.indexOf("<DatasetActivityConsole");
    expect(footerIdx).toBeGreaterThan(0);
    expect(consoleIdx).toBeGreaterThan(footerIdx);
  });

  it("wires cancellation and delete reconciliation", () => {
    expect(src).toContain("api.cancelDatasetJob");
    expect(src).toContain("preferId: nextId");
    expect(src).toContain("api.deleteDataset");
  });

  it("exposes export artifact download only after backend acceptance", () => {
    expect(src).toContain("downloadDatasetExport");
    expect(src).toContain("Download export");
    expect(src).toContain("exportArtifact");
  });

  it("does not fabricate progress when backend progress is unknown", () => {
    expect(src).not.toContain("function jobProgressPct");
    expect(progressRatio(job({ jobId: "1", jobType: "export", status: "running", progress: null }))).toBeNull();
  });

  it("duplicates via api.duplicateDataset and rebuilds via learnDataset rebuild", () => {
    expect(src).toContain("duplicateDataset");
    expect(src).toContain("rebuild: true");
    expect(src).toContain("onLearnToBrain({ rebuild: true })");
  });
});

describe("OfflineDatasetsPixelPage redirect to canonical learning mode", () => {
  const src = offlineSource();

  it("redirects to /datasets?mode=learning and does not N+1 getDataset", () => {
    expect(src).toContain('Navigate to="/datasets?mode=learning"');
    expect(src).not.toContain("listLearnedDatasets");
    expect(src).not.toContain("api.getDataset");
    expect(src).toContain("listLearningFleet");
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
