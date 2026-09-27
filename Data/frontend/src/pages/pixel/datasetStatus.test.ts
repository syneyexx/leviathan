import { describe, expect, it } from "vitest";
import { mapDatasetStatus, toneForDatasetStatus } from "./datasetStatus";

describe("mapDatasetStatus product truth (FRONTEND-003)", () => {
  it("does not map unknown / empty status to success-like Verwerkt", () => {
    expect(mapDatasetStatus("")).toBe("Onbekend");
    expect(mapDatasetStatus("unknown")).toBe("Onbekend");
    expect(mapDatasetStatus("weird-backend-state")).toBe("Onbekend");
    expect(mapDatasetStatus("unmeasured")).toBe("Onbekend");
  });

  it("keeps known success/progress vocabulary", () => {
    expect(mapDatasetStatus("ready")).toBe("Verwerkt");
    expect(mapDatasetStatus("processed")).toBe("Verwerkt");
    expect(mapDatasetStatus("running")).toBe("Bezig");
    expect(mapDatasetStatus("queued")).toBe("Wachtrij");
    expect(mapDatasetStatus("failed")).toBe("Fout");
    expect(mapDatasetStatus("x", "learned")).toBe("Klaar");
    expect(mapDatasetStatus("x", null, "LEARNED")).toBe("Klaar");
  });

  it("uses muted tone for Onbekend (not success cyan)", () => {
    expect(toneForDatasetStatus("Onbekend")).toBe("muted");
    expect(toneForDatasetStatus("Verwerkt")).toBe("cyan");
  });
});
