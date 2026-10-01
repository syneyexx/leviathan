import { describe, expect, it } from "vitest";
import {
  applySettledResource,
  emptyResource,
  resourceAvailabilityLabel,
  resourceFailure,
  resourceLoading,
  resourceSuccess,
} from "./resourceState";

describe("resourceState (R-013)", () => {
  it("starts unmeasured — empty is not a successful collection", () => {
    const state = emptyResource<string[]>([]);
    expect(state.data).toEqual([]);
    expect(state.measured).toBe(false);
    expect(state.stale).toBe(false);
    expect(resourceAvailabilityLabel(state)).toBe("UNKNOWN");
  });

  it("marks measured on success including empty arrays", () => {
    const state = resourceSuccess<string[]>([]);
    expect(state.measured).toBe(true);
    expect(state.stale).toBe(false);
    expect(state.error).toBeNull();
    expect(resourceAvailabilityLabel(state)).toBe("");
  });

  it("on initial failure keeps unmeasured and surfaces UNAVAILABLE", () => {
    const prev = emptyResource<string[]>([]);
    const next = resourceFailure(prev, "network down");
    expect(next.data).toEqual([]);
    expect(next.measured).toBe(false);
    expect(next.stale).toBe(false);
    expect(next.error).toBe("network down");
    expect(resourceAvailabilityLabel(next)).toBe("UNAVAILABLE");
  });

  it("on refresh failure retains last known data and marks stale", () => {
    const prev = resourceSuccess(["a", "b"]);
    const loading = resourceLoading(prev);
    expect(loading.data).toEqual(["a", "b"]);
    expect(loading.loading).toBe(true);
    const failed = resourceFailure(loading, "timeout");
    expect(failed.data).toEqual(["a", "b"]);
    expect(failed.measured).toBe(true);
    expect(failed.stale).toBe(true);
    expect(failed.error).toBe("timeout");
    expect(resourceAvailabilityLabel(failed)).toBe("STALE");
  });

  it("applySettledResource never promotes rejected to empty success", () => {
    const prev = emptyResource<{ sources: string[] }>({ sources: [] });
    const rejected = applySettledResource(
      prev,
      { status: "rejected", reason: new Error("boom") },
      "sources unavailable",
    );
    expect(rejected.measured).toBe(false);
    expect(rejected.data.sources).toEqual([]);
    expect(rejected.error).toBe("boom");

    const fulfilled = applySettledResource(
      rejected,
      { status: "fulfilled", value: { sources: ["x"] } },
      "sources unavailable",
    );
    expect(fulfilled.measured).toBe(true);
    expect(fulfilled.data.sources).toEqual(["x"]);
    expect(fulfilled.stale).toBe(false);
  });
});
