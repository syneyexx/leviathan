import { MediaPlatformShell } from "../../layouts/MediaPlatformShell";

/** Stub — full YouTube Control page lands in a follow-up. */
export function YouTubePage() {
  return (
    <MediaPlatformShell
      activePlatform="youtube"
      searchPlaceholder="Search videos, titles, topics, or anything..."
      createAccent="red"
      promo={{ platform: "youtube", caption: "The message reaches further." }}
    >
      <div className="mp-main-placeholder">YouTube Control — TODO</div>
    </MediaPlatformShell>
  );
}
