import { expect, type Page } from "@playwright/test";
import { CONSOLE_V2_VISUAL_FROZEN_ISO } from "../../src/mocks/consoleV2VisualFixture";

/**
 * Install Screen 1 Console visual fixture + deterministic clock.
 */
export async function installConsoleV2VisualFixture(page: Page): Promise<void> {
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
        "console";
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = frozen;
    },
    { frozen: CONSOLE_V2_VISUAL_FROZEN_ISO },
  );
}

export function assertConsoleFrozenClockContract() {
  expect(CONSOLE_V2_VISUAL_FROZEN_ISO.startsWith("2025-05-25T14:37")).toBe(true);
}
