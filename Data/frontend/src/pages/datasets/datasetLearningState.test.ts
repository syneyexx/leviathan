/**
 * WAVE 01 / Wave 13 — frontend learning-state helper consistency.
 * Job lists must not override LEARNED truth.
 * Queued must never project as learned.
 */

import { describe, expect, it } from "vitest";
import {
  displayStatusFromLearning,
  honestLearningProgress,
  learningStatusLabel,
  mapBrainStatusToCanonical,
  resolveLearningState,
  shouldShowJobAsLearningTruth,
  type DatasetLearningState,
} from "./datasetLearningState";

describe("datasetLearningState helpers", () => {
  const learned: DatasetLearningState = {
    datasetId: "d1",
    canonicalState: "LEARNED",
    brainStatus: "learned",
    learned: true,
    stale: true,
    progress: 1,
    label: "Geleerd",
  };

  it("READY+stale job projects as learned, not indexing", () => {
    const resolved = resolveLearningState({ learningState: learned });
    expect(displayStatusFromLearning(resolved)).toBe("learned");
    expect(shouldShowJobAsLearningTruth(resolved)).toBe(false);
    expect(honestLearningProgress(resolved)).toBe(100);
  });

  it("REBUILDING keeps learned truth while showing job detail", () => {
    const rebuilding: DatasetLearningState = {
      datasetId: "d1",
      canonicalState: "REBUILDING",
      brainStatus: "indexing",
      learned: true,
      priorReadyPreserved: true,
      usableIndexId: "idx-1",
      progress: 0.2,
    };
    expect(displayStatusFromLearning(rebuilding)).toBe("rebuilding");
    expect(shouldShowJobAsLearningTruth(rebuilding)).toBe(true);
    expect(honestLearningProgress(rebuilding)).toBe(20);
  });

  it("never invents a fake 35% when progress is missing", () => {
    const indexing: DatasetLearningState = {
      datasetId: "d1",
      canonicalState: "INDEXING",
      brainStatus: "indexing",
      learned: false,
      progress: null,
    };
    expect(honestLearningProgress(indexing)).toBeNull();
  });

  it("Dataset Manager and Offline map LEARNED identically", () => {
    const a = displayStatusFromLearning(learned);
    const b = displayStatusFromLearning(
      resolveLearningState({
        brainStatus: "learned",
        learned: true,
        canonicalState: "LEARNED",
      }),
    );
    expect(a).toBe("learned");
    expect(b).toBe("learned");
  });

  it("INDEX_QUEUED never displays as learned", () => {
    const queued: DatasetLearningState = {
      datasetId: "d1",
      canonicalState: "INDEX_QUEUED",
      brainStatus: "queued",
      learned: false,
      progress: null,
      label: "In wachtrij",
    };
    expect(displayStatusFromLearning(queued)).toBe("queued");
    expect(learningStatusLabel(queued)).toBe("In wachtrij");
    expect(shouldShowJobAsLearningTruth(queued)).toBe(true);
    expect(displayStatusFromLearning(queued)).not.toBe("learned");
  });

  it("mapBrainStatusToCanonical keeps queued distinct from learned", () => {
    expect(mapBrainStatusToCanonical("queued")).toBe("INDEX_QUEUED");
    expect(mapBrainStatusToCanonical("learned")).toBe("LEARNED");
    expect(mapBrainStatusToCanonical("not_learned")).toBe("LEGACY_NOT_LEARNED");
    expect(displayStatusFromLearning(resolveLearningState({ brainStatus: "queued" }))).toBe(
      "queued",
    );
  });

  it("FAILED and UNKNOWN stay explicit", () => {
    expect(
      displayStatusFromLearning({
        datasetId: "d1",
        canonicalState: "FAILED",
        brainStatus: "failed",
        error: "boom",
      }),
    ).toBe("failed");
    expect(
      displayStatusFromLearning({
        datasetId: "d1",
        canonicalState: "UNKNOWN",
        brainStatus: "not_learned",
      }),
    ).toBe("unknown");
  });
});
