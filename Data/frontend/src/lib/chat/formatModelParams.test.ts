import { describe, expect, it } from "vitest";
import { formatModelParams, formatParamCount } from "./formatModelParams";

describe("formatModelParams", () => {
  it("formats billions", () => {
    expect(formatModelParams(14_000_000_000)).toBe("14B");
    expect(formatModelParams(7_500_000_000)).toBe("7.5B");
  });

  it("formats millions as M (not B)", () => {
    expect(formatModelParams(7_000_000)).toBe("7M");
    expect(formatModelParams(1_500_000)).toBe("1.5M");
  });

  it("formats thousands as K", () => {
    expect(formatModelParams(125_000)).toBe("125K");
    expect(formatModelParams(1_500)).toBe("1.5K");
  });

  it("returns null for unknown / non-positive", () => {
    expect(formatModelParams(null)).toBeNull();
    expect(formatModelParams(undefined)).toBeNull();
    expect(formatModelParams(0)).toBeNull();
    expect(formatModelParams(-1)).toBeNull();
    expect(formatModelParams(Number.NaN)).toBeNull();
  });

  it("aliases formatParamCount", () => {
    expect(formatParamCount(1_000_000_000)).toBe("1B");
  });
});
