import { MediaPlatformShell } from "../../layouts/MediaPlatformShell";

/** Stub — full Media Control dashboard lands in a follow-up. */
export function MediaControlPage() {
  return (
    <MediaPlatformShell
      activePlatform="media"
      searchPlaceholder="Search media, content, campaigns, platforms, or ask Leviathan..."
      createAccent="gold"
      promo={{ caption: "Create. Schedule. Publish. Scale." }}
      sidebarCaption="Discipline creates freedom."
    >
      <div className="mp-main-placeholder">Media Control — TODO</div>
    </MediaPlatformShell>
  );
}
