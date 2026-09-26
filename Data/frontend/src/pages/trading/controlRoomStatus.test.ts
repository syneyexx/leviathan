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

  it("only PASS/MEASURED/OBSERVED are good tone", () => {
    expect(controlRoomStatusTone("PASS")).toBe("good");
    expect(controlRoomStatusTone("OBSERVED")).toBe("good");
    expect(controlRoomStatusTone("ASSUMED")).toBe("neutral");
  });
});
