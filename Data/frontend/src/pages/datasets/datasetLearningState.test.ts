/**
 * WAVE 01 — frontend learning-state helper consistency.
 * Job lists must not override LEARNED truth.
 */

import { describe, expect, it } from "vitest";
import {
  displayStatusFromLearning,
  honestLearningProgress,
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
});
