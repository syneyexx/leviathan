import { describe, expect, it } from "vitest";
import { bytesToGb } from "../../hooks/useModelsWorkspace";

describe("models VRAM reserve truthiness", () => {
  it("treats 0 bytes as real 0 GB (not falsy fallback)", () => {
    expect(bytesToGb(0)).toBe(0);
    const prev = 3.5;
    const next = bytesToGb(0) ?? prev;
    expect(next).toBe(0);
  });

  it("falls back only when policy field is missing", () => {
    const prev = 2;
    expect(bytesToGb(undefined) ?? prev).toBe(2);
    expect(bytesToGb(null) ?? prev).toBe(2);
  });
});
