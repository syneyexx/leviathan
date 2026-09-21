import { MediaPlatformShell } from "../../layouts/MediaPlatformShell";

/** Stub — full TikTok Control page lands in a follow-up. */
export function TikTokPage() {
  return (
    <MediaPlatformShell
      activePlatform="tiktok"
      searchPlaceholder="Search clips, sounds, trends, or anything..."
      createAccent="red"
      promo={{ platform: "tiktok", caption: "Ride the next wave." }}
    >
      <div className="mp-main-placeholder">TikTok Control — TODO</div>
    </MediaPlatformShell>
  );
}
