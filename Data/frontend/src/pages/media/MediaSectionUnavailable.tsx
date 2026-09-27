import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { MediaTruthBanner } from "../../components/media/MediaTruthBanner";
import { AppShell } from "../../layouts/AppShell";
import {
  MEDIA_STATUS_LABEL,
  MEDIA_SYSTEM_ITEMS,
  mediaMetricDisplay,
} from "../../lib/mediaConnection";
import { PageHero, Panel } from "./mr-shared";

export function MediaSectionUnavailable({
  title,
  heroImage,
  sectionLabel,
  children,
}: {
  title: string;
  heroImage: string;
  sectionLabel: string;
  children?: ReactNode;
}) {
  return (
    <AppShell
      activeMode="explore"
      modeLabel="Media Mode"
      searchPlaceholder="Search media, content, campaigns, platforms, or ask Leviathan..."
      systemItems={[...MEDIA_SYSTEM_ITEMS]}
      layout="wide"
      pageClass="lv-app--media-research"
    >
      <main className="lv-main lv-mr-main">
        <PageHero image={heroImage} title={title} imageOnly />
        <MediaTruthBanner />
        <section className="lv-mr-kpi-row" aria-label={`${sectionLabel} metrics`}>
          {["Reach", "Engagement", "Scheduled", "Live ops"].map((label) => (
            <article key={label} className="lv-mr-kpi is-cyan" data-truth="unavailable">
              <div className="lbl">{label}</div>
              <div className="val">{mediaMetricDisplay()}</div>
              <div className="sub">
                <span className="lv-mr-muted">{MEDIA_STATUS_LABEL}</span>
              </div>
            </article>
          ))}
        </section>
        <Panel title={sectionLabel}>
          <p className="lv-muted" data-truth="unavailable" role="status">
            {sectionLabel}: {mediaMetricDisplay()} — {MEDIA_STATUS_LABEL}. No fabricated inventory,
            queues, schedules, or engagement figures.
          </p>
          <p style={{ marginTop: "0.75rem" }}>
            <Link to="/media">Back to Media Control</Link>
          </p>
          {children}
        </Panel>
      </main>
    </AppShell>
  );
}
