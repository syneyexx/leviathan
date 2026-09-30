import { expect, test } from "@playwright/test";
import { MODULES_V2_VISUAL_FROZEN_ISO } from "../src/mocks/modulesV2VisualFixture";

test.describe("Modules V2 helpers", () => {
  test("frozen time matches Screen 1 clock date", () => {
    expect(MODULES_V2_VISUAL_FROZEN_ISO.startsWith("2025-05-25T14:37")).toBe(true);
  });
});
