import { describe, expect, it } from "vitest";
import { mapDatasetStatus, toneForDatasetStatus } from "./datasetStatus";

describe("mapDatasetStatus", () => {
  it("maps unknown/empty to Onbekend instead of Verwerkt", () => {
    expect(mapDatasetStatus("")).toBe("Onbekend");
    expect(mapDatasetStatus("unknown")).toBe("Onbekend");
    expect(mapDatasetStatus("UNMEASURED")).toBe("Onbekend");
    expect(mapDatasetStatus("weird-status")).toBe("Onbekend");
  });

  it("maps ready to Verwerkt and raw to Wachtrij", () => {
    expect(mapDatasetStatus("ready")).toBe("Verwerkt");
    expect(mapDatasetStatus("raw")).toBe("Wachtrij");
  });

  it("tones Onbekend as muted", () => {
    expect(toneForDatasetStatus("Onbekend")).toBe("muted");
  });
});
