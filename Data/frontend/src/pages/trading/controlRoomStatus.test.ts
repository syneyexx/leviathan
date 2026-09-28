import { describe, expect, it } from "vitest";
import {
  controlRoomStatusLabel,
  controlRoomStatusTone,
  isHonestNonGreen,
} from "./controlRoomStatus";

describe("controlRoomStatus mapping", () => {
  it("keeps UNMEASURED / EMPTY / DEGRADED non-green", () => {
    expect(controlRoomStatusTone("UNMEASURED")).toBe("neutral");
    expect(controlRoomStatusTone("EMPTY")).toBe("neutral");
    expect(controlRoomStatusTone("DEGRADED")).toBe("bad");
    expect(isHonestNonGreen("UNMEASURED")).toBe(true);
    expect(isHonestNonGreen("PASS")).toBe(false);
  });

  it("labels BLOCKED and missing as honest defaults", () => {
    expect(controlRoomStatusLabel(null)).toBe("UNMEASURED");
    expect(controlRoomStatusLabel("blocked")).toBe("BLOCKED");
    expect(controlRoomStatusTone("BLOCKED")).toBe("bad");
  });

  it("only explicit positive tokens are good tone", () => {
    expect(controlRoomStatusTone("PASS")).toBe("good");
    expect(controlRoomStatusTone("OBSERVED")).toBe("good");
    expect(controlRoomStatusTone("CERTIFIED")).toBe("good");
    expect(controlRoomStatusTone("READY")).toBe("good");
    expect(controlRoomStatusTone("ASSUMED")).toBe("neutral");
    expect(controlRoomStatusTone("PARTIAL")).toBe("warn");
    expect(controlRoomStatusTone("IN_PROGRESS")).toBe("warn");
    expect(controlRoomStatusTone("FEATURE_GATED")).toBe("warn");
    expect(controlRoomStatusTone("AVAILABLE")).toBe("info");
    expect(controlRoomStatusTone("BREACH")).toBe("bad");
    expect(isHonestNonGreen("PARTIAL")).toBe(true);
    expect(isHonestNonGreen("UNMEASURED")).toBe(true);
  });
});
