import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const APP = resolve(__dirname, "../../App.tsx");
const PIXEL_INDEX = resolve(__dirname, "../pixel/index.ts");

describe("Models production route", () => {
  it("mounts the real ModelsPage, not the pixel mock", () => {
    const src = readFileSync(APP, "utf8");
    expect(src).toContain('path="/models"');
    expect(src).toContain("<ModelsPage");
    expect(src).not.toContain("ModelsPixelPage");
    expect(src).not.toMatch(/from\s+["'].*mocks\/models-pixel/);
  });

  it("does not export ModelsPixelPage from the pixel barrel", () => {
    const src = readFileSync(PIXEL_INDEX, "utf8");
    expect(src).not.toContain("ModelsPixelPage");
  });
});
