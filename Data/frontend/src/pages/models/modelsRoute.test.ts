import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const APP = resolve(__dirname, "../App.tsx");

describe("Models production route", () => {
  it("mounts the real ModelsPage, not the pixel mock", () => {
    const src = readFileSync(APP, "utf8");
    expect(src).toContain('path="/models"');
    expect(src).toContain("<ModelsPage");
    expect(src).not.toContain("ModelsPixelPage");
    expect(src).not.toMatch(/from\s+["'].*mocks\/models-pixel/);
  });
});
