import { describe, expect, it } from "vitest";
import {
  classifyMediaCapability,
  isMediaCapability,
  mediaKindFromJob,
  rangeToMs,
} from "./mediaClassify";

describe("mediaClassify", () => {
  it("detects media capabilities", () => {
    expect(isMediaCapability("media.image_generate")).toBe(true);
    expect(isMediaCapability("agents.run")).toBe(false);
  });

  it("classifies image/video/audio caps", () => {
    expect(classifyMediaCapability("media.image_generate")).toBe("image");
    expect(classifyMediaCapability("media.video.process")).toBe("video");
    expect(classifyMediaCapability("media.audio.process")).toBe("audio");
  });

  it("falls back to filename for kind", () => {
    expect(mediaKindFromJob({ path: "/tmp/clip.mp4" })).toBe("video");
    expect(mediaKindFromJob({ path: "voice.wav" })).toBe("audio");
  });

  it("maps types ranges to ms windows", () => {
    expect(rangeToMs("24h")).toBe(24 * 60 * 60 * 1000);
    expect(rangeToMs("7d")).toBe(7 * 24 * 60 * 60 * 1000);
  });
});
