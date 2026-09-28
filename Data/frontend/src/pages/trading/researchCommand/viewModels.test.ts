import { describe, expect, it } from "vitest";
import { isExecutionSafe, measuredText, modeLabel, moneyText, safetyClass } from "./viewModels";

describe("research command truth formatters", () => {
  it("does not render an unmeasured zero as money", () => {
    expect(moneyText({ value: "0", measurement: "UNMEASURED" }, "USD")).toBe("UNMEASURED");
    expect(moneyText({ value: null, measurement: "UNMEASURED" }, "USD")).toBe("UNMEASURED");
  });

  it("renders a measured zero as a real flat value", () => {
    expect(moneyText({ value: "0", measurement: "MEASURED" }, "USD")).toContain("0");
  });

  it("labels agent estimates separately from measured validation", () => {
    expect(measuredText({ value: 0.42, measurement: "AGENT_ESTIMATE" })).toContain("agent estimate");
    expect(measuredText({ value: null, measurement: "UNMEASURED" })).toBe("UNMEASURED");
    expect(measuredText({ value: null, measurement: "EMPTY" })).toBe("EMPTY");
  });

  it("does not treat missing safety as SAFE", () => {
    expect(isExecutionSafe(undefined)).toBe(false);
    expect(isExecutionSafe("NOT_SAFE")).toBe(false);
    expect(isExecutionSafe("UNMEASURED")).toBe(false);
    expect(isExecutionSafe("SAFE")).toBe(true);
    expect(safetyClass("NOT_SAFE")).toBe("is-bad");
    expect(safetyClass(null)).not.toBe("is-safe");
  });

  it("names paper mode only from the paper binding", () => {
    expect(modeLabel("PAPER")).toBe("PAPER MODE");
    expect(modeLabel("NO_PAPER_WALLET")).toBe("NO PAPER WALLET");
    expect(modeLabel(null)).toBe("UNMEASURED");
  });
});
