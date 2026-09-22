import { useState } from "react";
import { BrandMark } from "../../components/BrandMark";
import {
  GrowthDelta,
  LineChart,
  MetricCard,
  Panel,
  PlatformIcon,
  ProgressBar,
  VerifiedBadge,
} from "../../components/media/MediaWidgets";
import { mediaControlCrops, platformTiles } from "../../assets/mediaControlAssets";
import { SubMenu } from "../../components/SubMenu";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";

const VIEW_SERIES = [1.1, 1.25, 1.4, 1.55, 1.8, 1.7, 2.0, 2.15, 2.05, 2.25, 2.35, 2.4];
const TILES = platformTiles.youtube;

const UPLOADS = [
  { title: "AI Will Change Everything", views: "2.4M views", when: "2 days ago", growth: "+42%", thumb: TILES[0] },
  { title: "The Leviathan Mindset", views: "1.1M views", when: "4 days ago", growth: "+28%", thumb: TILES[1] },
  { title: "Discipline Builds Freedom", views: "864K views", when: "6 days ago", growth: "+19%", thumb: TILES[2] },
  { title: "Stories Shape Civilization", views: "612K views", when: "1 week ago", growth: "+14%", thumb: TILES[3] },
] as const;

const SCHEDULE = [
  { title: "The Future of Human Potential", when: "Tomorrow · 18:00", status: "Scheduled", thumb: TILES[4] },
  { title: "Neural Interfaces Explained", when: "Oct 24 · 14:00", status: "Scheduled", thumb: TILES[5] },
  { title: "Q&A — Ask Leviathan", when: "Oct 26 · 20:00", status: "Live", thumb: TILES[1] },
  { title: "Stories That Shape Civilization", when: "Oct 29 · 16:30", status: "Scheduled", thumb: TILES[2] },
] as const;

const TOP = [
  { rank: 1, title: "AI Will Change Everything", views: "8.2M", watch: "412K hrs", avg: "68%", thumb: TILES[0] },
  { rank: 2, title: "The Leviathan Mindset", views: "5.4M", watch: "286K hrs", avg: "61%", thumb: TILES[1] },
  { rank: 3, title: "Discipline Builds Freedom", views: "3.9M", watch: "198K hrs", avg: "57%", thumb: TILES[2] },
  { rank: 4, title: "A Higher Humanity", views: "2.7M", watch: "142K hrs", avg: "54%", thumb: TILES[3] },
  { rank: 5, title: "Ideas Today", views: "1.8M", watch: "96K hrs", avg: "51%", thumb: TILES[4] },
] as const;

const COMMENTS = [
  { user: "nova_prime", time: "2m", text: "This reframed how I think about attention.", avatar: mediaControlCrops.youtubeThumb1 },
  { user: "signalcraft", time: "14m", text: "When is the next live session?", avatar: mediaControlCrops.youtubeThumb2 },
  { user: "orbitmind", time: "1h", text: "Thumbnail A is converting insane.", avatar: TILES[3] },
  { user: "aether_lab", time: "2h", text: "Script Generator saved me hours.", avatar: TILES[4] },
] as const;

const PERF_TABS = ["Views", "Watch Time", "Subscribers", "Revenue"] as const;

export function YouTubePage() {
  const toast = useAppToast();
  const [perfTab, setPerfTab] = useState<(typeof PERF_TABS)[number]>("Views");

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Media Mode"
      searchPlaceholder="Search videos, titles, topics, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--media-platform"
    >
      <main className="lv-main mp-main-in-shell" data-accent="red">
      <div className="mp-page">
        <section className="mp-hero">
          <div className="mp-hero-media">
            <img src={mediaControlCrops.youtubeHero} alt="" />
          </div>
          <div className="mp-hero-shade" />
          <div className="mp-hero-content">
            <div className="mp-hero-icon">
              <PlatformIcon platform="youtube" />
            </div>
            <div className="mp-hero-copy">
              <h1 className="mp-hero-title">YouTube Control</h1>
              <div className="mp-hero-flow">Ideas → Content → Audiences → Impact</div>
            </div>
            <div className="mp-hero-quotes">
              <span>Stories shape civilization. — Leviathan</span>
              <span>More than content. A brighter tomorrow.</span>
            </div>
          </div>
        </section>

        <SubMenu />

        <section className="mp-profile">
          <div className="mp-profile-avatar" aria-hidden="true">
            <BrandMark id="yt-profile" />
          </div>
          <div className="mp-profile-meta">
            <div className="mp-profile-name">
              LEVIATHAN <VerifiedBadge />
            </div>
            <div className="mp-profile-handle">@LeviathanOfficial · 1.32M subscribers</div>
            <div className="mp-profile-bio">A higher humanity through greater minds.</div>
          </div>
          <div className="mp-profile-actions">
            <button className="mp-btn" type="button" onClick={() => toast("View Channel")}>
              View Channel
              <svg viewBox="0 0 24 24">
                <path d="M14 5h5v5M19 5l-9 9M10 5H5v14h14v-5" />
              </svg>
            </button>
            <button className="mp-btn" type="button" onClick={() => toast("Channel Settings")}>
              Channel Settings
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2" />
              </svg>
            </button>
          </div>
        </section>

        <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
          <MetricCard
            label="Subscribers"
            value="1.32M"
            absolute="+12.4K"
            percent="+1.0%"
            sparkline={[40, 42, 45, 48, 52, 55, 58, 62]}
            sparkStroke="#20dc8c"
            icon={
              <svg viewBox="0 0 24 24">
                <circle cx="9" cy="9" r="3" />
                <circle cx="16" cy="10" r="2.4" />
                <path d="M4 18c1.5-3 4-4.5 5-4.5S12.5 15 14 18" />
              </svg>
            }
          />
          <MetricCard
            label="Total Views"
            value="184.7M"
            absolute="+3.2M"
            percent="+1.8%"
            sparkline={[30, 38, 35, 48, 44, 58, 52, 66]}
            sparkStroke="#e53935"
            icon={
              <svg viewBox="0 0 24 24">
                <path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12z" />
                <circle cx="12" cy="12" r="2.5" />
              </svg>
            }
          />
          <MetricCard
            label="Watch Time (hours)"
            value="12.4M"
            absolute="+321K"
            percent="+2.6%"
            sparkline={[20, 35, 28, 48, 40, 55, 60, 58]}
            sparkStroke="#e53935"
            icon={
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="8" />
                <path d="M12 8v5l3 2" />
              </svg>
            }
          />
          <MetricCard
            label="Estimated Revenue"
            value="$28,416"
            percent="+12%"
            sparkline={[22, 28, 30, 36, 40, 48, 52, 60]}
            sparkStroke="#20dc8c"
            icon={
              <svg viewBox="0 0 24 24">
                <path d="M12 3v18M8 8c0-2 8-2 8 2s-8 2-8 4 8 2 8 2" />
              </svg>
            }
          />
        </div>

        <div className="mp-grid-3">
          <Panel
            title="Performance Overview"
            action={
              <div className="mp-tabs">
                {PERF_TABS.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={`mp-tab${perfTab === tab ? " is-active" : ""}`}
                    onClick={() => {
                      setPerfTab(tab);
                      toast(`${tab} performance`);
                    }}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            }
          >
            <div className="mp-chart-wrap">
              <div style={{ minWidth: 0 }}>
                <div className="mp-list-meta" style={{ marginBottom: 6, display: "flex", justifyContent: "space-between" }}>
                  <span>Last 28 days · {perfTab}</span>
                  <span className="mp-badge is-red">Oct 17, 2024 · 2.4M views</span>
                </div>
                <LineChart
                  series={[{ id: "views", color: "#e53935", values: VIEW_SERIES, fill: "rgba(229,57,53,0.12)" }]}
                  labels={["Oct 1", "Oct 8", "Oct 15", "Oct 22", "Oct 28"]}
                  height={190}
                  marker={{ index: 8, label: "2.4M views" }}
                />
              </div>
              <div className="mp-side-stats">
                {[
                  ["Views", "2.4M", "+18%"],
                  ["Likes", "186.2K", "+14%"],
                  ["Comments", "6.8K", "+22%"],
                  ["Shares", "12.1K", "+31%"],
                ].map(([label, value, pct]) => (
                  <div key={label} className="mp-side-stat">
                    <span>{label}</span>
                    <strong>{value}</strong>
                    <GrowthDelta percent={pct} />
                  </div>
                ))}
              </div>
            </div>
          </Panel>

          <Panel title="Latest Uploads">
            <div className="mp-list">
              {UPLOADS.map((item) => (
                <div key={item.title} className="mp-list-row">
                  <img className="mp-thumb" src={item.thumb} alt="" />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{item.title}</div>
                    <div className="mp-list-meta">
                      {item.views} · {item.when}
                    </div>
                  </div>
                  <span className="mp-badge is-green">{item.growth}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Content Schedule">
            <div className="mp-list">
              {SCHEDULE.map((item) => (
                <div key={item.title} className="mp-list-row">
                  <img className="mp-thumb" src={item.thumb} alt="" />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{item.title}</div>
                    <div className="mp-list-meta">{item.when}</div>
                  </div>
                  <span className={`mp-badge ${item.status === "Live" ? "is-live" : "is-muted"}`}>{item.status}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-4">
          <div style={{ gridColumn: "span 2" }}>
            <Panel title="Top Performing Videos">
              <table className="mp-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Video</th>
                    <th>Views</th>
                    <th>Watch Time</th>
                    <th>Avg. View %</th>
                  </tr>
                </thead>
                <tbody>
                  {TOP.map((row) => (
                    <tr key={row.rank}>
                      <td>{row.rank}</td>
                      <td>
                        <div className="mp-list-row">
                          <img className="mp-thumb" src={row.thumb} alt="" />
                          <span className="mp-list-title">{row.title}</span>
                        </div>
                      </td>
                      <td>{row.views}</td>
                      <td>{row.watch}</td>
                      <td>{row.avg}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>

          <Panel title="AI Content Tools">
            <div className="mp-tool-grid">
              {[
                ["Video Ideas", "M4 7h16M8 3v4M16 3v4M6 11h4v8H6zM14 11h4v5h-4z"],
                ["Script Generator", "M7 4h10v16H7zM10 8h4M10 12h4M10 16h3"],
                ["Thumbnail Creator", "M4 6h16v12H4zM8 14l3-3 2 2 3-4 4 5"],
                ["Title Optimizer", "M5 7h14M8 12h8M10 17h4"],
              ].map(([label, d]) => (
                <button key={label} type="button" className="mp-tool-tile" onClick={() => toast(label)}>
                  <svg viewBox="0 0 24 24">
                    <path d={d} />
                  </svg>
                  <strong>{label}</strong>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Thumbnail Lab">
            <div className="mp-ab">
              {[
                { label: "A · 68% CTR", pct: 68, img: mediaControlCrops.youtubeThumb1, tone: "green" as const },
                { label: "B · 32% CTR", pct: 32, img: mediaControlCrops.youtubeThumb2, tone: "red" as const },
              ].map((item) => (
                <div key={item.label} className="mp-ab-card">
                  <img src={item.img} alt="" />
                  <div className="mp-ab-meta">
                    <div className="mp-ab-label">{item.label}</div>
                    <ProgressBar value={item.pct} tone={item.tone} showValue={false} />
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <Panel title="Comment Moderation" action={<span className="mp-badge is-red">Unread (12)</span>}>
          <div className="mp-list">
            {COMMENTS.map((c) => (
              <div key={c.user + c.time} className="mp-comment">
                <img className="mp-avatar-sm" src={c.avatar} alt="" />
                <div className="mp-comment-body">
                  <div className="mp-comment-head">
                    <strong>@{c.user}</strong>
                    <span>{c.time}</span>
                  </div>
                  <div className="mp-comment-text">{c.text}</div>
                  <button className="mp-link-btn" type="button" onClick={() => toast(`Reply to @${c.user}`)}>
                    Reply
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <div className="mp-pipeline">
          <div className="mp-footer-quote" style={{ marginLeft: 0, marginRight: 8 }}>
            A higher humanity reaches further.
          </div>
          {[
            ["Ideas", "12"],
            ["Scripting", "6"],
            ["Production", "4"],
            ["Editing", "3"],
            ["Review", "2"],
            ["Scheduled", "1"],
          ].map(([label, value], i, arr) => (
            <div key={label} style={{ display: "contents" }}>
              <div className="mp-pipeline-step">
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
              {i < arr.length - 1 ? <span className="mp-pipeline-arrow">→</span> : null}
            </div>
          ))}
          <button className="mp-btn mp-btn-solid" type="button" onClick={() => toast("Upload New Video")}>
            Upload New Video
          </button>
          <div className="mp-footer-quote">Ideas today · A brighter tomorrow</div>
        </div>
      </div>
      </main>
    </AppShell>
  );
}
