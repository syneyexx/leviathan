import { BrandMark } from "../../components/BrandMark";
import {
  DonutChart,
  GrowthDelta,
  LineChart,
  MetricCard,
  Panel,
  PlatformIcon,
  VerifiedBadge,
} from "../../components/media/MediaWidgets";
import { mediaControlCrops, platformTiles } from "../../assets/mediaControlAssets";
import { MediaPlatformShell } from "../../layouts/MediaPlatformShell";
import { useAppToast } from "../../state/useAppToast";
import { useState } from "react";

const TILES = platformTiles.facebook;
const FOLLOWERS = [1.05, 1.08, 1.1, 1.12, 1.14, 1.16, 1.18, 1.2, 1.21, 1.22, 1.23, 1.24];
const TABS = ["Followers", "Reach", "Engagement", "Page Views"] as const;

const POSTS = [
  { title: "A Higher Humanity Is Possible", when: "2h ago", likes: "18.2K", comments: "642", shares: "1.1K", growth: "+24%", thumb: TILES[0] },
  { title: "Community Builds Worlds", when: "1d ago", likes: "12.4K", comments: "418", shares: "860", growth: "+18%", thumb: TILES[1] },
  { title: "Discipline Series Launch", when: "2d ago", likes: "9.8K", comments: "302", shares: "640", growth: "+14%", thumb: TILES[2] },
  { title: "Conversations That Scale", when: "3d ago", likes: "7.1K", comments: "214", shares: "420", growth: "+11%", thumb: TILES[3] },
] as const;

const CALENDAR = [
  { date: "Oct 28", title: "Page Live Q&A", meta: "Video Post · 10:00 AM", thumb: TILES[0] },
  { date: "Oct 29", title: "Community Spotlight", meta: "Image Post · 2:00 PM", thumb: TILES[1] },
  { date: "Oct 31", title: "Campaign Teaser", meta: "Reel · 6:00 PM", thumb: TILES[2] },
  { date: "Nov 1", title: "Event Reminder", meta: "Event · 9:00 AM", thumb: TILES[3] },
  { date: "Nov 2", title: "Impact Report", meta: "Link Post · 12:00 PM", thumb: TILES[4] },
] as const;

const TOP = [
  { title: "Higher Minds Keynote", type: "Video", reach: "1.8M", eng: "142K", er: "7.9%", thumb: TILES[0] },
  { title: "Leviathan Manifesto", type: "Image", reach: "1.2M", eng: "98K", er: "8.1%", thumb: TILES[1] },
  { title: "Community Roundtable", type: "Reel", reach: "960K", eng: "76K", er: "7.4%", thumb: TILES[2] },
  { title: "Discipline Series #3", type: "Video", reach: "840K", eng: "64K", er: "7.1%", thumb: TILES[3] },
  { title: "Ideas Compound", type: "Image", reach: "710K", eng: "52K", er: "6.8%", thumb: TILES[4] },
] as const;

const ADS = [
  { name: "Higher Minds", spend: "$4,280", reach: "820K", trend: "+18%" },
  { name: "Leviathan Community", spend: "$2,640", reach: "510K", trend: "+12%" },
  { name: "Discipline Series", spend: "$1,920", reach: "386K", trend: "+9%" },
] as const;

const AGES = [
  { label: "18-24", pct: 18 },
  { label: "25-34", pct: 36 },
  { label: "35-44", pct: 28 },
  { label: "45+", pct: 18 },
] as const;

export function FacebookPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Followers");

  return (
    <MediaPlatformShell
      activePlatform="facebook"
      searchPlaceholder="Search posts, comments, campaigns, or anything..."
      createAccent="blue"
      promo={{ platform: "facebook", caption: "Real people. Bigger possibilities." }}
      statusItems={[
        { label: "Page Status", value: "Healthy" },
        { label: "Monetization", value: "Enabled" },
        { label: "Page Quality", value: "Good" },
        { label: "Community Guidelines", value: "No Issues" },
      ]}
    >
      <div className="mp-page">
        <section className="mp-hero">
          <div className="mp-hero-media">
            <img src={mediaControlCrops.facebookHero} alt="" />
          </div>
          <div className="mp-hero-shade" />
          <div className="mp-hero-content">
            <div className="mp-hero-icon">
              <PlatformIcon platform="facebook" />
            </div>
            <div className="mp-hero-copy">
              <h1 className="mp-hero-title">Facebook Control</h1>
              <div className="mp-hero-flow">Community — Conversations — Campaigns — Impact</div>
            </div>
            <div className="mp-hero-quotes">
              <span>People build stronger worlds. — Leviathan</span>
            </div>
          </div>
        </section>

        <section className="mp-profile">
          <div className="mp-profile-avatar">
            <BrandMark id="fb-profile" />
          </div>
          <div className="mp-profile-meta">
            <div className="mp-profile-name">
              LEVIATHAN <VerifiedBadge />
            </div>
            <div className="mp-profile-handle">@LeviathanOfficial · Public Figure · Higher Humanity</div>
          </div>
          <div className="mp-profile-actions">
            <button className="mp-btn" type="button" onClick={() => toast("View Page")}>
              View Page
            </button>
            <button className="mp-btn" type="button" onClick={() => toast("Page Settings")}>
              Page Settings
            </button>
          </div>
        </section>

        <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))" }}>
          <MetricCard label="Page Followers" value="1.24M" absolute="+18.3K" percent="+1.5%" sparkline={FOLLOWERS} sparkStroke="#1877f2" />
          <MetricCard label="Post Reach" value="4.82M" absolute="+612K" percent="+14.5%" sparkline={[3, 3.4, 3.8, 4, 4.2, 4.4, 4.6, 4.82]} sparkStroke="#1877f2" />
          <MetricCard label="Post Engagement" value="386.7K" absolute="+28.4K" percent="+7.9%" sparkline={[250, 280, 300, 320, 340, 360, 370, 386]} sparkStroke="#1877f2" />
          <MetricCard label="Video Views" value="2.1M" absolute="+420K" percent="+25.0%" sparkline={[1.2, 1.4, 1.5, 1.6, 1.7, 1.85, 2.0, 2.1]} sparkStroke="#1877f2" />
          <MetricCard label="Link Clicks" value="124.6K" absolute="+11.2K" percent="+9.9%" sparkline={[80, 90, 95, 100, 108, 114, 120, 124]} sparkStroke="#1877f2" />
        </div>

        <div className="mp-grid-3">
          <Panel
            title="Audience Growth"
            action={
              <div className="mp-tabs">
                {TABS.map((t) => (
                  <button key={t} type="button" className={`mp-tab${tab === t ? " is-active" : ""}`} onClick={() => setTab(t)}>
                    {t}
                  </button>
                ))}
              </div>
            }
          >
            <div className="mp-chart-wrap">
              <LineChart series={[{ id: "f", color: "#1877f2", values: FOLLOWERS }]} labels={["Oct 1", "Oct 8", "Oct 15", "Oct 22", "Oct 28"]} height={180} />
              <div className="mp-side-stats">
                {[
                  ["Total Followers", "1.24M", "+1.5%"],
                  ["New Followers", "18.3K", "+8.2%"],
                  ["Post Reach", "4.82M", "+14.5%"],
                  ["Engagements", "386.7K", "+7.9%"],
                ].map(([l, v, p]) => (
                  <div key={l} className="mp-side-stat">
                    <span>{l}</span>
                    <strong>{v}</strong>
                    <GrowthDelta percent={p} />
                  </div>
                ))}
              </div>
            </div>
          </Panel>

          <Panel title="Latest Posts">
            <div className="mp-list">
              {POSTS.map((p) => (
                <div key={p.title} className="mp-list-row">
                  <img className="mp-thumb square" src={p.thumb} alt="" />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{p.title}</div>
                    <div className="mp-list-meta">
                      {p.when} · ♥ {p.likes} · 💬 {p.comments} · ↗ {p.shares}
                    </div>
                  </div>
                  <span className="mp-badge is-green">{p.growth}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Content Calendar">
            <div className="mp-list">
              {CALENDAR.map((c) => (
                <div key={c.date} className="mp-list-row">
                  <div style={{ width: 52, fontSize: 11, color: "var(--mp-gold)" }}>{c.date}</div>
                  <img className="mp-thumb" src={c.thumb} alt="" />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{c.title}</div>
                    <div className="mp-list-meta">{c.meta}</div>
                  </div>
                  <span className="mp-badge is-green">Scheduled</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-4">
          <div style={{ gridColumn: "span 2" }}>
            <Panel title="Top Performing Content">
              <table className="mp-table">
                <thead>
                  <tr>
                    <th>Post</th>
                    <th>Type</th>
                    <th>Reach</th>
                    <th>Engagement</th>
                    <th>ER</th>
                  </tr>
                </thead>
                <tbody>
                  {TOP.map((r) => (
                    <tr key={r.title}>
                      <td>
                        <div className="mp-list-row">
                          <img className="mp-thumb" src={r.thumb} alt="" />
                          <span className="mp-list-title">{r.title}</span>
                        </div>
                      </td>
                      <td>{r.type}</td>
                      <td>{r.reach}</td>
                      <td>{r.eng}</td>
                      <td>{r.er}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>

          <Panel title="Ad Campaigns">
            <div className="mp-list">
              {ADS.map((a) => (
                <div key={a.name} className="mp-list-row">
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{a.name}</div>
                    <div className="mp-list-meta">
                      Spend {a.spend} · Reach {a.reach}
                    </div>
                  </div>
                  <GrowthDelta percent={a.trend} />
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Audience Demographics">
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <DonutChart value={58} color="#1877f2" label="58%" size={84} />
              <div className="mp-stack">
                <div className="mp-list-meta">Men 58%</div>
                <div className="mp-list-meta">Women 38%</div>
                <div className="mp-list-meta">Other 4%</div>
                <div className="mp-list-title">1.24M total</div>
              </div>
            </div>
            <div className="mp-list-title" style={{ margin: "10px 0 6px" }}>
              Top Age Groups
            </div>
            {AGES.map((a) => (
              <div key={a.label} className="mp-bar-row">
                <span>{a.label}</span>
                <div className="mp-bar-track">
                  <div className="mp-bar-fill" style={{ width: `${a.pct * 2.2}%`, background: "#1877f2" }} />
                </div>
                <span>{a.pct}%</span>
              </div>
            ))}
          </Panel>
        </div>

        <div className="mp-grid-2">
          <Panel title="Community Sentiment">
            <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
              <DonutChart value={92} color="#20dc8c" label="92%" size={100} />
              <div className="mp-stack">
                <div className="mp-list-title">92% Positive</div>
                <div className="mp-list-meta">Neutral 6%</div>
                <div className="mp-list-meta">Negative 2%</div>
              </div>
            </div>
          </Panel>
          <Panel title="Inbox & Comments">
            <div className="mp-list">
              {[
                ["128", "Unread Messages"],
                ["24", "Comments to Review"],
                ["7", "Mentions"],
              ].map(([n, l]) => (
                <div key={l} className="mp-list-row">
                  <strong style={{ fontSize: 22, color: "var(--mp-gold-bright)", width: 56 }}>{n}</strong>
                  <span className="mp-list-title">{l}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-action-bar">
          <span className="mp-footer-quote" style={{ marginLeft: 0 }}>
            Community turns vision into reality
          </span>
          {["Create Post", "Create Reel", "Go Live", "Create Event", "Create Ad", "Boost Post"].map((label) => (
            <button key={label} className="mp-btn" type="button" onClick={() => toast(label)}>
              {label}
            </button>
          ))}
          <span className="mp-footer-quote">Ideas today · A brighter tomorrow</span>
        </div>
      </div>
    </MediaPlatformShell>
  );
}
