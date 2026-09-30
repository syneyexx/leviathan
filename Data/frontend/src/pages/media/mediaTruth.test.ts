import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  MEDIA_CONNECTED,
  MEDIA_STATUS_LABEL,
  MEDIA_SYSTEM_ITEMS,
  MEDIA_UNAVAILABLE,
  mediaMetricDisplay,
} from "../../lib/mediaConnection";

const here = dirname(fileURLToPath(import.meta.url));

function read(rel: string): string {
  return readFileSync(join(here, rel), "utf8");
}

describe("media connection truth helpers", () => {
  it("reports media as not connected with UNAVAILABLE metrics", () => {
    expect(MEDIA_CONNECTED).toBe(false);
    expect(MEDIA_STATUS_LABEL).toBe("NOT CONNECTED");
    expect(MEDIA_UNAVAILABLE).toBe("UNAVAILABLE");
    expect(mediaMetricDisplay("1.32M")).toBe("UNAVAILABLE");
    expect(MEDIA_SYSTEM_ITEMS.join(" ")).toMatch(/NOT CONNECTED/);
  });
});

describe("Media Control fabricated metrics (FRONTEND-004)", () => {
  const src = read("MediaControlPage.tsx");
  const mid = readFileSync(
    join(here, "../../components/media/MediaMidGrid.tsx"),
    "utf8",
  );

  it("does not present fabricated subscriber / reach KPIs as live", () => {
    expect(src).not.toMatch(/1\.32M|1\.80M|8\.42M|142\.6K/);
    expect(src).not.toMatch(/All Systems Nominal/);
    expect(src).not.toMatch(/MEMORY ONLINE/);
    expect(src).toMatch(/MediaTruthBanner|NOT CONNECTED|UNAVAILABLE/);
    expect(`${src}\n${mid}`).toMatch(/data-truth="not-connected"|data-truth="unavailable"/);
  });
});

describe("Media platform pages fabricated state (FRONTEND-005)", () => {
  const pages = [
    "YouTubePage.tsx",
    "TikTokPage.tsx",
    "InstagramPage.tsx",
    "FacebookPage.tsx",
    "MediaQueuePage.tsx",
    "MediaViralPage.tsx",
    "MediaCalendarPage.tsx",
    "MediaLibraryPage.tsx",
    "MediaPersonasPage.tsx",
  ];

  it("routes platform/section pages through honest unavailable shells", () => {
    for (const page of pages) {
      const src = read(page);
      expect(src).not.toMatch(/MEMORY ONLINE|SYSTEMS OPERATIONAL/);
      expect(src).not.toMatch(/1\.32M subscribers|1\.80M|2\.4M views/);
      expect(src).toMatch(/PlatformUnavailablePage|MediaSectionUnavailable/);
    }
  });

  it("PlatformUnavailablePage banners NOT CONNECTED and UNAVAILABLE metrics", () => {
    const shared = readFileSync(
      join(here, "../../components/media/PlatformUnavailablePage.tsx"),
      "utf8",
    );
    expect(shared).toMatch(/MediaTruthBanner/);
    expect(shared).toMatch(/mediaMetricDisplay|MEDIA_UNAVAILABLE/);
    expect(shared).toMatch(/data-truth="not-connected"/);
  });
});
