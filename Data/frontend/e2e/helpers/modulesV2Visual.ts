import { expect, type Page } from "@playwright/test";
import { MODULES_V2_VISUAL_FROZEN_ISO } from "../../src/mocks/modulesV2VisualFixture";

/**
 * Install Screen 1 Modules visual fixture + deterministic clock.
 * Seeds timezone to UTC so frozen ISO wall-clock matches reference 14:37:26.
 */
export async function installModulesV2VisualFixture(page: Page): Promise<void> {
  await page.addInitScript(
    ({ frozen }) => {
      try {
        window.localStorage.setItem(
          "lv.ui.preferences.v1",
          JSON.stringify({
            app_display_name: "Leviathan AI Control Center",
            timezone: "UTC",
            locale: "nl",
            theme: "dark_leviathan",
            auto_refresh_seconds: 30,
            sound_notifications: true,
            desktop_notifications: true,
            prefer_local_data: true,
            optional_diagnostics_share: false,
            crash_reports_enabled: true,
          }),
        );
      } catch {
        /* ignore */
      }
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: string; __LV_V2_FROZEN_NOW__?: string }).__LV_V2_VISUAL_FIXTURE__ =
        "modules";
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
    },
    { frozen: MODULES_V2_VISUAL_FROZEN_ISO },
  );
}

export function assertModulesFrozenClockContract() {
  expect(MODULES_V2_VISUAL_FROZEN_ISO.startsWith("2025-05-25T14:37")).toBe(true);
}
