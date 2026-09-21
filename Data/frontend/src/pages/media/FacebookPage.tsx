import { MediaPlatformShell } from "../../layouts/MediaPlatformShell";

/** Stub — full Facebook Control page lands in a follow-up. */
export function FacebookPage() {
  return (
    <MediaPlatformShell
      activePlatform="facebook"
      searchPlaceholder="Search posts, pages, audiences, or anything..."
      createAccent="blue"
      promo={{ platform: "facebook", caption: "Reach communities at scale." }}
    >
      <div className="mp-main-placeholder">Facebook Control — TODO</div>
    </MediaPlatformShell>
  );
}
