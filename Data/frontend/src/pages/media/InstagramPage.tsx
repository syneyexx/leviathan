import { MediaPlatformShell } from "../../layouts/MediaPlatformShell";

/** Stub — full Instagram Control page lands in a follow-up. */
export function InstagramPage() {
  return (
    <MediaPlatformShell
      activePlatform="instagram"
      searchPlaceholder="Search reels, posts, stories, or anything..."
      createAccent="gold"
      promo={{ platform: "instagram", caption: "Frames that hold attention." }}
    >
      <div className="mp-main-placeholder">Instagram Control — TODO</div>
    </MediaPlatformShell>
  );
}
