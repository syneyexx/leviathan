import { BrandMark } from "../../components/BrandMark";
import {
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

const TILES = platformTiles.instagram;
const GROWTH = [1.05, 1.08, 1.1, 1.12, 1.14, 1.16, 1.18, 1.2, 1.21, 1.22, 1.23, 1.24];

const LOCATIONS = [
  { name: "United States", pct: 28 },
  { name: "United Kingdom", pct: 12 },
  { name: "Canada", pct: 8 },
  { name: "Germany", pct: 7 },
  { name: "Netherlands", pct: 5 },
] as const;

const AGES = [
  { name: "18-24", pct: 22 },
  { name: "25-34", pct: 34 },
  { name: "35-44", pct: 42 },
  { name: "45-54", pct: 18 },
] as const;

const REELS = [
  { views: "2.4M", growth: "+38%", thumb: TILES[0] },
  { views: "1.8M", growth: "+24%", thumb: TILES[1] },
  { views: "1.1M", growth: "+17%", thumb: TILES[2] },
] as const;

const STORIES = [
  { title: "Ideas Today", eng: "186K", thumb: TILES[3] },
  { title: "Behind the Build", eng: "142K", thumb: TILES[4] },
  { title: "Q&A Live", eng: "98K", thumb: TILES[5] },
] as const;

const DMS = [
  { name: "Alex R.", preview: "Collab on the Higher Humanity series?", time: "2m", unread: true },
  { name: "Sophia K.", preview: "Logo pack looks incredible.", time: "12m", unread: false },
  { name: "Creator Agency", preview: "Brand deal draft attached.", time: "1h", unread: false },
  { name: "Marcus V.", preview: "Can we reuse Reel #3?", time: "3h", unread: false },
  { name: "Nova Lab", preview: "Story frame feedback inside.", time: "5h", unread: false },
] as const;

const POSTS = [
  { title: "Vision Grid", likes: "186K", comments: "4.2K", date: "Oct 24", thumb: TILES[0] },
  { title: "Civilization Still", likes: "142K", comments: "3.1K", date: "Oct 22", thumb: TILES[1] },
  { title: "Orbital Portrait", likes: "118K", comments: "2.4K", date: "Oct 20", thumb: TILES[2] },
] as const;

const CALENDAR = [
  { date: "Oct 29", type: "Reel", title: "Discipline Cut", status: "Scheduled" },
  { date: "Oct 30", type: "Carousel", title: "Aesthetic Thesis", status: "Scheduled" },
  { date: "Oct 31", type: "Story", title: "Behind Scenes", status: "Draft" },
  { date: "Nov 1", type: "Reel", title: "AI Civilization", status: "Scheduled" },
  { date: "Nov 2", type: "Post", title: "Brand Still", status: "Draft" },
] as const;

const HASHTAGS = [
  { tag: "#HigherHumanity", posts: "2.4M", growth: "+22%" },
  { tag: "#LeviathanVisuals", posts: "860K", growth: "+18%" },
  { tag: "#CivilizationDesign", posts: "420K", growth: "+31%" },
  { tag: "#AestheticProtocol", posts: "210K", growth: "+14%" },
] as const;

const DEALS = [
  { brand: "Neural Minds", type: "Sponsored Reel", status: "In Talks" },
  { brand: "Apex Protocol", type: "Story Series", status: "Contract Sent" },
  { brand: "Tomorrow Labs", type: "Feed Takeover", status: "Active" },
] as const;

export function InstagramPage() {
  const toast = useAppToast();

  return (
    <MediaPlatformShell
      activePlatform="instagram"
      searchPlaceholder="Search content, hashtags, captions, or anything..."
      createAccent="gold"
      promo={{ platform: "instagram", caption: "Visuals move people. Ideas change the world." }}
    >
      <div className="mp-page">
        <section className="mp-hero">
          <div className="mp-hero-media">
            <img src={mediaControlCrops.instagramHero} alt="" />
          </div>
          <div className="mp-hero-shade" />
          <div className="mp-hero-content">
            <div className="mp-hero-icon">
              <PlatformIcon platform="instagram" />
            </div>
            <div className="mp-hero-copy">
              <h1 className="mp-hero-title">Instagram Control</h1>
              <div className="mp-hero-flow">Visuals — Community — Culture — Impact</div>
            </div>
            <div className="mp-hero-quotes">
              <span>Beauty builds belief.</span>
              <span>A more human tomorrow. — Leviathan</span>
            </div>
          </div>
        </section>

        <section className="mp-profile">
          <div className="mp-profile-avatar">
            <BrandMark id="ig-profile" />
          </div>
          <div className="mp-profile-meta">
            <div className="mp-profile-name">
              LEVIATHAN <VerifiedBadge />
            </div>
            <div className="mp-profile-handle">@leviathanofficial</div>
            <div className="mp-profile-bio">Vision · Technology · Civilization · Aesthetics</div>
            <div className="mp-list-meta" style={{ marginTop: 4 }}>
              A higher humanity through greater minds.
            </div>
          </div>
          <div className="mp-profile-actions">
            <button className="mp-btn" type="button" onClick={() => toast("View Profile")}>
              View Profile
            </button>
            <button className="mp-btn" type="button" onClick={() => toast("Profile Settings")}>
              Profile Settings
            </button>
          </div>
        </section>

        <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(6, minmax(0,1fr))" }}>
          <MetricCard label="Followers" value="1.24M" absolute="+18.2K" percent="+1.5%" sparkline={GROWTH} sparkStroke="#20dc8c" />
          <MetricCard label="Reach" value="4.8M" percent="+27%" sparkline={[2, 2.4, 2.8, 3.2, 3.6, 4, 4.4, 4.8]} sparkStroke="#c5a059" />
          <MetricCard label="Impressions" value="12.6M" percent="+32%" sparkline={[6, 7, 8, 9, 10, 11, 12, 12.6]} sparkStroke="#c5a059" />
          <MetricCard label="Engagement Rate" value="6.8%" percent="+1.4%" sparkline={[4.8, 5.1, 5.4, 5.8, 6.1, 6.4, 6.6, 6.8]} sparkStroke="#20dc8c" />
          <MetricCard label="Saves" value="186.4K" percent="+28%" sparkline={[100, 120, 130, 145, 155, 170, 180, 186]} sparkStroke="#c5a059" />
          <MetricCard label="Profile Visits" value="342.1K" percent="+19%" sparkline={[200, 230, 250, 270, 290, 310, 330, 342]} sparkStroke="#20dc8c" />
        </div>

        <div className="mp-grid-3">
          <Panel title="Audience Growth">
            <LineChart series={[{ id: "f", color: "#22c9d6", values: GROWTH }]} labels={["Oct 1", "Oct 8", "Oct 15", "Oct 22", "Oct 28"]} height={150} />
            <div className="mp-grid-2" style={{ marginTop: 10, gridTemplateColumns: "1fr 1fr" }}>
              <div className="mp-stack">
                <div className="mp-list-title">Top Locations</div>
                {LOCATIONS.map((l) => (
                  <div key={l.name} className="mp-bar-row">
                    <span>{l.name}</span>
                    <div className="mp-bar-track">
                      <div className="mp-bar-fill" style={{ width: `${l.pct * 2}%` }} />
                    </div>
                    <span>{l.pct}%</span>
                  </div>
                ))}
              </div>
              <div className="mp-stack">
                <div className="mp-list-title">Top Age Range</div>
                {AGES.map((a) => (
                  <div key={a.name} className="mp-bar-row">
                    <span>{a.name}</span>
                    <div className="mp-bar-track">
                      <div className="mp-bar-fill" style={{ width: `${a.pct * 2}%` }} />
                    </div>
                    <span>{a.pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          </Panel>

          <Panel title="Reels & Story Performance">
            <div className="mp-list-title" style={{ marginBottom: 6 }}>
              Reels
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8 }}>
              {REELS.map((r) => (
                <div key={r.views} className="mp-ab-card">
                  <img src={r.thumb} alt="" />
                  <div className="mp-ab-meta">
                    <strong>{r.views}</strong>
                    <GrowthDelta percent={r.growth} />
                  </div>
                </div>
              ))}
            </div>
            <div className="mp-list-title" style={{ margin: "10px 0 6px" }}>
              Stories
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8 }}>
              {STORIES.map((s) => (
                <div key={s.title} className="mp-ab-card">
                  <img src={s.thumb} alt="" style={{ aspectRatio: "9/16" }} />
                  <div className="mp-ab-meta">
                    <div className="mp-list-title">{s.title}</div>
                    <div className="mp-list-meta">{s.eng}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Inbox & DMs">
            <div className="mp-list">
              {DMS.map((d) => (
                <div key={d.name} className="mp-list-row">
                  {d.unread ? <span className="mp-status-dot" data-tone="teal" style={{ marginTop: 0 }} /> : <span style={{ width: 7 }} />}
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{d.name}</div>
                    <div className="mp-list-meta">{d.preview}</div>
                  </div>
                  <span className="mp-list-meta">{d.time}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-4">
          <Panel title="Top Performing Posts">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8 }}>
              {POSTS.map((p) => (
                <div key={p.title} className="mp-ab-card">
                  <img src={p.thumb} alt="" style={{ aspectRatio: "1" }} />
                  <div className="mp-ab-meta">
                    <div className="mp-list-title">{p.title}</div>
                    <div className="mp-list-meta">
                      ♥ {p.likes} · 💬 {p.comments} · {p.date}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Content Calendar">
            <div className="mp-list">
              {CALENDAR.map((c) => (
                <div key={c.date + c.title} className="mp-list-row">
                  <div style={{ width: 52, fontSize: 11, color: "var(--mp-gold)" }}>{c.date}</div>
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{c.title}</div>
                    <div className="mp-list-meta">{c.type}</div>
                  </div>
                  <span className={`mp-badge ${c.status === "Scheduled" ? "is-green" : "is-muted"}`}>{c.status}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Post Scheduler">
            <textarea className="mp-textarea" placeholder="Share something with the world..." />
            <div className="mp-tabs" style={{ marginTop: 8 }}>
              {["Post", "Reel", "Story", "Carousel"].map((t, i) => (
                <button key={t} type="button" className={`mp-tab${i === 1 ? " is-active" : ""}`} onClick={() => toast(t)}>
                  {t}
                </button>
              ))}
            </div>
            <button className="mp-btn mp-btn-solid" type="button" style={{ marginTop: 10, width: "100%", justifyContent: "center" }} onClick={() => toast("Schedule")}>
              Schedule
            </button>
          </Panel>

          <Panel title="Hashtag Insights">
            <div className="mp-list">
              {HASHTAGS.map((h) => (
                <div key={h.tag} className="mp-list-row">
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{h.tag}</div>
                    <div className="mp-list-meta">{h.posts} posts</div>
                  </div>
                  <GrowthDelta percent={h.growth} />
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-3">
          <Panel title="Aesthetic Feed Planner" action={<span className="mp-list-meta">Drag to reorder</span>}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6 }}>
              {TILES.map((t, i) => (
                <img key={i} src={t} alt="" style={{ width: "100%", aspectRatio: "1", objectFit: "cover", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)" }} />
              ))}
            </div>
          </Panel>

          <Panel
            title="Visual Asset Library"
            action={
              <div className="mp-tabs">
                {["All", "Images", "Reels"].map((t, i) => (
                  <button key={t} type="button" className={`mp-tab${i === 0 ? " is-active" : ""}`}>
                    {t}
                  </button>
                ))}
              </div>
            }
          >
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6 }}>
              {TILES.slice(0, 4).map((t, i) => (
                <img key={i} src={t} alt="" className="mp-thumb square" style={{ width: "100%", height: "auto", aspectRatio: "1" }} />
              ))}
            </div>
          </Panel>

          <Panel title="Collaborations & Brand Deals">
            <div className="mp-list">
              {DEALS.map((d) => (
                <div key={d.brand} className="mp-list-row">
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{d.brand}</div>
                    <div className="mp-list-meta">{d.type}</div>
                  </div>
                  <span className={`mp-badge ${d.status === "Active" ? "is-green" : d.status === "Contract Sent" ? "is-gold" : "is-muted"}`}>{d.status}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </MediaPlatformShell>
  );
}
