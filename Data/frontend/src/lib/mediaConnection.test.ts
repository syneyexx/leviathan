import { describe, expect, it } from "vitest";
import {
  MEDIA_CONNECTED,
  MEDIA_UNAVAILABLE,
  mediaMetricDisplay,
} from "./mediaConnection";

describe("mediaMetricDisplay", () => {
  it("returns UNAVAILABLE when media is not connected", () => {
    expect(MEDIA_CONNECTED).toBe(false);
    expect(mediaMetricDisplay()).toBe(MEDIA_UNAVAILABLE);
    expect(mediaMetricDisplay("1.32M")).toBe("UNAVAILABLE");
    expect(mediaMetricDisplay("1.32M")).toBe(MEDIA_UNAVAILABLE);
  });
});
