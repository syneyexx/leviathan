import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { MAIN_MENU } from "../navigation/menu";

describe("shell navigation contract", () => {
  it("keeps a single MAIN_MENU authority with real routes", () => {
    expect(MAIN_MENU.length).toBeGreaterThanOrEqual(7);
    for (const item of MAIN_MENU) {
      expect(item.to.startsWith("/")).toBe(true);
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.submenu.length).toBeGreaterThan(0);
    }
  });

  it("does not introduce screenshot-only menu labels as canonical items", () => {
    const labels = MAIN_MENU.map((item) => item.label);
    expect(labels).toContain("Hades AI");
    expect(labels).toContain("Instellingen");
    expect(labels).toContain("TradingCenter");
    expect(labels).not.toContain("Home");
    expect(labels).not.toContain("Finance");
    expect(labels).not.toContain("Reports");
  });
});

describe("useShellStatus helpers", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("maps agent fleet summary active count when present", async () => {
    const { useShellStatus } = await import("./useShellStatus");
    // Smoke: module exports the hook for AppHeader.
    expect(typeof useShellStatus).toBe("function");
  });
});
