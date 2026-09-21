import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { mediaControlCrops, platformTiles } from "../../assets/mediaControlAssets";
import {
  LineChart,
  PlatformIcon,
  Sparkline,
  type PlatformKind,
} from "../../components/media/MediaWidgets";
import { SubMenu } from "../../components/SubMenu";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";

const PLATFORMS = [
  {
    id: "youtube" as const,
    name: "YouTube",
    metricLabel: "Subscribers",
    metric: "1.32M",
    growth: "+2.4%",
    engagement: "6.8%",
    scheduled: 4,
    reach: "18.4M",
    lastPost: "2h ago",
    spark: [42, 48, 45, 52, 58, 55, 62, 68, 64, 72],
    to: "/media/youtube",
  },
  {
    id: "tiktok" as const,
    name: "TikTok",
    metricLabel: "Followers",
    metric: "1.80M",
    growth: "+3.1%",
    engagement: "9.2%",
    scheduled: 6,
    reach: "42.7M",
    lastPost: "45m ago",
    spark: [30, 38, 42, 40, 55, 60, 58, 70, 75, 82],
    to: "/media/tiktok",
  },
  {
    id: "instagram" as const,
    name: "Instagram",
    metricLabel: "Followers",
    metric: "1.24M",
    growth: "+1.5%",
    engagement: "6.8%",
    scheduled: 5,
    reach: "12.6M",
    lastPost: "3h ago",
    spark: [50, 48, 52, 55, 53, 58, 60, 57, 62, 65],
    to: "/media/instagram",
  },
  {
    id: "facebook" as const,
    name: "Facebook",
    metricLabel: "Followers",
    metric: "1.24M",
    growth: "+1.5%",
    engagement: "5.4%",
    scheduled: 3,
    reach: "4.82M",
    lastPost: "5h ago",
    spark: [40, 42, 41, 44, 43, 46, 45, 48, 47, 50],
    to: "/media/facebook",
  },
] as const;

const PIPELINE_TABS = ["All", "Video", "Image", "Text", "Automation"] as const;

const JOBS = [
  { id: 1001, task: "Market Update Short", type: "Short Video", kind: "Video", platforms: ["youtube", "tiktok"] as PlatformKind[], status: "Rendering", statusTone: "warn", progress: 72, eta: "4m" },
  { id: 1002, task: "Weekly Recap Reel", type: "Reel", kind: "Video", platforms: ["instagram", "tiktok"] as PlatformKind[], status: "In Progress", statusTone: "cyan", progress: 48, eta: "12m" },
  { id: 1003, task: "Macro Brief Carousel", type: "Carousel", kind: "Image", platforms: ["instagram", "facebook"] as PlatformKind[], status: "Queued", statusTone: "muted", progress: 12, eta: "28m" },
  { id: 1004, task: "Trading Psychology Tips", type: "Short Video", kind: "Video", platforms: ["youtube"] as PlatformKind[], status: "Editing", statusTone: "gold", progress: 61, eta: "9m" },
  { id: 1005, task: "Thread: Liquidity Map", type: "Text", kind: "Text", platforms: ["facebook", "instagram"] as PlatformKind[], status: "Queued", statusTone: "muted", progress: 8, eta: "35m" },
  { id: 1006, task: "Brand Kit Refresh", type: "Image", kind: "Image", platforms: ["instagram"] as PlatformKind[], status: "Completed", statusTone: "ok", progress: 100, eta: "—" },
  { id: 1007, task: "Caption Batch · Q2", type: "Text", kind: "Text", platforms: ["youtube", "tiktok", "instagram"] as PlatformKind[], status: "In Progress", statusTone: "cyan", progress: 34, eta: "18m" },
  { id: 1008, task: "Auto-clip Night Session", type: "Automation", kind: "Automation", platforms: ["youtube", "tiktok"] as PlatformKind[], status: "Queued", statusTone: "muted", progress: 5, eta: "42m" },
] as const;

const KPIS = [
  { label: "Total Reach", value: "8.42M", delta: "+12.4%", spark: [20, 28, 26, 34, 40, 38, 48, 52] },
  { label: "Watch Time", value: "142.6K h", delta: "+8.1%", spark: [18, 22, 30, 28, 36, 42, 40, 48] },
  { label: "Engagement Rate", value: "6.94%", delta: "+1.2%", spark: [30, 32, 31, 36, 38, 37, 42, 44] },
  { label: "CTR", value: "3.28%", delta: "+0.4%", spark: [22, 24, 23, 26, 28, 30, 29, 32] },
  { label: "Audience Growth", value: "+18.2K", delta: "+6.7%", spark: [14, 18, 22, 28, 32, 36, 40, 46] },
  { label: "Conversion Rate", value: "2.14%", delta: "-0.2%", spark: [40, 38, 36, 34, 35, 33, 32, 31], down: true },
] as const;

const CALENDAR = [
  { when: "Apr 22 · 18:00", title: "Trading Psychology Tips", tags: ["Short Video", "Education"], platforms: ["youtube"] as PlatformKind[], thumb: mediaControlCrops.youtubeThumb1 },
  { when: "Apr 23 · 09:30", title: "Macro Brief Carousel", tags: ["Carousel", "Economy"], platforms: ["instagram", "facebook"] as PlatformKind[], thumb: mediaControlCrops.instagramReel1 },
  { when: "Apr 23 · 16:00", title: "Weekly Recap Reel", tags: ["Reel", "Markets"], platforms: ["tiktok", "instagram"] as PlatformKind[], thumb: mediaControlCrops.youtubeThumb2 },
  { when: "Apr 24 · 12:00", title: "Liquidity Map Thread", tags: ["Text", "Analysis"], platforms: ["facebook"] as PlatformKind[], thumb: mediaControlCrops.mediaPoster },
  { when: "Apr 25 · 20:00", title: "Night Session Highlights", tags: ["Short Video", "Live"], platforms: ["youtube", "tiktok"] as PlatformKind[], thumb: mediaControlCrops.tiktokPoster },
  { when: "Apr 27 · 11:00", title: "Brand Kit Drop", tags: ["Image", "Brand"], platforms: ["instagram"] as PlatformKind[], thumb: mediaControlCrops.instagramPoster },
] as const;

const ASSET_TABS = ["All", "Videos", "Images", "Templates", "Audio", "Brand Kits"] as const;

const ASSETS = [
  { name: "Q2_Market_Update.mp4", meta: "1080p · 42 MB · 0:48", kind: "Videos", img: platformTiles.youtube[0] },
  { name: "Psychology_Tips_01.mp4", meta: "4K · 118 MB · 1:12", kind: "Videos", img: platformTiles.youtube[1] },
  { name: "Macro_Carousel_A.png", meta: "1080×1350 · 3.2 MB", kind: "Images", img: platformTiles.instagram[0] },
  { name: "Weekly_Recap_Thumb.jpg", meta: "1280×720 · 890 KB", kind: "Images", img: platformTiles.tiktok[0] },
  { name: "Caption_Template_Q2", meta: "Template · 14 variants", kind: "Templates", img: platformTiles.facebook[0] },
  { name: "Brand_Kit.zip", meta: "Folder · 86 assets", kind: "Brand Kits", img: mediaControlCrops.mediaPoster },
  { name: "Voiceover_Night.wav", meta: "48 kHz · 12.4 MB", kind: "Audio", img: platformTiles.youtube[2] },
  { name: "Liquidity_Map_Still.jpg", meta: "1920×1080 · 2.1 MB", kind: "Images", img: platformTiles.instagram[1] },
] as const;

const COMMENT_TABS = ["All", "Unread", "Mentions"] as const;
const SENTIMENTS = ["Positive", "Neutral", "Negative"] as const;

const COMMENTS = [
  { user: "@alpha_trader", time: "12m", text: "This breakdown on liquidity voids is elite. More of these.", sentiment: "Positive" as const, unread: true },
  { user: "@macro_mira", time: "34m", text: "Can you cover rate-cut odds next week?", sentiment: "Neutral" as const, unread: true },
  { user: "@clip_king", time: "1h", text: "Thumbnail game is strong — saved the carousel.", sentiment: "Positive" as const, unread: false },
  { user: "@skeptic_42", time: "2h", text: "Audio levels dipped mid-reel. Fix for next one?", sentiment: "Negative" as const, unread: false },
  { user: "@leviathan_fan", time: "3h", text: "@leviathan the psychology tips hit different.", sentiment: "Positive" as const, unread: false },
] as const;

const AI_TOOLS = [
  { title: "Script Generation", desc: "Draft short-form scripts from briefs.", icon: "script" },
  { title: "Thumbnail Ideation", desc: "Compose cinematic thumbnail variants.", icon: "thumb" },
  { title: "Caption Writing", desc: "Platform-tuned captions and hooks.", icon: "caption" },
  { title: "Auto Clipping", desc: "Extract viral moments from longform.", icon: "clip" },
  { title: "Hashtag Research", desc: "Rank tags by reach and competition.", icon: "hash" },
  { title: "Trend Discovery", desc: "Surface rising formats and topics.", icon: "trend" },
  { title: "Voiceover (TTS)", desc: "Generate branded narration tracks.", icon: "voice" },
  { title: "Smart Scheduling", desc: "Pick peak windows per platform.", icon: "clock" },
] as const;

const USAGE = [
  { label: "Media Processing", value: 68, detail: "68%" },
  { label: "AI Generation", value: 43, detail: "43%" },
  { label: "Storage Usage", value: 42, detail: "210 / 500 GB" },
  { label: "Bandwidth", value: 32, detail: "320 GB / 1 TB" },
  { label: "Queue Load", value: 30, detail: "3 / 10" },
] as const;

const LOGS = [
  { time: "14:37:18", text: "Thumbnail generated · Market Update Short", tone: "ok", platform: "youtube" as PlatformKind },
  { time: "14:36:42", text: "Post published · Weekly Recap Reel", tone: "ok", platform: "tiktok" as PlatformKind },
  { time: "14:35:11", text: "Asset uploaded · Brand_Kit.zip", tone: "info", platform: "instagram" as PlatformKind },
  { time: "14:33:05", text: "Render queue · 2 jobs waiting", tone: "warn", platform: "youtube" as PlatformKind },
  { time: "14:31:48", text: "Caption batch completed · 14 items", tone: "ok", platform: "facebook" as PlatformKind },
  { time: "14:29:22", text: "Campaign draft saved · Q2 Awareness", tone: "info", platform: "instagram" as PlatformKind },
  { time: "14:27:09", text: "Auto-clip failed · retry scheduled", tone: "err", platform: "tiktok" as PlatformKind },
] as const;

const PLATFORM_OPTS = ["YouTube", "TikTok", "Instagram", "Facebook"] as const;

function ToolIcon({ kind }: { kind: string }) {
  switch (kind) {
    case "script":
      return <path d="M7 5h10v14H7zM9 8h6M9 11h6M9 14h4" />;
    case "thumb":
      return (
        <>
          <rect x="4" y="6" width="16" height="12" rx="2" />
          <path d="M8 14l3-3 2.5 2.5L16 11l2 2" />
        </>
      );
    case "caption":
      return <path d="M5 7h14v8H9l-4 3V7z" />;
    case "clip":
      return <path d="M8 6l10 6-10 6V6z" />;
    case "hash":
      return <path d="M9 5l-2 14M17 5l-2 14M5 9h14M4 15h14" />;
    case "trend":
      return <path d="M4 16l5-5 3 3 7-8" />;
    case "voice":
      return (
        <>
          <rect x="9" y="4" width="6" height="10" rx="3" />
          <path d="M6 11a6 6 0 0012 0M12 17v3" />
        </>
      );
    default:
      return (
        <>
          <circle cx="12" cy="12" r="8" />
          <path d="M12 8v4l3 2" />
        </>
      );
  }
}

function SectionTitle({ n, title }: { n: number; title: string }) {
  return (
    <header className="lv-mc-section-head">
      <span className="lv-mc-section-num">{n}.</span>
      <h2>{title}</h2>
    </header>
  );
}

export function MediaControlPage() {
  const toast = useAppToast();
  const [pipelineTab, setPipelineTab] = useState<(typeof PIPELINE_TABS)[number]>("All");
  const [assetTab, setAssetTab] = useState<(typeof ASSET_TABS)[number]>("All");
  const [commentTab, setCommentTab] = useState<(typeof COMMENT_TABS)[number]>("All");
  const [sentiment, setSentiment] = useState<(typeof SENTIMENTS)[number] | "All">("All");
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(["YouTube", "TikTok"]);
  const [campaignOpts, setCampaignOpts] = useState({
    ai: true,
    cross: true,
    trend: true,
    audience: false,
  });

  const filteredJobs = useMemo(() => {
    if (pipelineTab === "All") return JOBS;
    return JOBS.filter((job) => job.kind === pipelineTab);
  }, [pipelineTab]);

  const filteredAssets = useMemo(() => {
    if (assetTab === "All") return ASSETS;
    return ASSETS.filter((asset) => asset.kind === assetTab);
  }, [assetTab]);

  const filteredComments = useMemo(() => {
    return COMMENTS.filter((c) => {
      if (commentTab === "Unread" && !c.unread) return false;
      if (commentTab === "Mentions" && !c.text.includes("@")) return false;
      if (sentiment !== "All" && c.sentiment !== sentiment) return false;
      return true;
    });
  }, [commentTab, sentiment]);

  const chartSeries = useMemo(
    () => [
      { id: "Reach", color: "#22C9D6", values: [42, 48, 55, 52, 60, 68, 72, 70, 78, 85, 82, 90] },
      { id: "Watch Time", color: "#4285E8", values: [30, 34, 38, 42, 40, 48, 52, 55, 58, 62, 66, 70] },
      { id: "Engagement", color: "#20DC8C", values: [22, 24, 28, 26, 32, 30, 36, 38, 40, 42, 44, 46] },
      { id: "Conversions", color: "#D6A957", values: [12, 14, 13, 16, 18, 17, 20, 22, 21, 24, 26, 28] },
    ],
    [],
  );

  const togglePlatform = (name: string) => {
    setSelectedPlatforms((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name],
    );
  };

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Media Mode"
      searchPlaceholder="Search media, content, campaigns, platforms, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
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

        <SubMenu />

        <div className="lv-mc-grid-top">
          <section className="lv-mc-panel">
            <SectionTitle n={1} title="PLATFORM OVERVIEW / CHANNEL GRID" />
            <div className="lv-mc-channel-grid">
              {PLATFORMS.map((p) => (
                <Link key={p.id} to={p.to} className="lv-mc-channel-card">
                  <div className="lv-mc-channel-head">
                    <PlatformIcon platform={p.id} />
                    <div>
                      <strong>{p.name}</strong>
                      <span className="lv-mc-connected">
                        <i /> Connected
                      </span>
                    </div>
                  </div>
                  <div className="lv-mc-channel-metric">
                    <span>{p.metric}</span>
                    <small>{p.metricLabel}</small>
                    <em className="is-up">{p.growth}</em>
                  </div>
                  <div className="lv-mc-channel-stats">
                    <span>
                      Eng. <b>{p.engagement}</b>
                    </span>
                    <span>
                      Sched. <b>{p.scheduled}</b>
                    </span>
                  </div>
                  <div className="lv-mc-channel-reach">
                    <div>
                      <small>30d Reach</small>
                      <strong>{p.reach}</strong>
                    </div>
                    <Sparkline values={[...p.spark]} stroke="#22C9D6" fill="rgba(34,201,214,0.12)" />
                  </div>
                  <div className="lv-mc-channel-foot">Last Post · {p.lastPost}</div>
                </Link>
              ))}
            </div>
          </section>

          <section className="lv-mc-panel lv-mc-orchestrator">
            <SectionTitle n={2} title="CAMPAIGN ORCHESTRATOR" />
            <div className="lv-mc-orch-body">
              <div className="lv-mc-orch-form">
                <label className="lv-mc-field-label">Platforms</label>
                <div className="lv-mc-chips">
                  {PLATFORM_OPTS.map((name) => (
                    <button
                      key={name}
                      type="button"
                      className={`lv-mc-chip${selectedPlatforms.includes(name) ? " is-on" : ""}`}
                      onClick={() => togglePlatform(name)}
                    >
                      {name}
                    </button>
                  ))}
                </div>
                <div className="lv-mc-orch-fields">
                  {[
                    ["Content Type", "Short Video"],
                    ["Campaign Objective", "Awareness"],
                    ["Approval Mode", "Auto (Low Risk)"],
                    ["Posting Priority", "High"],
                  ].map(([label, value]) => (
                    <label key={label} className="lv-mc-field">
                      <span>{label}</span>
                      <select defaultValue={value} onChange={() => toast(label)}>
                        <option>{value}</option>
                        <option>Alt option</option>
                      </select>
                    </label>
                  ))}
                  <label className="lv-mc-field lv-mc-field--wide">
                    <span>Schedule</span>
                    <input type="datetime-local" defaultValue="2025-04-22T18:00" />
                  </label>
                </div>
                <div className="lv-mc-orch-actions">
                  <button type="button" className="lv-mc-btn-gold" onClick={() => toast("Launch Campaign")}>
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M4 12l7-2 2-7 7 16-7-2-2-7z" />
                    </svg>
                    Launch Campaign
                  </button>
                  <button type="button" className="lv-mc-btn-ghost" onClick={() => toast("Save as Draft")}>
                    Save as Draft
                  </button>
                </div>
              </div>
              <aside className="lv-mc-orch-summary">
                <div className="lv-mc-reach">
                  <small>Estimated Reach</small>
                  <strong>~ 420K – 1.2M</strong>
                </div>
                <div className="lv-mc-checks">
                  {(
                    [
                      ["ai", "AI Optimization"],
                      ["cross", "Cross-Platform"],
                      ["trend", "Trend Matching"],
                      ["audience", "Audience Targeting"],
                    ] as const
                  ).map(([key, label]) => (
                    <label key={key}>
                      <input
                        type="checkbox"
                        checked={campaignOpts[key]}
                        onChange={() => setCampaignOpts((prev) => ({ ...prev, [key]: !prev[key] }))}
                      />
                      {label}
                    </label>
                  ))}
                </div>
                <label className="lv-mc-field">
                  <span>Campaign Presets</span>
                  <select defaultValue="Q2 Awareness Blitz" onChange={() => toast("Campaign Presets")}>
                    <option>Q2 Awareness Blitz</option>
                    <option>Engagement Push</option>
                    <option>Product Launch</option>
                  </select>
                </label>
              </aside>
            </div>
          </section>
        </div>

        <div className="lv-mc-grid-mid">
          <section className="lv-mc-panel">
            <div className="lv-mc-panel-bar">
              <SectionTitle n={3} title="CONTENT PIPELINE / ACTIVE JOBS" />
              <button type="button" className="lv-mc-btn-teal" onClick={() => toast("New Job")}>
                + New Job
              </button>
            </div>
            <div className="lv-mc-tabs" role="tablist">
              {PIPELINE_TABS.map((tab) => {
                const count = tab === "All" ? JOBS.length : JOBS.filter((j) => j.kind === tab).length;
                return (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={pipelineTab === tab}
                    className={pipelineTab === tab ? "is-active" : ""}
                    onClick={() => setPipelineTab(tab)}
                  >
                    {tab} ({count})
                  </button>
                );
              })}
            </div>
            <div className="lv-mc-table-wrap">
              <table className="lv-mc-table">
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
                  {filteredJobs.map((job) => (
                    <tr key={job.id}>
                      <td>#{job.id}</td>
                      <td>{job.task}</td>
                      <td>{job.type}</td>
                      <td>
                        <span className="lv-mc-plat-row">
                          {job.platforms.map((p) => (
                            <PlatformIcon key={p} platform={p} className="is-sm" />
                          ))}
                        </span>
                      </td>
                      <td>
                        <span className={`lv-mc-pill is-${job.statusTone}`}>{job.status}</span>
                      </td>
                      <td>
                        <div className="lv-mc-prog">
                          <div className="lv-mc-prog-track">
                            <span style={{ width: `${job.progress}%` }} />
                          </div>
                          <em>{job.progress}%</em>
                        </div>
                      </td>
                      <td>{job.eta}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="lv-mc-panel">
            <SectionTitle n={4} title="PERFORMANCE ANALYTICS" />
            <div className="lv-mc-kpi-row">
              {KPIS.map((kpi) => (
                <article key={kpi.label} className="lv-mc-kpi">
                  <div className="lv-mc-kpi-label">{kpi.label}</div>
                  <div className="lv-mc-kpi-value">{kpi.value}</div>
                  <div className="lv-mc-kpi-foot">
                    <span className={"down" in kpi && kpi.down ? "is-down" : "is-up"}>{kpi.delta}</span>
                    <Sparkline
                      values={[...kpi.spark]}
                      stroke={"down" in kpi && kpi.down ? "#f87171" : "#20DC8C"}
                      fill={"down" in kpi && kpi.down ? "rgba(248,113,113,0.12)" : "rgba(32,220,140,0.12)"}
                    />
                  </div>
                </article>
              ))}
            </div>
            <div className="lv-mc-chart-block">
              <div className="lv-mc-chart-legend">
                {chartSeries.map((s) => (
                  <span key={s.id}>
                    <i style={{ background: s.color }} />
                    {s.id}
                  </span>
                ))}
              </div>
              <LineChart
                series={chartSeries}
                labels={["Mar 22", "Mar 29", "Apr 5", "Apr 12", "Apr 19", "Apr 22"]}
                height={168}
                className="lv-mc-line-chart"
              />
            </div>
          </section>

          <section className="lv-mc-panel">
            <SectionTitle n={5} title="CONTENT CALENDAR" />
            <div className="lv-mc-cal-label">This Week</div>
            <ul className="lv-mc-calendar">
              {CALENDAR.map((item) => (
                <li key={item.title}>
                  <time>{item.when}</time>
                  <img src={item.thumb} alt="" width={48} height={32} />
                  <div className="lv-mc-cal-body">
                    <div className="lv-mc-cal-title-row">
                      <strong>{item.title}</strong>
                      <span className="lv-mc-plat-row">
                        {item.platforms.map((p) => (
                          <PlatformIcon key={p} platform={p} className="is-sm" />
                        ))}
                      </span>
                    </div>
                    <div className="lv-mc-cal-tags">
                      {item.tags.map((tag) => (
                        <span key={tag}>{tag}</span>
                      ))}
                    </div>
                  </div>
                  <span className="lv-mc-pill is-ok">Scheduled</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <div className="lv-mc-grid-bot">
          <section className="lv-mc-panel">
            <div className="lv-mc-panel-bar">
              <SectionTitle n={6} title="ASSET LIBRARY / MEDIA VAULT" />
              <button type="button" className="lv-mc-btn-teal" onClick={() => toast("Upload")}>
                Upload
              </button>
            </div>
            <div className="lv-mc-asset-tools">
              <input
                type="search"
                placeholder="Search assets..."
                onKeyDown={(e) => {
                  if (e.key === "Enter") toast("Search assets");
                }}
              />
              <div className="lv-mc-tabs">
                {ASSET_TABS.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={assetTab === tab ? "is-active" : ""}
                    onClick={() => setAssetTab(tab)}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            </div>
            <div className="lv-mc-asset-grid">
              {filteredAssets.map((asset) => (
                <button
                  key={asset.name}
                  type="button"
                  className="lv-mc-asset-card"
                  onClick={() => toast(asset.name)}
                >
                  <img src={asset.img} alt="" width={160} height={100} />
                  <strong>{asset.name}</strong>
                  <small>{asset.meta}</small>
                </button>
              ))}
            </div>
          </section>

          <section className="lv-mc-panel">
            <SectionTitle n={7} title="COMMENTS / INBOX / COMMUNITY" />
            <div className="lv-mc-tabs">
              {COMMENT_TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={commentTab === tab ? "is-active" : ""}
                  onClick={() => setCommentTab(tab)}
                >
                  {tab}
                  {tab === "All" ? ` (${COMMENTS.length})` : ""}
                </button>
              ))}
            </div>
            <div className="lv-mc-sentiment">
              <button
                type="button"
                className={sentiment === "All" ? "is-active" : ""}
                onClick={() => setSentiment("All")}
              >
                All
              </button>
              {SENTIMENTS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`${sentiment === s ? "is-active" : ""} is-${s.toLowerCase()}`}
                  onClick={() => setSentiment(s)}
                >
                  {s}
                </button>
              ))}
            </div>
            <ul className="lv-mc-comments">
              {filteredComments.map((c) => (
                <li key={c.user + c.time}>
                  <div className="lv-mc-avatar" aria-hidden="true">
                    {c.user.slice(1, 3).toUpperCase()}
                  </div>
                  <div className="lv-mc-comment-body">
                    <div className="lv-mc-comment-meta">
                      <strong>{c.user}</strong>
                      <time>{c.time}</time>
                      <span className={`lv-mc-sentiment-tag is-${c.sentiment.toLowerCase()}`}>
                        {c.sentiment}
                      </span>
                    </div>
                    <p>{c.text}</p>
                  </div>
                  <button type="button" className="lv-mc-btn-ghost" onClick={() => toast(`Reply ${c.user}`)}>
                    Reply
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="lv-mc-panel">
            <SectionTitle n={8} title="AI MEDIA TOOLS" />
            <div className="lv-mc-tools-grid">
              {AI_TOOLS.map((tool) => (
                <button
                  key={tool.title}
                  type="button"
                  className="lv-mc-tool-card"
                  onClick={() => toast(tool.title)}
                >
                  <span className="lv-mc-tool-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24">
                      <ToolIcon kind={tool.icon} />
                    </svg>
                  </span>
                  <strong>{tool.title}</strong>
                  <small>{tool.desc}</small>
                </button>
              ))}
            </div>
          </section>

          <div className="lv-mc-bot-stack">
            <section className="lv-mc-panel">
              <SectionTitle n={9} title="SYSTEM USAGE / WORKFLOW HEALTH" />
              <div className="lv-mc-usage">
                {USAGE.map((row) => (
                  <div key={row.label} className="lv-mc-usage-row">
                    <div className="lv-mc-usage-meta">
                      <span>{row.label}</span>
                      <em>{row.detail}</em>
                    </div>
                    <div className="lv-mc-prog-track">
                      <span style={{ width: `${row.value}%` }} />
                    </div>
                  </div>
                ))}
              </div>
              <div className="lv-mc-nominal">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12.5l4.2 4.2L19 7.5" />
                </svg>
                All Systems Nominal
              </div>
            </section>

            <section className="lv-mc-panel">
              <div className="lv-mc-panel-bar">
                <SectionTitle n={10} title="LOGS / EVENT TIMELINE" />
                <span className="lv-mc-live">
                  <i /> Live
                </span>
              </div>
              <ul className="lv-mc-logs">
                {LOGS.map((log) => (
                  <li key={log.time + log.text}>
                    <time>{log.time}</time>
                    <span className={`lv-mc-log-dot is-${log.tone}`} />
                    <span className="lv-mc-log-text">{log.text}</span>
                    <PlatformIcon platform={log.platform} className="is-sm" />
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
