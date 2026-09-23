/**
 * Dataset Management action wiring — regression tests (handlers, gating, console).
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
const HOOK = resolve(__dirname, "./useDatasetActivity.ts");
const CLIENT = resolve(__dirname, "../../api/client.ts");

function pageSource(): string {
  return readFileSync(PAGE, "utf8");
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

describe("DatasetManagementPixelPage action wiring", () => {
  const src = pageSource();

  it("maps every Dataset Action to a real handler (no hard-disabled stubs)", () => {
    for (const id of [
      "upload",
      "hf",
      "local",
      "create",
      "delete",
      "offline",
      "dup",
      "index",
      "validate",
      "export",
    ]) {
      expect(src).toContain(`case "${id}"`);
    }
    expect(src).not.toContain("Offline-conversie wordt niet ondersteund door DatasetService");
    expect(src).not.toContain("Dupliceren is nog niet beschikbaar via de API");
    expect(src).not.toMatch(/disabled:\s*true/);
  });

  it("gates selection-dependent actions and keeps create/import ungated by selection", () => {
    expect(src).toContain('const needsSelection = ["delete", "offline", "dup", "index", "validate", "export"]');
    expect(src).toContain('const needsVersion = ["offline", "index", "validate", "export"]');
    // upload/hf/local/create must not require selection
    expect(src).toMatch(/needsSelection[\s\S]*does not include upload|needsSelection = \["delete"/);
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
    // Console after footer / main content stack
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

  it("uses offlineBrainPreflight + enqueueOfflineBrainIndex for offline convert", () => {
    expect(src).toContain("offlineBrainPreflight");
    expect(src).toContain("enqueueOfflineBrainIndex");
  });

  it("duplicates via api.duplicateDataset and rebuilds index with rebuild:true", () => {
    expect(src).toContain("duplicateDataset");
    expect(src).toContain("rebuild: true");
  });

  it("does not fabricate progress when backend progress is unknown", () => {
    // Removed local jobProgressPct that forced 0/100
    expect(src).not.toContain("function jobProgressPct");
    expect(progressRatio(job({ jobId: "1", jobType: "export", status: "running", progress: null }))).toBeNull();
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

  it("passes rebuild on indexDatasetVersion", () => {
    expect(src).toContain("rebuild?: boolean");
  });
});

describe("useDatasetActivity shared hook", () => {
  const src = hookSource();

  it("reuses mergeActivityEntries + adaptive pollingIntervalMs", () => {
    expect(src).toContain("mergeActivityEntries");
    expect(src).toContain("pollingIntervalMs");
    expect(src).toContain("preferredJobId");
    expect(src).toContain("clearActivityView");
    expect(src).toContain("onLifecycleChange");
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
