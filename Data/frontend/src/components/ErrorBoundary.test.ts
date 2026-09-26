import { describe, expect, it } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

describe("ErrorBoundary", () => {
  it("exposes getDerivedStateFromError", () => {
    const state = ErrorBoundary.getDerivedStateFromError(new Error("boom"));
    expect(state.error?.message).toBe("boom");
  });
});
