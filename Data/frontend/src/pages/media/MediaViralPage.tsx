import { useState } from "react";
import { mediaPageArt, mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { Donut, PageHero, Panel, Pill, PlatformGlyph, Spark } from "./mr-shared";

type Platform = "youtube" | "tiktok" | "instagram" | "facebook";

type EmergingTrend = {
  id: string;
  topic: string;
  platforms: Platform[];
  growth: string;
  mentions: string;
  score: number;
};

const PLATFORM_HEAT: Array<{
  platform: Platform;
  label: string;
  growth: string;
  points: number[];
  color: string;
}> = [
  { platform: "youtube", label: "YouTube", growth: "+48%", points: [12, 18, 16, 24, 28, 32, 36, 42], color: "#ff0000" },
  { platform: "tiktok", label: "TikTok", growth: "+92%", points: [18, 24, 32, 40, 55, 62, 74, 88], color: "#fe2c55" },
  { platform: "instagram", label: "Instagram", growth: "+61%", points: [14, 20, 26, 34, 42, 48, 54, 60], color: "#dd2a7b" },
  { platform: "facebook", label: "Facebook", growth: "+23%", points: [8, 10, 12, 14, 16, 18, 20, 24], color: "#1877f2" },
];

const EMERGING: EmergingTrend[] = [
  {
    id: "t1",
    topic: "AI Pet Videos",
    platforms: ["tiktok", "instagram", "youtube"],
    growth: "+820%",
    mentions: "128K",
    score: 94,
  },
  {
    id: "t2",
    topic: "Cozy Productivity",
    platforms: ["instagram", "tiktok"],
    growth: "+640%",
    mentions: "96K",
    score: 91,
  },
  {
    id: "t3",
    topic: "Retro Tech Unbox",
    platforms: ["youtube", "tiktok"],
    growth: "+510%",
    mentions: "74K",
    score: 87,
  },
  {
    id: "t4",
    topic: "Local AI Demos",
    platforms: ["youtube", "facebook"],
    growth: "+430%",
    mentions: "61K",
    score: 84,
  },
  {
    id: "t5",
    topic: "Travel Nature Reels",
    platforms: ["instagram", "tiktok"],
    growth: "+380%",
    mentions: "54K",
    score: 81,
  },
  {
    id: "t6",
    topic: "Founders Hook Stories",
    platforms: ["tiktok", "youtube", "instagram"],
    growth: "+310%",
    mentions: "41K",
    score: 78,
  },
];

const SOUNDS = [
  { title: "Neon Pulse Drop", growth: "+920%", platform: "tiktok" as Platform, points: [4, 10, 6, 14, 8, 16, 5, 12] },
  { title: "Lo-fi Desk Loop", growth: "+710%", platform: "instagram" as Platform, points: [6, 8, 12, 7, 14, 9, 11, 5] },
  { title: "Retro Click Kit", growth: "+580%", platform: "tiktok" as Platform, points: [5, 12, 8, 10, 15, 6, 13, 9] },
  { title: "Ocean Soft Pad", growth: "+460%", platform: "instagram" as Platform, points: [3, 7, 11, 6, 12, 8, 10, 14] },
  { title: "Founders Hook", growth: "+390%", platform: "tiktok" as Platform, points: [8, 5, 13, 9, 6, 15, 10, 7] },
];

const HASHTAGS = [
  { tag: "#aipet", growth: "+820%", posts: "128K", points: [20, 28, 35, 48, 62, 78, 90, 96] },
  { tag: "#cozyproductivity", growth: "+640%", posts: "96K", points: [18, 22, 30, 40, 55, 70, 82, 88] },
  { tag: "#localai", growth: "+510%", posts: "74K", points: [12, 18, 26, 34, 48, 60, 72, 80] },
  { tag: "#retrotech", growth: "+430%", posts: "61K", points: [10, 16, 22, 30, 42, 50, 58, 64] },
  { tag: "#naturereels", growth: "+380%", posts: "54K", points: [14, 18, 24, 28, 36, 44, 52, 58] },
];

const COMPETITORS = [
  { account: "NovaLabs", topic: "AI pets", mentions: "1.2K", growth: "+420%" },
  { account: "DeskCraft", topic: "Cozy desks", mentions: "980", growth: "+310%" },
  { account: "PixelForge", topic: "Local AI", mentions: "860", growth: "+280%" },
  { account: "TrailCut", topic: "Nature POV", mentions: "720", growth: "+210%" },
  { account: "RetroByte", topic: "Unboxing", mentions: "640", growth: "+190%" },
];

const MATRIX_DOTS = [
  { label: "AI Pets", x: 78, y: 22, size: 18, color: "#22c9d6" },
  { label: "Cozy Desk", x: 62, y: 38, size: 14, color: "#a78bfa" },
  { label: "Retro", x: 48, y: 52, size: 12, color: "#f0c875" },
  { label: "Local AI", x: 70, y: 58, size: 11, color: "#4ade80" },
  { label: "Nature", x: 36, y: 68, size: 10, color: "#f472b6" },
  { label: "Finance", x: 28, y: 42, size: 9, color: "#38bdf8" },
];

const WATCHLIST = [
  { topic: "AI Pet Videos", status: "Watching", tone: "cyan" as const },
  { topic: "Cozy Productivity", status: "Alert", tone: "gold" as const },
  { topic: "Local AI Demos", status: "Rising", tone: "green" as const },
  { topic: "Retro Tech Unbox", status: "Watching", tone: "cyan" as const },
  { topic: "Founders Hook", status: "Paused", tone: "muted" as const },
];

const ACTIONS = [
  "Publish 3 short-form hooks within 48h",
  "Pair with Neon Pulse Drop sound",
  "Target Gen-Z pet + AI niche overlap",
  "Seed #aipet on TT + IG Stories",
];

export function MediaViralPage() {
  const toast = useAppToast();
  const [selectedId, setSelectedId] = useState("t1");
  const selected = EMERGING.find((t) => t.id === selectedId) ?? EMERGING[0];

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Viral Mode"
      searchPlaceholder="Search trends, creators, topics, competitors, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--media-research"
    >
      <main className="lv-main lv-mr-main">
        <PageHero image={mediaPageHeroes.viral} title="VIRAL RADAR — Spot signals, predict momentum." imageOnly />

        <section className="lv-mv-grid">
          <Panel title="Global Trend Map">
            <div className="lv-mv-map">
              <img src={mediaPageArt.viralMap} alt="" />
              <div className="lv-mv-map-stats">
                <div className="lv-mv-map-stat">
                  Viral Signals
                  <strong>421</strong>
                </div>
                <div className="lv-mv-map-stat">
                  Emerging
                  <strong>1.8K</strong>
                </div>
                <div className="lv-mv-map-stat">
                  Hot Zones
                  <strong>37</strong>
                </div>
                <div className="lv-mv-map-stat">
                  Velocity
                  <strong>+612%</strong>
                </div>
              </div>
            </div>
          </Panel>

          <Panel title="Platform Heat">
            {PLATFORM_HEAT.map((row) => (
              <div key={row.platform} className="lv-mv-heat-row">
                <PlatformGlyph platform={row.platform} />
                <span>{row.label}</span>
                <span className="lv-mr-good">{row.growth}</span>
                <Spark points={row.points} color={row.color} width={64} height={20} />
              </div>
            ))}
          </Panel>

          <div style={{ display: "grid", gap: 10 }}>
            <Panel title="Sentiment">
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <Donut
                  size={110}
                  center="72%"
                  slices={[
                    { value: 62, color: "#4ade80" },
                    { value: 24, color: "#f0c875" },
                    { value: 14, color: "#f87171" },
                  ]}
                />
                <div style={{ display: "grid", gap: 6, fontSize: 12 }}>
                  <div>
                    <Pill tone="green">Positief 62%</Pill>
                  </div>
                  <div>
                    <Pill tone="gold">Neutraal 24%</Pill>
                  </div>
                  <div>
                    <Pill tone="red">Negatief 14%</Pill>
                  </div>
                </div>
              </div>
            </Panel>
            <Panel title="Growth Velocity">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                <span className="lv-mr-muted" style={{ fontSize: 11 }}>
                  7-day momentum
                </span>
                <strong className="lv-mr-good" style={{ fontSize: 18 }}>
                  +612%
                </strong>
              </div>
              <Spark points={[22, 28, 35, 42, 55, 68, 74, 88]} color="#22c9d6" width={220} height={36} />
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 11 }} className="lv-mr-muted">
                <span>10 sep</span>
                <span>17 sep</span>
              </div>
            </Panel>
          </div>
        </section>

        <section className="lv-mr-split">
          <div style={{ display: "grid", gap: 10, minWidth: 0 }}>
            <Panel
              title="Emerging Trends"
              action={
                <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast("Trends vernieuwen")}>
                  Vernieuwen
                </button>
              }
            >
              <div className="lv-mv-trend-row" style={{ color: "#8ea3af", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                <span>Topic</span>
                <span>Platforms</span>
                <span>Growth</span>
                <span>Mentions</span>
                <span>Opportunity</span>
              </div>
              {EMERGING.map((trend) => (
                <button
                  key={trend.id}
                  type="button"
                  className="lv-mv-trend-row"
                  onClick={() => setSelectedId(trend.id)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    background: trend.id === selected.id ? "rgba(34, 201, 214, 0.08)" : "transparent",
                    border: 0,
                    color: "inherit",
                    cursor: "pointer",
                    borderRadius: 4,
                  }}
                >
                  <strong style={{ color: "#f0ebe3" }}>{trend.topic}</strong>
                  <div className="lv-mr-plat-row">
                    {trend.platforms.map((p) => (
                      <PlatformGlyph key={p} platform={p} />
                    ))}
                  </div>
                  <span className="lv-mr-good">{trend.growth}</span>
                  <span>{trend.mentions}</span>
                  <Pill tone={trend.score >= 90 ? "gold" : trend.score >= 80 ? "cyan" : "muted"}>{trend.score}</Pill>
                </button>
              ))}
            </Panel>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <Panel title="Trending Sounds">
                {SOUNDS.map((s) => (
                  <div key={s.title} className="lv-mv-heat-row">
                    <PlatformGlyph platform={s.platform} />
                    <div>
                      <div style={{ color: "#f0ebe3" }}>{s.title}</div>
                      <span className="lv-mr-good" style={{ fontSize: 11 }}>
                        {s.growth}
                      </span>
                    </div>
                    <span />
                    <Spark points={s.points} color="#fe2c55" width={56} height={18} />
                  </div>
                ))}
              </Panel>
              <Panel title="Breakout Hashtags">
                {HASHTAGS.map((h) => (
                  <div key={h.tag} className="lv-mv-heat-row">
                    <span style={{ color: "#5b9fd4", gridColumn: "1 / 3" }}>{h.tag}</span>
                    <span className="lv-mr-good">{h.growth}</span>
                    <span className="lv-mr-muted">{h.posts}</span>
                  </div>
                ))}
              </Panel>
            </div>
          </div>

          <Panel
            title="SELECTED TREND"
            action={<Pill tone="gold">HOT</Pill>}
          >
            <div className="lv-mv-detail-hero">
              <img src={mediaPageArt.viralTrendHero} alt="" />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, gap: 12 }}>
              <div>
                <strong style={{ color: "#f0ebe3", fontSize: 16 }}>{selected.topic}</strong>
                <div className="lv-mr-muted" style={{ fontSize: 12, marginTop: 4 }}>
                  Spot signals · predict momentum
                </div>
              </div>
              <div className="lv-mv-score" title="Viral score">
                9.2
              </div>
            </div>

            <div className="lv-mq-meta" style={{ marginTop: 12 }}>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Platforms</span>
                <div className="lv-mr-plat-row">
                  {selected.platforms.map((p) => (
                    <PlatformGlyph key={p} platform={p} />
                  ))}
                </div>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Growth</span>
                <strong className="lv-mr-good">{selected.growth}</strong>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Mentions</span>
                <strong>{selected.mentions}</strong>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Opportunity</span>
                <Pill tone="gold">{selected.score}/100</Pill>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Audience</span>
                <span>Gen-Z · Pets · AI creators · 18–34</span>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Peak window</span>
                <span>Next 36–72h</span>
              </div>
            </div>

            <div style={{ marginTop: 14 }}>
              <div className="lv-mr-panel-title" style={{ marginBottom: 8 }}>
                Recommended Actions
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, lineHeight: 1.55, color: "#c8d4dc" }}>
                {ACTIONS.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>

            <div className="lv-mq-actions">
              <button
                type="button"
                className="lv-mr-btn lv-mr-btn--gold"
                onClick={() => toast("Generate Content Strategy")}
              >
                Generate Content Strategy
              </button>
              <div className="lv-mq-actions-row">
                <button type="button" className="lv-mr-btn" style={{ flex: 1 }} onClick={() => toast("Alert instellen")}>
                  Alert
                </button>
                <button type="button" className="lv-mr-btn" style={{ flex: 1 }} onClick={() => toast("Watchlist")}>
                  Watchlist
                </button>
              </div>
            </div>
          </Panel>
        </section>

        <section className="lv-mv-bottom">
          <Panel title="Competitor Surges">
            <div className="lv-mv-heat-row" style={{ color: "#8ea3af", fontSize: 10, textTransform: "uppercase" }}>
              <span />
              <span>Account / Topic</span>
              <span>Mentions</span>
              <span>Growth</span>
            </div>
            {COMPETITORS.map((c) => (
              <div key={c.account} className="lv-mv-heat-row">
                <span
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: "50%",
                    display: "grid",
                    placeItems: "center",
                    background: "rgba(34, 201, 214, 0.15)",
                    color: "#22c9d6",
                    fontSize: 10,
                    fontWeight: 700,
                  }}
                >
                  {c.account.slice(0, 2).toUpperCase()}
                </span>
                <div>
                  <div style={{ color: "#f0ebe3" }}>{c.account}</div>
                  <div className="lv-mr-muted" style={{ fontSize: 11 }}>
                    {c.topic}
                  </div>
                </div>
                <span>{c.mentions}</span>
                <span className="lv-mr-good">{c.growth}</span>
              </div>
            ))}
          </Panel>

          <Panel title="Opportunity Matrix">
            <div
              style={{
                position: "relative",
                height: 200,
                borderRadius: 8,
                border: "1px solid rgba(40, 60, 80, 0.45)",
                background:
                  "linear-gradient(180deg, rgba(8,14,20,0.9), rgba(4,8,12,0.95)), repeating-linear-gradient(0deg, transparent, transparent 39px, rgba(40,60,80,0.25) 40px), repeating-linear-gradient(90deg, transparent, transparent 39px, rgba(40,60,80,0.25) 40px)",
                overflow: "hidden",
              }}
            >
              <span className="lv-mr-muted" style={{ position: "absolute", left: 8, bottom: 6, fontSize: 10 }}>
                Reach →
              </span>
              <span className="lv-mr-muted" style={{ position: "absolute", left: 8, top: 6, fontSize: 10, writingMode: "vertical-rl", transform: "rotate(180deg)" }}>
                Velocity →
              </span>
              {MATRIX_DOTS.map((d) => (
                <button
                  key={d.label}
                  type="button"
                  title={d.label}
                  onClick={() => toast(d.label)}
                  style={{
                    position: "absolute",
                    left: `${d.x}%`,
                    top: `${d.y}%`,
                    width: d.size,
                    height: d.size,
                    marginLeft: -d.size / 2,
                    marginTop: -d.size / 2,
                    borderRadius: "50%",
                    border: "1px solid rgba(255,255,255,0.35)",
                    background: d.color,
                    boxShadow: `0 0 12px ${d.color}`,
                    cursor: "pointer",
                    padding: 0,
                  }}
                />
              ))}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8, fontSize: 11 }}>
              {MATRIX_DOTS.map((d) => (
                <span key={d.label} className="lv-mr-muted">
                  <span style={{ color: d.color }}>●</span> {d.label}
                </span>
              ))}
            </div>
          </Panel>

          <Panel
            title="Watchlist"
            action={
              <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast("Watchlist beheren")}>
                Beheer
              </button>
            }
          >
            {WATCHLIST.map((w) => (
              <div key={w.topic} className="lv-mv-heat-row">
                <span style={{ gridColumn: "1 / 3", color: "#f0ebe3" }}>{w.topic}</span>
                <Pill tone={w.tone}>{w.status}</Pill>
                <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast(`Open ${w.topic}`)}>
                  Open
                </button>
              </div>
            ))}
          </Panel>
        </section>
      </main>
    </AppShell>
  );
}
