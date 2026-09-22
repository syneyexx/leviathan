import { useState } from "react";
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
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";

const TILES = platformTiles.instagram;
const GROWTH = [0.82, 0.88, 0.9, 0.96, 1.02, 1.05, 1.1, 1.14, 1.16, 1.19, 1.22, 1.24];

const LOCATIONS = [
  { name: "United States", pct: 28 },
  { name: "United Kingdom", pct: 12 },
  { name: "Canada", pct: 8 },
  { name: "Germany", pct: 6 },
  { name: "Australia", pct: 5 },
] as const;

const AGES = [
  { name: "18-24", pct: 34 },
  { name: "25-34", pct: 42 },
  { name: "35-44", pct: 16 },
  { name: "45+", pct: 8 },
] as const;

const REELS = [
  { title: "A Higher Humanity", views: "2.4M", growth: "+38%", thumb: TILES[0] },
  { title: "Beauty Builds Belief", views: "1.8M", growth: "+24%", thumb: mediaControlCrops.instagramReel1 },
  { title: "Ideas That Scale", views: "1.1M", growth: "+17%", thumb: TILES[1] },
] as const;

const STORIES = [
  { title: "Ideas Today…", eng: "186K", growth: "+12%", thumb: TILES[2] },
  { title: "Behind the Build", eng: "142K", growth: "+9%", thumb: TILES[3] },
  { title: "Q&A", eng: "98K", growth: "+6%", thumb: TILES[4] },
] as const;

const DMS = [
  { name: "Alex R.", preview: "Collab on the Higher Humanity series?", time: "2m", unread: true },
  { name: "Sophia K.", preview: "Love your latest reel! 🔥", time: "12m", unread: false },
  { name: "Creator Agency", preview: "Brand deal draft attached.", time: "1h", unread: false },
  { name: "Daniel M.", preview: "Can we feature Leviathan next week?", time: "3h", unread: false },
  { name: "Bella C.", preview: "The aesthetics on this feed…", time: "5h", unread: false },
] as const;

const POSTS = [
  { title: "A Higher Humanity Is Possible", likes: "248K", comments: "4.2K", date: "Oct 14, 2024", thumb: TILES[0] },
  { title: "Discipline Creates Worlds", likes: "196K", comments: "3.1K", date: "Oct 11, 2024", thumb: TILES[1] },
  { title: "Visuals Move People", likes: "174K", comments: "2.8K", date: "Oct 8, 2024", thumb: TILES[5] },
] as const;

const CALENDAR = [
  { date: "Oct 29", type: "Reel", title: "Higher Minds Series", time: "10:00 AM", status: "Scheduled" },
  { date: "Oct 30", type: "Carousel", title: "Civilization Frames", time: "2:00 PM", status: "Scheduled" },
  { date: "Oct 31", type: "Story", title: "Studio Walkthrough", time: "6:00 PM", status: "Draft" },
  { date: "Nov 1", type: "Reel", title: "Beauty Builds Belief", time: "11:00 AM", status: "Scheduled" },
  { date: "Nov 2", type: "Post", title: "A More Human Tomorrow", time: "4:00 PM", status: "Draft" },
] as const;

const HASHTAGS = [
  { tag: "#HigherHumanity", reach: "2.4M", growth: "+18%" },
  { tag: "#AI", reach: "1.8M", growth: "+22%" },
  { tag: "#FutureOfWork", reach: "964K", growth: "+14%" },
  { tag: "#Leviathan", reach: "812K", growth: "+31%" },
  { tag: "#VisualCulture", reach: "640K", growth: "+9%" },
  { tag: "#Civilization", reach: "428K", growth: "+11%" },
] as const;

const DEALS = [
  { brand: "Neural Minds", type: "Strategic Partnership", status: "In Talks" },
  { brand: "Apex Protocol", type: "Sponsored Content", status: "Contract Sent" },
  { brand: "Tomorrow Labs", type: "Product Collaboration", status: "Active" },
] as const;

const SCHEDULER_TABS = ["Post", "Reel", "Story", "Carousel"] as const;
const ASSET_TABS = ["All", "Images", "Reels", "Templates", "Brand", "AI Assets"] as const;

export function InstagramPage() {
  const toast = useAppToast();
  const [schedulerTab, setSchedulerTab] = useState<(typeof SCHEDULER_TABS)[number]>("Reel");
  const [assetTab, setAssetTab] = useState<(typeof ASSET_TABS)[number]>("All");
  const [composer, setComposer] = useState("");

  const feedCells = [...TILES, mediaControlCrops.instagramReel1, TILES[0], TILES[1]].slice(0, 8);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Media Mode"
      searchPlaceholder="Search content, hashtags, captions, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--media-platform"
    >
      <main className="lv-main mp-main-in-shell" data-accent="gold">
      <div className="mp-page mp-ig">
        <section className="mp-hero mp-ig-hero">
          <div className="mp-hero-media">
            <img src={mediaControlCrops.instagramHero} alt="" draggable={false} />
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
        <section className="mp-profile mp-ig-profile">
          <div className="mp-profile-avatar">
            <BrandMark id="ig-profile" />
          </div>
          <div className="mp-profile-meta">
            <div className="mp-profile-name">
              LEVIATHAN <VerifiedBadge />
            </div>
            <div className="mp-profile-handle">@leviathanofficial</div>
            <div className="mp-ig-tags">Vision • Technology • Civilization • Aesthetics</div>
            <div className="mp-profile-bio">A higher humanity through greater minds.</div>
          </div>
          <div className="mp-profile-actions">
            <button className="mp-btn" type="button" onClick={() => toast("View Profile")}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M14 5h5v5M19 5l-9 9M10 5H5v14h14v-5" />
              </svg>
              View Profile
            </button>
            <button className="mp-btn" type="button" onClick={() => toast("Profile Settings")}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6.1 6.1l1.6 1.6M16.3 16.3l1.6 1.6M17.9 6.1l-1.6 1.6M7.7 16.3l-1.6 1.6" />
              </svg>
              Profile Settings
            </button>
          </div>
        </section>

        <div className="mp-metrics mp-ig-metrics">
          <MetricCard label="Followers" value="1.24M" absolute="+18.2K" percent="+1.5%" sparkline={GROWTH} sparkStroke="#20dc8c" />
          <MetricCard label="Reach" value="4.8M" percent="+27%" sparkline={[2, 2.4, 2.8, 3.2, 3.6, 4, 4.4, 4.8]} sparkStroke="#20dc8c" />
          <MetricCard label="Impressions" value="12.6M" percent="+32%" sparkline={[6, 7, 8, 9, 10, 11, 12, 12.6]} sparkStroke="#d6a957" />
          <MetricCard label="Engagement Rate" value="6.8%" percent="+1.4%" sparkline={[4.8, 5.1, 5.4, 5.8, 6.1, 6.4, 6.6, 6.8]} sparkStroke="#20dc8c" />
          <MetricCard label="Saves" value="186.4K" percent="+28%" sparkline={[100, 120, 130, 145, 155, 170, 180, 186]} sparkStroke="#d6a957" />
          <MetricCard label="Profile Visits" value="342.1K" percent="+19%" sparkline={[200, 230, 250, 270, 290, 310, 330, 342]} sparkStroke="#20dc8c" />
        </div>

        <div className="mp-grid-3 mp-ig-mid">
          <Panel
            title="Audience Growth"
            action={
              <button type="button" className="mp-ig-range" onClick={() => toast("Last 28 days")}>
                Last 28 days
              </button>
            }
          >
            <LineChart
              series={[{ id: "f", color: "#20dc8c", fill: "rgba(32,220,140,0.14)", values: GROWTH }]}
              labels={["Oct 1", "Oct 8", "Oct 15", "Oct 22", "Oct 28"]}
              height={150}
              marker={{ index: 11, label: "1.24M followers" }}
            />
            <div className="mp-ig-demo-cols">
              <div className="mp-stack">
                <div className="mp-ig-subhead">Top Locations</div>
                {LOCATIONS.map((l) => (
                  <div key={l.name} className="mp-bar-row">
                    <span>{l.name}</span>
                    <div className="mp-bar-track">
                      <div className="mp-bar-fill" style={{ width: `${Math.min(100, l.pct * 2.4)}%` }} />
                    </div>
                    <span>{l.pct}%</span>
                  </div>
                ))}
              </div>
              <div className="mp-stack">
                <div className="mp-ig-subhead">Top Age Range</div>
                {AGES.map((a) => (
                  <div key={a.name} className="mp-bar-row">
                    <span>{a.name}</span>
                    <div className="mp-bar-track">
                      <div className="mp-bar-fill" style={{ width: `${Math.min(100, a.pct * 2)}%` }} />
                    </div>
                    <span>{a.pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          </Panel>

          <Panel title="Reels & Story Performance">
            <div className="mp-ig-subhead">Reels</div>
            <div className="mp-ig-thumb-grid">
              {REELS.map((r) => (
                <button key={r.title} type="button" className="mp-ig-media-card" onClick={() => toast(r.title)}>
                  <img src={r.thumb} alt="" draggable={false} />
                  <div className="mp-ig-media-meta">
                    <strong>{r.views}</strong>
                    <span>{r.title}</span>
                    <GrowthDelta percent={r.growth} />
                  </div>
                </button>
              ))}
            </div>
            <div className="mp-ig-subhead" style={{ marginTop: 10 }}>
              Stories
            </div>
            <div className="mp-ig-thumb-grid">
              {STORIES.map((s) => (
                <button key={s.title} type="button" className="mp-ig-media-card is-story" onClick={() => toast(s.title)}>
                  <img src={s.thumb} alt="" draggable={false} />
                  <div className="mp-ig-media-meta">
                    <strong>{s.eng}</strong>
                    <span>{s.title}</span>
                    <GrowthDelta percent={s.growth} />
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Inbox & DMs">
            <div className="mp-list">
              {DMS.map((d) => (
                <button key={d.name} type="button" className="mp-ig-dm-row" onClick={() => toast(`DM · ${d.name}`)}>
                  {d.unread ? <span className="mp-status-dot" data-tone="teal" /> : <span className="mp-ig-dm-spacer" />}
                  <div className="mp-ig-dm-av" aria-hidden="true">
                    {d.name.slice(0, 1)}
                  </div>
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{d.name}</div>
                    <div className="mp-list-meta">{d.preview}</div>
                  </div>
                  <span className="mp-list-meta">{d.time}</span>
                </button>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-4 mp-ig-lower">
          <Panel title="Top Performing Posts">
            <div className="mp-ig-posts-grid">
              {POSTS.map((p) => (
                <button key={p.title} type="button" className="mp-ig-media-card is-post" onClick={() => toast(p.title)}>
                  <img src={p.thumb} alt="" draggable={false} />
                  <div className="mp-ig-media-meta">
                    <strong>{p.title}</strong>
                    <span>
                      ♥ {p.likes} · 💬 {p.comments}
                    </span>
                    <em>{p.date}</em>
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Content Calendar">
            <div className="mp-list">
              {CALENDAR.map((c) => (
                <button key={c.date + c.title} type="button" className="mp-ig-cal-row" onClick={() => toast(c.title)}>
                  <div className="mp-ig-cal-date">{c.date}</div>
                  <div className="mp-list-copy">
                    <div className="mp-list-title">
                      {c.type} · {c.title}
                    </div>
                    <div className="mp-list-meta">{c.time}</div>
                  </div>
                  <span className={`mp-badge ${c.status === "Scheduled" ? "is-green" : "is-muted"}`}>{c.status}</span>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Post Scheduler">
            <div className="mp-tabs mp-ig-tabs">
              {SCHEDULER_TABS.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`mp-tab${schedulerTab === t ? " is-active" : ""}`}
                  onClick={() => setSchedulerTab(t)}
                >
                  {t}
                </button>
              ))}
            </div>
            <textarea
              className="mp-textarea"
              placeholder="Share something with the world..."
              value={composer}
              onChange={(e) => setComposer(e.target.value)}
              aria-label="Post caption"
            />
            <div className="mp-ig-composer-bar">
              <div className="mp-ig-attach">
                {(["Image", "Video", "Emoji", "Location"] as const).map((label) => (
                  <button key={label} type="button" aria-label={label} onClick={() => toast(label)}>
                    {label === "Image" ? "🖼" : label === "Video" ? "▶" : label === "Emoji" ? "☺" : "⌖"}
                  </button>
                ))}
              </div>
              <button
                className="mp-btn mp-btn-solid mp-ig-schedule-btn"
                type="button"
                onClick={() => toast(`Schedule ${schedulerTab}`)}
              >
                Schedule
              </button>
            </div>
          </Panel>

          <Panel title="Hashtag Insights">
            <div className="mp-list">
              {HASHTAGS.map((h) => (
                <button key={h.tag} type="button" className="mp-ig-hash-row" onClick={() => toast(h.tag)}>
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{h.tag}</div>
                    <div className="mp-list-meta">{h.reach} reach</div>
                  </div>
                  <GrowthDelta percent={h.growth} />
                </button>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-3 mp-ig-footer">
          <Panel title="Aesthetic Feed Planner" action={<span className="mp-list-meta">Drag to reorder</span>}>
            <div className="mp-ig-feed-grid">
              {feedCells.map((t, i) => (
                <button key={i} type="button" className="mp-ig-feed-cell" onClick={() => toast(`Feed cell ${i + 1}`)}>
                  <img src={t} alt="" draggable={false} />
                </button>
              ))}
              <button type="button" className="mp-ig-feed-add" onClick={() => toast("Add feed asset")}>
                +
              </button>
            </div>
          </Panel>

          <Panel
            title="Visual Asset Library"
            action={
              <div className="mp-tabs mp-ig-tabs is-compact">
                {ASSET_TABS.map((t) => (
                  <button
                    key={t}
                    type="button"
                    className={`mp-tab${assetTab === t ? " is-active" : ""}`}
                    onClick={() => {
                      setAssetTab(t);
                      toast(`${t} assets`);
                    }}
                  >
                    {t}
                  </button>
                ))}
              </div>
            }
          >
            <div className="mp-ig-asset-strip">
              {[...TILES, mediaControlCrops.instagramPoster, mediaControlCrops.instagramReel1].map((t, i) => (
                <button key={i} type="button" className="mp-ig-asset-cell" onClick={() => toast(`${assetTab} asset ${i + 1}`)}>
                  <img src={t} alt="" draggable={false} />
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Collaborations & Brand Deals">
            <div className="mp-list">
              {DEALS.map((d) => (
                <button key={d.brand} type="button" className="mp-ig-deal-row" onClick={() => toast(d.brand)}>
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{d.brand}</div>
                    <div className="mp-list-meta">{d.type}</div>
                  </div>
                  <span
                    className={`mp-badge ${
                      d.status === "Active" ? "is-green" : d.status === "Contract Sent" ? "is-gold" : "is-muted"
                    }`}
                  >
                    {d.status}
                  </span>
                </button>
              ))}
            </div>
          </Panel>
        </div>
      </div>
      </main>
    </AppShell>
  );
}
