import { Link } from "react-router-dom";
import { useState } from "react";
import {
  GrowthDelta,
  LineChart,
  MetricCard,
  Panel,
  PlatformIcon,
  ProgressBar,
  Sparkline,
  StatusDot,
  type PlatformKind,
} from "../../components/media/MediaWidgets";
import { mediaControlCrops, platformTiles } from "../../assets/mediaControlAssets";
import { MediaPlatformShell } from "../../layouts/MediaPlatformShell";
import { useAppToast } from "../../state/useAppToast";

const PLATFORMS: Array<{
  id: PlatformKind;
  to: string;
  label: string;
  metric: string;
  value: string;
  change: string;
  eng: string;
  sched: string;
  reach: string;
  last: string;
  spark: number[];
}> = [
  { id: "youtube", to: "/media/youtube", label: "YouTube", metric: "Subscribers", value: "1.32M", change: "+2.4%", eng: "6.8%", sched: "4", reach: "18.4M", last: "2h ago", spark: [40, 44, 48, 52, 55, 58, 60, 64] },
  { id: "tiktok", to: "/media/tiktok", label: "TikTok", metric: "Followers", value: "1.80M", change: "+3.1%", eng: "9.2%", sched: "6", reach: "42.7M", last: "45m ago", spark: [30, 36, 40, 48, 52, 58, 62, 70] },
  { id: "instagram", to: "/media/instagram", label: "Instagram", metric: "Followers", value: "1.24M", change: "+1.5%", eng: "6.8%", sched: "5", reach: "12.6M", last: "3h ago", spark: [28, 32, 35, 38, 42, 46, 50, 54] },
  { id: "facebook", to: "/media/facebook", label: "Facebook", metric: "Followers", value: "1.24M", change: "+1.5%", eng: "5.4%", sched: "3", reach: "4.82M", last: "5h ago", spark: [22, 26, 28, 32, 36, 40, 44, 48] },
];

const JOBS = [
  { id: "#1001", task: "Market Update Short", type: "Video", platforms: ["youtube", "tiktok"] as PlatformKind[], status: "Rendering", tone: "teal" as const, progress: 72, eta: "4m" },
  { id: "#1002", task: "Higher Humanity Carousel", type: "Image", platforms: ["instagram", "facebook"] as PlatformKind[], status: "In Progress", tone: "gold" as const, progress: 48, eta: "12m" },
  { id: "#1003", task: "Caption Pack · Discipline", type: "Text", platforms: ["tiktok", "instagram"] as PlatformKind[], status: "Queued", tone: "gold" as const, progress: 12, eta: "28m" },
  { id: "#1004", task: "Auto Clip · Keynote", type: "Automation", platforms: ["youtube"] as PlatformKind[], status: "Editing", tone: "teal" as const, progress: 61, eta: "9m" },
  { id: "#1005", task: "Story Frame Set", type: "Image", platforms: ["instagram"] as PlatformKind[], status: "Completed", tone: "green" as const, progress: 100, eta: "—" },
  { id: "#1006", task: "FB Ad Creative A/B", type: "Video", platforms: ["facebook"] as PlatformKind[], status: "Queued", tone: "gold" as const, progress: 8, eta: "40m" },
  { id: "#1007", task: "Trend Sound Remix", type: "Video", platforms: ["tiktok"] as PlatformKind[], status: "In Progress", tone: "gold" as const, progress: 34, eta: "18m" },
  { id: "#1008", task: "Weekly Report Export", type: "Automation", platforms: ["youtube", "facebook"] as PlatformKind[], status: "Completed", tone: "green" as const, progress: 100, eta: "—" },
];

const CAL = [
  { when: "Tue 18:00", title: "Market Update Short", tags: "Short Video · Economy", platform: "youtube" as PlatformKind, thumb: platformTiles.youtube[0] },
  { when: "Wed 12:00", title: "Discipline Cutdown", tags: "Reel · Mindset", platform: "instagram" as PlatformKind, thumb: platformTiles.instagram[0] },
  { when: "Thu 09:00", title: "Community Pulse", tags: "Post · Culture", platform: "facebook" as PlatformKind, thumb: platformTiles.facebook[0] },
  { when: "Fri 19:30", title: "Trend Remix", tags: "Short · Sound", platform: "tiktok" as PlatformKind, thumb: platformTiles.tiktok[0] },
  { when: "Sat 11:00", title: "Impact Report", tags: "Carousel · Data", platform: "instagram" as PlatformKind, thumb: platformTiles.instagram[1] },
];

const COMMENTS = [
  { user: "nova_prime", text: "This campaign orchestration is elite.", sentiment: "Positive", time: "2m" },
  { user: "orbit_lab", text: "Can you clarify the schedule window?", sentiment: "Neutral", time: "18m" },
  { user: "signal_k", text: "Thumbnail feels off-brand.", sentiment: "Negative", time: "41m" },
  { user: "aether", text: "Cross-platform reach looking strong.", sentiment: "Positive", time: "1h" },
];

const TOOLS = [
  "Script Generation",
  "Thumbnail Ideation",
  "Caption Writing",
  "Auto Clipping",
  "Hashtag Research",
  "Trend Discovery",
  "Voiceover (TTS)",
  "Smart Scheduling",
];

const LOGS = [
  { t: "14:37:21", text: "Thumbnail generated", platform: "youtube" as PlatformKind },
  { t: "14:36:08", text: "Post published", platform: "instagram" as PlatformKind },
  { t: "14:34:52", text: "Campaign draft saved", platform: "facebook" as PlatformKind },
  { t: "14:32:11", text: "Video exported", platform: "tiktok" as PlatformKind },
  { t: "14:30:44", text: "Caption AI completed", platform: "youtube" as PlatformKind },
];

const PIPE_TABS = ["All (8)", "Video (3)", "Image (2)", "Text (2)", "Automation (1)"] as const;

export function MediaControlPage() {
  const toast = useAppToast();
  const [pipeTab, setPipeTab] = useState<(typeof PIPE_TABS)[number]>("All (8)");
  const [platforms, setPlatforms] = useState<PlatformKind[]>(["youtube", "tiktok", "instagram"]);

  const togglePlatform = (id: PlatformKind) => {
    setPlatforms((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));
  };

  return (
    <MediaPlatformShell
      activePlatform="media"
      searchPlaceholder="Search media, content, campaigns, platforms, or ask Leviathan..."
      createAccent="gold"
      sidebarPoster={mediaControlCrops.mediaSidebarPoster}
      sidebarCaption="Discipline creates freedom."
      promo={{ image: mediaControlCrops.mediaPoster, caption: "Content builds influence." }}
      statusItems={[
        { label: "Memory", value: "Online" },
        { label: "Systems", value: "Operational" },
        { label: "Media Queue", value: "3 / 10" },
        { label: "Storage", value: "42%" },
      ]}
    >
      <div className="mp-page">
        <section className="mp-hero">
          <div className="mp-hero-media">
            <img src={mediaControlCrops.mediaHeroWide} alt="" />
          </div>
          <div className="mp-hero-shade" />
          <div className="mp-hero-content">
            <div className="mp-hero-copy">
              <h1 className="mp-hero-title">Media Control</h1>
              <div className="mp-hero-flow">Create. Schedule. Publish. Scale.</div>
              <div className="mp-list-meta" style={{ marginTop: 8, letterSpacing: "0.08em" }}>
                “Ideas compound when they reach the world.” — LEVIATHAN
              </div>
            </div>
            <div className="mp-hero-quotes">
              <span>Content builds influence</span>
              <span>Influence builds opportunity</span>
              <span>A brighter tomorrow together</span>
            </div>
          </div>
        </section>

        <Panel title="1 · Platform Overview / Channel Grid">
          <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
            {PLATFORMS.map((p) => (
              <Link key={p.id} to={p.to} className="mp-metric-card" style={{ textDecoration: "none", color: "inherit" }}>
                <div className="mp-metric-head">
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <PlatformIcon platform={p.id} />
                    <strong>{p.label}</strong>
                  </div>
                  <span className="mp-badge is-green">
                    <StatusDot tone="green" /> Connected
                  </span>
                </div>
                <div className="mp-list-meta">{p.metric}</div>
                <div className="mp-metric-value">{p.value}</div>
                <GrowthDelta percent={p.change} />
                <div className="mp-list-meta">
                  Eng {p.eng} · Scheduled {p.sched} · 30d {p.reach}
                </div>
                <Sparkline values={p.spark} stroke="#00e5ff" fill="rgba(0,229,255,0.12)" />
                <div className="mp-list-meta">Last post {p.last}</div>
              </Link>
            ))}
          </div>
        </Panel>

        <Panel title="2 · Campaign Orchestrator">
          <div className="mp-grid-2" style={{ gridTemplateColumns: "1.6fr 0.8fr" }}>
            <div className="mp-stack">
              <div className="mp-chip-row">
                {(["youtube", "tiktok", "instagram", "facebook"] as PlatformKind[]).map((id) => (
                  <button
                    key={id}
                    type="button"
                    className="mp-tab"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      background: platforms.includes(id) ? "rgba(214,169,87,0.16)" : undefined,
                      borderColor: platforms.includes(id) ? "var(--mp-border-strong)" : undefined,
                    }}
                    onClick={() => togglePlatform(id)}
                  >
                    <PlatformIcon platform={id} />
                    {id}
                  </button>
                ))}
              </div>
              <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
                {[
                  ["Content Type", "Short Video"],
                  ["Campaign Objective", "Brand Awareness"],
                  ["Approval Mode", "Auto AI + Rules"],
                  ["Posting Priority", "High"],
                  ["Schedule", "Apr 22, 2025 18:00 UTC"],
                  ["Audience", "Lookalike · Core"],
                ].map(([label, value]) => (
                  <label key={label} className="mp-stack" style={{ gap: 4 }}>
                    <span className="mp-list-meta">{label}</span>
                    <select className="mp-select" defaultValue={value}>
                      <option>{value}</option>
                    </select>
                  </label>
                ))}
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <button className="mp-btn mp-btn-solid" type="button" onClick={() => toast("Launch Campaign")} style={{ background: "var(--mp-gold-bright)", color: "#111" }}>
                  Launch Campaign
                </button>
                <button className="mp-link-btn" type="button" onClick={() => toast("Save as Draft")}>
                  Save as Draft
                </button>
              </div>
            </div>
            <div className="mp-stack" style={{ border: "1px solid var(--mp-border)", borderRadius: 10, padding: 12 }}>
              <div className="mp-list-meta">Estimated Reach</div>
              <div className="mp-metric-value" style={{ fontSize: 22 }}>
                ~ 420K – 1.2M
              </div>
              {["AI Optimization", "Cross-Platform", "Trend Matching", "Audience Targeting"].map((opt) => (
                <label key={opt} className="mp-list-meta" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input type="checkbox" defaultChecked /> {opt}
                </label>
              ))}
            </div>
          </div>
        </Panel>

        <Panel
          title="3 · Content Pipeline / Active Jobs"
          action={
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div className="mp-tabs">
                {PIPE_TABS.map((t) => (
                  <button key={t} type="button" className={`mp-tab${pipeTab === t ? " is-active" : ""}`} onClick={() => setPipeTab(t)}>
                    {t}
                  </button>
                ))}
              </div>
              <button className="mp-btn" type="button" onClick={() => toast("New Job")}>
                + New Job
              </button>
            </div>
          }
        >
          <table className="mp-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Content Task</th>
                <th>Type</th>
                <th>Platforms</th>
                <th>Status</th>
                <th>Progress</th>
                <th>ETA</th>
              </tr>
            </thead>
            <tbody>
              {JOBS.map((j) => (
                <tr key={j.id}>
                  <td style={{ color: "var(--mp-green)" }}>{j.id}</td>
                  <td>{j.task}</td>
                  <td>{j.type}</td>
                  <td>
                    <div style={{ display: "flex", gap: 4 }}>
                      {j.platforms.map((p) => (
                        <PlatformIcon key={p} platform={p} />
                      ))}
                    </div>
                  </td>
                  <td>
                    <span className={`mp-badge ${j.tone === "green" ? "is-green" : j.tone === "teal" ? "is-gold" : "is-muted"}`}>
                      <StatusDot tone={j.tone === "teal" ? "teal" : j.tone} /> {j.status}
                    </span>
                  </td>
                  <td style={{ minWidth: 120 }}>
                    <ProgressBar value={j.progress} tone="teal" />
                  </td>
                  <td>{j.eta}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="4 · Performance Analytics" action={<span className="mp-badge is-muted">Last 30 Days</span>}>
          <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(6, minmax(0,1fr))", marginBottom: 10 }}>
            <MetricCard label="Total Reach" value="78.4M" percent="+12.4%" sparkline={[40, 48, 52, 60, 66, 70, 74, 78]} sparkStroke="#00e5ff" />
            <MetricCard label="Watch Time" value="14.2M hrs" percent="+8.1%" sparkline={[30, 34, 40, 44, 50, 55, 58, 62]} sparkStroke="#c5a059" />
            <MetricCard label="Engagement Rate" value="7.2%" percent="+1.1%" sparkline={[5, 5.4, 5.8, 6.1, 6.4, 6.8, 7, 7.2]} sparkStroke="#20dc8c" />
            <MetricCard label="CTR" value="3.8%" percent="-0.2%" direction="down" sparkline={[4.2, 4.1, 4, 3.9, 3.9, 3.85, 3.82, 3.8]} sparkStroke="#e53935" />
            <MetricCard label="Audience Growth" value="+86.4K" percent="+4.6%" sparkline={[20, 28, 35, 42, 50, 60, 72, 86]} sparkStroke="#20dc8c" />
            <MetricCard label="Conversion Rate" value="2.1%" percent="+0.4%" sparkline={[1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2, 2.1]} sparkStroke="#00e5ff" />
          </div>
          <LineChart
            series={[
              { id: "reach", color: "#00e5ff", values: [40, 48, 55, 62, 70, 74, 80, 86] },
              { id: "watch", color: "#c5a059", values: [30, 34, 40, 46, 52, 58, 60, 64] },
              { id: "eng", color: "#20dc8c", values: [20, 24, 28, 32, 36, 40, 44, 48] },
              { id: "conv", color: "#fe2c55", values: [10, 12, 14, 16, 18, 20, 22, 24] },
            ]}
            labels={["Mar 23", "Mar 30", "Apr 6", "Apr 13", "Apr 20"]}
            height={180}
          />
        </Panel>

        <div className="mp-grid-2">
          <Panel title="5 · Content Calendar">
            <div className="mp-list">
              {CAL.map((c) => (
                <div key={c.when} className="mp-list-row">
                  <div style={{ width: 70, fontSize: 11, color: "var(--mp-gold)" }}>{c.when}</div>
                  <img className="mp-thumb" src={c.thumb} alt="" />
                  <PlatformIcon platform={c.platform} />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{c.title}</div>
                    <div className="mp-list-meta">{c.tags}</div>
                  </div>
                  <span className="mp-badge is-green">Scheduled</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel
            title="6 · Asset Library / Media Vault"
            action={
              <button className="mp-btn" type="button" onClick={() => toast("Upload")}>
                Upload
              </button>
            }
          >
            <div className="mp-tabs" style={{ marginBottom: 8 }}>
              {["All", "Videos", "Images", "Templates", "Audio", "Brand Kits"].map((t, i) => (
                <button key={t} type="button" className={`mp-tab${i === 0 ? " is-active" : ""}`}>
                  {t}
                </button>
              ))}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8 }}>
              {[...platformTiles.youtube.slice(0, 2), ...platformTiles.instagram.slice(0, 2)].map((src, i) => (
                <div key={i} className="mp-ab-card">
                  <img src={src} alt="" />
                  <div className="mp-ab-meta">
                    <div className="mp-list-title">{i % 2 === 0 ? "Q2_Market_Update.mp4" : "Brand_Still.jpg"}</div>
                    <div className="mp-list-meta">{i % 2 === 0 ? "4K · 00:42" : "2048×2048"}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-2">
          <Panel
            title="7 · Comments / Inbox / Community"
            action={
              <div className="mp-tabs">
                {["All (24)", "Unread (5)", "Mentions (3)", "Positive", "Neutral", "Negative"].map((t, i) => (
                  <button key={t} type="button" className={`mp-tab${i === 0 ? " is-active" : ""}`}>
                    {t}
                  </button>
                ))}
              </div>
            }
          >
            {COMMENTS.map((c) => (
              <div key={c.user} className="mp-comment">
                <div className="mp-avatar-sm" />
                <div className="mp-comment-body">
                  <div className="mp-comment-head">
                    <strong>@{c.user}</strong>
                    <span>{c.time}</span>
                    <span className={`mp-badge ${c.sentiment === "Positive" ? "is-green" : c.sentiment === "Negative" ? "is-red" : "is-muted"}`}>{c.sentiment}</span>
                  </div>
                  <div className="mp-comment-text">{c.text}</div>
                  <button className="mp-link-btn" type="button" onClick={() => toast(`Reply @${c.user}`)}>
                    Reply
                  </button>
                </div>
              </div>
            ))}
          </Panel>

          <Panel title="8 · AI Media Tools">
            <div className="mp-tool-grid" style={{ gridTemplateColumns: "repeat(4,1fr)" }}>
              {TOOLS.map((t) => (
                <button key={t} type="button" className="mp-tool-tile" onClick={() => toast(t)}>
                  <svg viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="7" />
                    <path d="M12 8v8M8 12h8" />
                  </svg>
                  <strong>{t}</strong>
                </button>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-2">
          <Panel title="9 · System Usage / Workflow Health" action={<span className="mp-badge is-green">All Systems Nominal</span>}>
            {[
              ["Media Processing", 68, "teal"],
              ["AI Generation", 43, "gold"],
              ["Storage Usage", 42, "gold"],
              ["Bandwidth", 32, "teal"],
              ["Queue Load", 30, "green"],
            ].map(([label, value, tone]) => (
              <ProgressBar key={label as string} label={label as string} value={value as number} tone={tone as "teal" | "gold" | "green"} />
            ))}
            <div className="mp-list-meta" style={{ marginTop: 8 }}>
              Bandwidth 320 GB / 1 TB · Queue 3 / 10
            </div>
          </Panel>

          <Panel title="10 · Logs / Event Timeline" action={<span className="mp-badge is-live">Live</span>}>
            <div className="mp-list">
              {LOGS.map((l) => (
                <div key={l.t + l.text} className="mp-list-row">
                  <span className="mp-list-meta" style={{ width: 64 }}>
                    {l.t}
                  </span>
                  <PlatformIcon platform={l.platform} />
                  <span className="mp-list-title">{l.text}</span>
                  <StatusDot tone="green" />
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </MediaPlatformShell>
  );
}
