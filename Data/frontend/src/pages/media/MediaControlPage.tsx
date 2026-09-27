import { Link } from "react-router-dom";
import { mediaControlCrops } from "../../assets/mediaControlAssets";
import { MediaTruthBanner } from "../../components/media/MediaTruthBanner";
import { PlatformIcon, type PlatformKind } from "../../components/media/MediaWidgets";
import { AppShell } from "../../layouts/AppShell";
import {
  MEDIA_STATUS_LABEL,
  MEDIA_SYSTEM_ITEMS,
  mediaMetricDisplay,
} from "../../lib/mediaConnection";

const PLATFORMS = [
  { id: "youtube" as const, name: "YouTube", metricLabel: "Subscribers", to: "/media/youtube" },
  { id: "tiktok" as const, name: "TikTok", metricLabel: "Followers", to: "/media/tiktok" },
  { id: "instagram" as const, name: "Instagram", metricLabel: "Followers", to: "/media/instagram" },
  { id: "facebook" as const, name: "Facebook", metricLabel: "Followers", to: "/media/facebook" },
] as const;

const NAV_LINKS = [
  { to: "/media/queue", label: "Publication Queue" },
  { to: "/media/viral", label: "Viral Radar" },
  { to: "/media/calendar", label: "Calendar" },
  { to: "/media/library", label: "Library" },
  { to: "/media/personas", label: "Personas" },
] as const;

function SectionTitle({ n, title }: { n: number; title: string }) {
  return (
    <header className="lv-mc-section-head">
      <span className="lv-mc-section-num">{n}.</span>
      <h2>{title}</h2>
    </header>
  );
}

function UnavailableBlock({ label }: { label: string }) {
  return (
    <p className="lv-muted" data-truth="unavailable" role="status" style={{ margin: "0.75rem 0" }}>
      {label}: {mediaMetricDisplay()} — {MEDIA_STATUS_LABEL}
    </p>
  );
}

export function MediaControlPage() {
  return (
    <AppShell
      activeMode="explore"
      modeLabel="Media Mode"
      searchPlaceholder="Search media, content, campaigns, platforms, or ask Leviathan..."
      systemItems={[...MEDIA_SYSTEM_ITEMS]}
      layout="wide"
      pageClass="lv-app--media-control"
    >
      <main className="lv-main lv-mc-main">
        <section className="lv-mc-hero" aria-label="Media Control">
          <div className="lv-mc-hero-media">
            <img src={mediaControlCrops.mediaHeroWide} alt="" width={1600} height={320} />
          </div>
          <div className="lv-mc-hero-shade" />
          <div className="lv-mc-hero-content">
            <p className="lv-mc-hero-kicker">CREATE. SCHEDULE. PUBLISH. SCALE.</p>
            <h1 className="lv-mc-hero-title">MEDIA CONTROL</h1>
            <p className="lv-mc-hero-quote">
              “Ideas compound when they reach the world.” — LEVIATHAN
            </p>
          </div>
        </section>

        <MediaTruthBanner />

        <div className="lv-mc-grid-top">
          <section className="lv-mc-panel">
            <SectionTitle n={1} title="PLATFORM OVERVIEW / CHANNEL GRID" />
            <div className="lv-mc-channel-grid">
              {PLATFORMS.map((p) => (
                <Link key={p.id} to={p.to} className="lv-mc-channel-card" data-truth="not-connected">
                  <div className="lv-mc-channel-head">
                    <PlatformIcon platform={p.id as PlatformKind} />
                    <div>
                      <strong>{p.name}</strong>
                      <span className="lv-mc-connected" data-truth="not-connected">
                        <i /> {MEDIA_STATUS_LABEL}
                      </span>
                    </div>
                  </div>
                  <div className="lv-mc-channel-metric">
                    <span>{mediaMetricDisplay()}</span>
                    <small>{p.metricLabel}</small>
                  </div>
                  <div className="lv-mc-channel-foot">Last Post · {mediaMetricDisplay()}</div>
                </Link>
              ))}
            </div>
          </section>

          <section className="lv-mc-panel">
            <SectionTitle n={2} title="CAMPAIGN ORCHESTRATOR" />
            <UnavailableBlock label="Campaign reach, presets, and launch" />
          </section>
        </div>

        <div className="lv-mc-grid-mid">
          <section className="lv-mc-panel">
            <SectionTitle n={3} title="CONTENT PIPELINE / ACTIVE JOBS" />
            <UnavailableBlock label="Pipeline jobs" />
          </section>
          <section className="lv-mc-panel">
            <SectionTitle n={4} title="PERFORMANCE ANALYTICS" />
            <UnavailableBlock label="Reach, watch time, engagement, CTR" />
          </section>
          <section className="lv-mc-panel">
            <SectionTitle n={5} title="CONTENT CALENDAR" />
            <UnavailableBlock label="Scheduled posts" />
          </section>
        </div>

        <div className="lv-mc-grid-bot">
          <section className="lv-mc-panel">
            <SectionTitle n={6} title="ASSET LIBRARY / MEDIA VAULT" />
            <UnavailableBlock label="Asset inventory" />
            <nav className="lv-mc-orch-actions" aria-label="Media sections" style={{ marginTop: "0.75rem" }}>
              {NAV_LINKS.map((link) => (
                <Link key={link.to} to={link.to} className="lv-mc-btn-ghost">
                  {link.label}
                </Link>
              ))}
            </nav>
          </section>
          <section className="lv-mc-panel">
            <SectionTitle n={7} title="COMMENTS / INBOX / COMMUNITY" />
            <UnavailableBlock label="Inbox" />
          </section>
          <section className="lv-mc-panel">
            <SectionTitle n={8} title="AI MEDIA TOOLS" />
            <UnavailableBlock label="AI media tools" />
          </section>
          <div className="lv-mc-bot-stack">
            <section className="lv-mc-panel">
              <SectionTitle n={9} title="SYSTEM USAGE / WORKFLOW HEALTH" />
              <UnavailableBlock label="Usage meters" />
            </section>
            <section className="lv-mc-panel">
              <SectionTitle n={10} title="LOGS / EVENT TIMELINE" />
              <UnavailableBlock label="Live event timeline" />
            </section>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
