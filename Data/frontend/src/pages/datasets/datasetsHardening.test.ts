/**
 * Phase 3–7 Datasets hardening unit tests.
 */

import { describe, expect, it, vi, afterEach } from "vitest";
import {
  activityPeriodToQueryParams,
  buildListDatasetsParams,
  typeLabelToQueryParam,
  updatedFilterToQueryParams,
} from "./datasetFilterParams";
import {
  blocked,
  completed,
  isSuccessOutcome,
  mutationToastKind,
  outcomeFromBulk,
  startedJob,
} from "./mutationOutcomes";
import { healthBarStyle, healthPctLabel, buildCatalogHealthItems } from "./datasetHealth";
import {
  initTagsFromDataset,
  normalizeTagList,
  resolveTagsToSave,
  addTag,
  removeTag,
} from "./tagEdit";
import {
  emptyCreateForm,
  emptyHfImportForm,
  emptyLocalImportForm,
  emptyUploadForm,
  redactHfFormForLog,
} from "./datasetForms";
import {
  canDownloadExport,
  exportEnqueued,
  exportPhaseLabel,
  exportReady,
  initialExportState,
} from "./exportState";
import { seriesFromPreview } from "./previewSeries";
import { api } from "../../api/client";

describe("datasetFilterParams", () => {
  it("maps type labels to detectedFormat query params", () => {
    expect(typeLabelToQueryParam("Documenten")).toEqual({ detectedFormat: "md" });
    expect(typeLabelToQueryParam("Code")).toEqual({ detectedFormat: "code" });
    expect(typeLabelToQueryParam("Tekst")).toEqual({ detectedFormat: "text" });
    expect(typeLabelToQueryParam("Tabel")).toEqual({ detectedFormat: "csv" });
    expect(typeLabelToQueryParam("JSON")).toEqual({ detectedFormat: "json" });
    expect(typeLabelToQueryParam("Alle types")).toEqual({});
  });

  it("maps updated filters to ISO updatedAfter", () => {
    const now = Date.parse("2026-06-15T12:00:00.000Z");
    const r = updatedFilterToQueryParams("Laatste 24 uur", now);
    expect(r.updatedAfter).toBe(new Date(now - 24 * 60 * 60 * 1000).toISOString());
    expect(updatedFilterToQueryParams("Oudste eerst", now).sort).toBe("updated_at_asc");
  });

  it("builds full listDatasets params including server filters", () => {
    const p = buildListDatasetsParams({
      filter: "local",
      query: "corpus",
      typeFilter: "Code",
      updatedFilter: "Laatste 7 dagen",
      offset: 50,
      nowMs: Date.parse("2026-06-15T12:00:00.000Z"),
    });
    expect(p.q).toBe("corpus");
    expect(p.sourceScope).toBe("local");
    expect(p.detectedFormat).toBe("code");
    expect(p.offset).toBe(50);
    expect(p.updatedAfter).toBeTruthy();
  });

  it("maps activity period to createdAfter", () => {
    const now = Date.parse("2026-06-15T12:00:00.000Z");
    expect(activityPeriodToQueryParams("Laatste 24 uur", now).createdAfter).toBe(
      new Date(now - 24 * 60 * 60 * 1000).toISOString(),
    );
    expect(activityPeriodToQueryParams("Alles", now)).toEqual({});
  });
});

describe("mutationOutcomes", () => {
  it("toasts success only for completed/started/partial-with-success", () => {
    expect(mutationToastKind(completed("ok"))).toBe("success");
    expect(mutationToastKind(startedJob("job", "j1"))).toBe("success");
    expect(mutationToastKind(blocked("nee"))).toBe("info");
    expect(isSuccessOutcome(blocked("x"))).toBe(false);
    expect(
      mutationToastKind(outcomeFromBulk({ succeeded: 2, failed: 1, message: "partial" })),
    ).toBe("success");
    expect(
      mutationToastKind(outcomeFromBulk({ succeeded: 0, failed: 3, message: "fail" })),
    ).toBe("error");
  });
});

describe("UNMEASURED health bars", () => {
  it("never coerces null pct to 0% width", () => {
    const bar = healthBarStyle(null);
    expect(bar.className).toContain("is-indeterminate");
    expect(bar.style).toBeUndefined();
    expect(healthPctLabel(null)).toBe("UNMEASURED");
    expect(healthBarStyle(40).style?.width).toBe("40%");
  });

  it("builds catalog health from overview not page length", () => {
    const items = buildCatalogHealthItems({
      totalDatasets: 100,
      readyDatasets: 40,
      datasetsWithValidation: 10,
      datasetsWithoutValidation: 90,
      indexedDatasets: 25,
      localDatasets: 60,
      byStatus: { ready: 40, unknown: 2 },
      totalSamples: 0,
      samplesMeasuredDatasets: 0,
      samplesUnmeasuredDatasets: 0,
      totalKnownBytes: 0,
      attributableBytes: 0,
      bytesMeasuredDatasets: 0,
      bytesUnmeasuredDatasets: 0,
      measurementStatus: "measured",
      activeImports: 0,
      runningImports: 0,
      queuedImports: 0,
      validationIssues: 0,
      criticalValidationIssues: 0,
      warningValidationIssues: 0,
      versionsWithValidation: 10,
      exportVersionCount: 0,
      bySourceType: {},
      tagCounts: [],
      storageBreakdown: [],
      catalogStatus: { status: "ok" } as never,
      services: [],
    });
    expect(items.find((i) => i.id === "ready")?.pct).toBe(40);
    expect(items.find((i) => i.id === "schema")?.pct).toBe(10);
    expect(buildCatalogHealthItems(null)[0].pct).toBeNull();
  });
});

describe("tag edit", () => {
  it("initializes and normalizes tags without silent wipe", () => {
    expect(initTagsFromDataset({ semanticTags: ["A", "a", " B "] })).toEqual(["A", "B"]);
    expect(normalizeTagList(["Foo", "foo", "Bar"])).toEqual(["Foo", "Bar"]);
    expect(resolveTagsToSave("", ["keep"])).toEqual({
      kind: "blocked",
      message: expect.stringContaining("niet stilzwijgend"),
    });
    expect(resolveTagsToSave("x,y", []).kind).toBe("save");
    expect(addTag(["a"], "A")).toEqual(["a"]);
    expect(removeTag(["a", "b"], "A")).toEqual(["b"]);
  });
});

describe("form isolation", () => {
  it("resets to empty factories and redacts HF token", () => {
    expect(emptyCreateForm().name).toBe("");
    expect(emptyUploadForm().file).toBeNull();
    expect(emptyLocalImportForm().path).toBe("");
    const hf = emptyHfImportForm();
    hf.token = "secret-token";
    const redacted = redactHfFormForLog(hf);
    expect(redacted).not.toHaveProperty("token");
    expect(redacted.tokenPresent).toBe(true);
  });
});

describe("export state machine", () => {
  it("only allows download when READY with ids", () => {
    let s = initialExportState();
    expect(canDownloadExport(s)).toBe(false);
    s = exportEnqueued(s, { datasetId: "d1", jobId: "j1" });
    expect(exportPhaseLabel(s.phase)).toContain("wachtrij");
    expect(canDownloadExport(s)).toBe(false);
    s = exportReady(s, { versionId: "v1" });
    expect(canDownloadExport(s)).toBe(true);
  });
});

describe("preview series", () => {
  it("requires timestamp/x AND numeric measure — no fake price series", () => {
    expect(seriesFromPreview([{ a: 1 }, { a: 2 }, { a: 3 }])).toBeNull();
    expect(
      seriesFromPreview([
        { timestamp: "2026-01-01", price: 10 },
        { timestamp: "2026-01-02", price: 11 },
        { timestamp: "2026-01-03", price: 12 },
      ]),
    ).toMatchObject({ label: "price", xLabel: "timestamp" });
  });
});

describe("api client datasets contracts", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function mockFetch(status: number, body: unknown, capture?: { url?: string }) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL | Request) => {
        if (capture) capture.url = String(url);
        return {
          ok: status >= 200 && status < 300,
          status,
          json: async () => body,
        };
      }),
    );
  }

  it("listDatasets passes updatedAfter/cursor and returns nextCursor", async () => {
    const capture: { url?: string } = {};
    mockFetch(200, { datasets: [], total: 3, nextCursor: "c2" }, capture);
    const res = await api.listDatasets(50, {
      updatedAfter: "2026-01-01T00:00:00.000Z",
      cursor: "c1",
      detectedFormat: "code",
      tags: "nlp",
    });
    expect(capture.url).toContain("updatedAfter=");
    expect(capture.url).toContain("cursor=c1");
    expect(capture.url).toContain("detectedFormat=code");
    expect(capture.url).toContain("tags=nlp");
    expect(res.nextCursor).toBe("c2");
    expect(res.total).toBe(3);
  });

  it("listDatasetJobs accepts options object with createdAfter and total", async () => {
    const capture: { url?: string } = {};
    mockFetch(200, { jobs: [], total: 7 }, capture);
    const res = await api.listDatasetJobs({
      datasetId: "d1",
      createdAfter: "2026-01-01T00:00:00.000Z",
      limit: 25,
    });
    expect(capture.url).toContain("datasetId=d1");
    expect(capture.url).toContain("createdAfter=");
    expect(capture.url).toContain("limit=25");
    expect(res.total).toBe(7);
    // backward compatible overload
    await api.listDatasetJobs("d2", 10);
    expect(capture.url).toContain("datasetId=d2");
  });

  it("listLearningFleet hits fleet endpoint (no N+1)", async () => {
    const capture: { url?: string } = {};
    mockFetch(200, { datasets: [], truth: { embedsDatasetSummaryToAvoidNPlusOne: true } }, capture);
    await api.listLearningFleet(50);
    expect(capture.url).toBe("/api/datasets/learning/fleet?limit=50");
  });
});

describe("process queue UI contract", () => {
  it("canonical workspace source does not call processDatasetJobs from UI path", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const ws = readFileSync(resolve(__dirname, "./useDatasetsWorkspace.ts"), "utf8");
    const mut = readFileSync(resolve(__dirname, "./useDatasetMutations.ts"), "utf8");
    const toolbar = readFileSync(
      resolve(__dirname, "../../components/datasets/DatasetsToolbar.tsx"),
      "utf8",
    );
    expect(ws).not.toContain("processDatasetJobs");
    expect(mut).not.toContain("processDatasetJobs");
    expect(mut).not.toContain("onProcessQueue");
    expect(toolbar).toContain("canProcess");
    expect(toolbar).toContain("Selecteer datasets om te verwerken");
  });
});
