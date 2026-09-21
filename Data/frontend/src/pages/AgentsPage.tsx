import { mediaControlCrops } from "../assets/mediaControlAssets";
import { MediaPlatformShell } from "../layouts/MediaPlatformShell";

/** Stub — full Agents orchestration page lands in a follow-up. */
export function AgentsPage() {
  return (
    <MediaPlatformShell
      activePlatform="agents"
      searchPlaceholder="Search agents, workflows, tasks, or anything..."
      createAccent="gold"
      sidebarPoster={mediaControlCrops.agentsSidebarPoster}
      sidebarCaption="Autonomous minds. Coordinated will."
      promo={{
        image: mediaControlCrops.agentsPoster,
        caption: "Seven agents. One command.",
      }}
      statusItems={[
        { label: "Fleet Status", value: "Online" },
        { label: "Memory", value: "Synced" },
        { label: "Tools", value: "Ready" },
        { label: "Alerts", value: "None" },
      ]}
    >
      <div className="mp-main-placeholder">Agents — TODO</div>
    </MediaPlatformShell>
  );
}
