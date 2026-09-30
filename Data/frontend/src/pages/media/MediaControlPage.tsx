import { MediaBottomGrid } from "../../components/media/MediaBottomGrid";
import { MediaHero } from "../../components/media/MediaHero";
import { MediaMetrics } from "../../components/media/MediaMetrics";
import { MediaMidGrid } from "../../components/media/MediaMidGrid";
import { MediaOpsGrid } from "../../components/media/MediaOpsGrid";
import { MediaTruthBanner } from "../../components/media/MediaTruthBanner";
import { useMediaOverview } from "../../hooks/useMediaOverview";
import { AppShell } from "../../layouts/AppShell";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/**
 * Media Control → Overzicht (V2).
 * Layout matches the Media Control reference; metrics come from live media/jobs/telemetry.
 */
export function MediaControlPage() {
  const overview = useMediaOverview({ enabled: true });
  const frozen = visualFixtureNow();
  const hardError = overview.errors.mediaStatus && overview.errors.workers && overview.errors.jobs;

  return (
    <AppShell
      variant="v2"
      pageClass="lv-app--media-control"
      v2Title="Media Control / Overzicht"
      v2Subtitle="Beheer, genereer en analyseer alle media content met AI."
      v2Online={overview.online}
      v2Refreshing={overview.refreshing}
      onV2Refresh={() => {
        void overview.refresh();
      }}
      v2StatusRows={overview.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page lv-v2-page--media">
        <MediaHero />
        <MediaTruthBanner />
        <MediaMetrics overview={overview} />

        {hardError ? (
          <p className="lv-v2-media-statusline" role="status" data-truth="unavailable">
            Media status, workers en jobs zijn unavailable — panels tonen empty/UNMEASURED states.
          </p>
        ) : null}

        <MediaOpsGrid overview={overview} />
        <MediaMidGrid overview={overview} />
        <MediaBottomGrid overview={overview} />
      </main>
    </AppShell>
  );
}
