import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { BrandMark } from "../BrandMark";
import { MediaTruthBanner } from "./MediaTruthBanner";
import { MetricCard, Panel, PlatformIcon, type PlatformKind } from "./MediaWidgets";
import { AppShell } from "../../layouts/AppShell";
import {
  MEDIA_STATUS_LABEL,
  MEDIA_SYSTEM_ITEMS,
  MEDIA_UNAVAILABLE,
  mediaMetricDisplay,
} from "../../lib/mediaConnection";

const ACCENT: Record<PlatformKind, string> = {
  youtube: "red",
  tiktok: "cyan",
  instagram: "gold",
  facebook: "blue",
};

export function PlatformUnavailablePage({
  platform,
  title,
  heroImage,
  handle,
  children,
}: {
  platform: PlatformKind;
  title: string;
  heroImage: string;
  handle: string;
  children?: ReactNode;
}) {
  return (
    <AppShell
      activeMode="explore"
      modeLabel="Media Mode"
      searchPlaceholder="Search videos, titles, topics, or ask Leviathan..."
      systemItems={[...MEDIA_SYSTEM_ITEMS]}
      layout="wide"
      pageClass="lv-app--media-platform"
    >
      <main className="lv-main mp-main-in-shell" data-accent={ACCENT[platform]}>
        <div className="mp-page">
          <section className="mp-hero">
            <div className="mp-hero-media">
              <img src={heroImage} alt="" />
            </div>
            <div className="mp-hero-shade" />
            <div className="mp-hero-content">
              <div className="mp-hero-icon">
                <PlatformIcon platform={platform} />
              </div>
              <div className="mp-hero-copy">
                <h1 className="mp-hero-title">{title}</h1>
                <div className="mp-hero-flow">Ideas → Content → Audiences → Impact</div>
              </div>
            </div>
          </section>

          <MediaTruthBanner />

          <section className="mp-profile" data-truth="not-connected">
            <div className="mp-profile-avatar" aria-hidden="true">
              <BrandMark id={`${platform}-profile`} />
            </div>
            <div className="mp-profile-meta">
              <div className="mp-profile-name">LEVIATHAN</div>
              <div className="mp-profile-handle">
                {handle} · {mediaMetricDisplay()}
              </div>
              <div className="mp-profile-bio">
                Platform account {MEDIA_STATUS_LABEL.toLowerCase()} — no live channel state.
              </div>
            </div>
          </section>

          <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
            {["Followers / Subscribers", "Views", "Engagement", "Reach"].map((label) => (
              <MetricCard key={label} label={label} value={mediaMetricDisplay()} />
            ))}
          </div>

          <Panel title="Live platform state">
            <p className="lv-muted" data-truth="unavailable" role="status">
              Uploads, schedules, comments, and analytics are {MEDIA_UNAVAILABLE} until a provider is
              connected.
            </p>
            <p style={{ marginTop: "0.75rem" }}>
              <Link to="/media" className="mp-btn">
                Back to Media Control
              </Link>
            </p>
            {children}
          </Panel>
        </div>
      </main>
    </AppShell>
  );
}
