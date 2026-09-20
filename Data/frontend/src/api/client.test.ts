import { describe, expect, it } from "vitest";
import { ApiError } from "./client";

describe("ApiError", () => {
  it("preserves HTTP status", () => {
    const error = new ApiError(503, "LLM unavailable");
    expect(error.status).toBe(503);
    expect(error.message).toBe("LLM unavailable");
  });
});
