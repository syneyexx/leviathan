import { Link } from "react-router-dom";
import { MediaTruthBanner } from "../../components/media/MediaTruthBanner";
import { Badge, Panel } from "../../components/ui";
import { AppShell } from "../../layouts/AppShell";
import { MEDIA_CONNECTED, MEDIA_STATUS_LABEL, mediaMetricDisplay } from "../../lib/mediaConnection";

const PLATFORMS = [
  { id: "youtube", name: "YouTube", to: "/media/youtube" },
  { id: "tiktok", name: "TikTok", to: "/media/tiktok" },
  { id: "instagram", name: "Instagram", to: "/media/instagram" },
  { id: "facebook", name: "Facebook", to: "/media/facebook" },
  { id: "queue", name: "Publicatiewachtrij", to: "/media/queue" },
] as const;

/** Distributie hub — honest connection posture, deep-links to platform shells. */
export function MediaDistributionPage() {
  return (
    <AppShell
      variant="v2"
      v2Title="Media Control / Distributie"
      v2Subtitle="Platformkoppelingen en publicatiestatus."
      v2Online={MEDIA_CONNECTED ? true : false}
    >
      <main className="lv-v2-page lv-v2-page--media">
        <MediaTruthBanner />
        <Panel
          title="Platformen"
          action={
            <Link to="/media/planning" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm">
              Planning bekijken
            </Link>
          }
        >
          <div className="lv-v2-list">
            {PLATFORMS.map((p) => (
              <Link
                key={p.id}
                to={p.to}
                className="lv-v2-list-row lv-v2-media-dist-row"
                data-truth="not-connected"
              >
                <span className="lv-v2-media-dist-row__name">{p.name}</span>
                <Badge tone="muted">{MEDIA_STATUS_LABEL}</Badge>
                <span data-truth="unavailable">{mediaMetricDisplay()}</span>
              </Link>
            ))}
          </div>
        </Panel>
      </main>
    </AppShell>
  );
}
