import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

describe("TrainingPixelPage product truth", () => {
  const src = readFileSync(join(here, "TrainingPixelPage.tsx"), "utf8");

  it("FRONTEND-001: does not render TRAINING_DATASET_PREVIEW as live sample text", () => {
    expect(src).not.toMatch(/TRAINING_DATASET_PREVIEW/);
    expect(src).toMatch(/Dataset preview UNAVAILABLE/);
    expect(src).toMatch(/data-truth="unavailable"/);
  });

  it("FRONTEND-002: does not render TRAINING_SAFETY_TOGGLES fixture as live config", () => {
    expect(src).not.toMatch(/TRAINING_SAFETY_TOGGLES/);
    expect(src).toMatch(/Static fixture safety toggles/);
    expect(src).toMatch(/Gradient checkpointing/);
    expect(src).toMatch(/Load in 4-bit/);
  });
});
