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
import { MediaPlatformShell } from "../../layouts/MediaPlatformShell";
import { useAppToast } from "../../state/useAppToast";

const TILES = platformTiles.instagram;
const GROWTH = [0.82, 0.88, 0.9, 0.96, 1.02, 1.05, 1.1, 1.14, 1.16, 1.19, 1.22, 1.24];

const LOCATIONS = [
  { label: "United States", value: 28 },
  { label: "United Kingdom", value: 12 },
  { label: "Canada", value: 8 },
  { label: "Germany", value: 6 },
  { label: "Australia", value: 5 },
] as const;

const AGES = [
  { label: "18–24", value: 34 },
  { label: "25–34", value: 42 },
  { label: "35–44", value: 16 },
  { label: "45+", value: 8 },
] as const;

const REELS = [
  { thumb: TILES[0], views: "2.4M", title: "A Higher Humanity", delta: "+38%" },
  { thumb: mediaControlCrops.instagramReel1, views: "1.8M", title: "Beauty Builds Belief", delta: "+24%" },
  { thumb: TILES[1], views: "1.1M", title: "Ideas That Scale", delta: "+19%" },
] as const;

const STORIES = [
  { thumb: TILES[2], views: "186K", title: "Ideas Today…", delta: "+12%" },
  { thumb: TILES[3], views: "142K", title: "Behind the Build", delta: "+9%" },
  { thumb: TILES[4], views: "98K", title: "Q&A Live", delta: "+6%" },
] as const;

const INBOX = [
  { name: "Alex R.", preview: "Your latest reel is fire — collaboration?", time: "2m", avatar: TILES[0] },
  { name: "Sophia K.", preview: "Love your latest reel!", time: "14m", avatar: TILES[1] },
  { name: "Creator Agency", preview: "Brand brief attached for Nov.", time: "1h", avatar: TILES[2] },
  { name: "Daniel M.", preview: "Can we feature Leviathan next week?", time: "3h", avatar: TILES[3] },
  { name: "Bella C.", preview: "The aesthetics on this feed…", time: "5h", avatar: TILES[4] },
] as const;

const TOP_POSTS = [
  { thumb: TILES[0], title: "A Higher Humanity Is Possible", likes: "248K", comments: "4.2K", date: "Oct 14" },
  { thumb: TILES[1], title: "Discipline Creates Worlds", likes: "196K", comments: "3.1K", date: "Oct 11" },
  { thumb: TILES[5], title: "Visuals Move People", likes: "174K", comments: "2.8K", date: "Oct 8" },
] as const;

const CALENDAR = [
  { date: "Oct 29", type: "Reel", title: "Higher Minds Series", time: "10:00 AM", status: "Scheduled" as const },
  { date: "Oct 30", type: "Carousel", title: "Civilization Frames", time: "2:00 PM", status: "Scheduled" as const },
  { date: "Oct 31", type: "Story", title: "Studio Walkthrough", time: "6:00 PM", status: "Draft" as const },
  { date: "Nov 1", type: "Reel", title: "Beauty Builds Belief", time: "11:00 AM", status: "Scheduled" as const },
  { date: "Nov 2", type: "Post", title: "A More Human Tomorrow", time: "4:00 PM", status: "Draft" as const },
] as const;

const HASHTAGS = [
  { tag: "#HigherHumanity", reach: "2.4M", growth: "+18%" },
  { tag: "#AI", reach: "1.8M", growth: "+22%" },
  { tag: "#FutureOfWork", reach: "964K", growth: "+14%" },
  { tag: "#Leviathan", reach: "812K", growth: "+31%" },
  { tag: "#VisualCulture", reach: "640K", growth: "+9%" },
  { tag: "#Civilization", reach: "428K", growth: "+11%" },
] as const;

const COLLABS = [
  { partner: "Neural Minds", type: "Strategic Partnership", status: "In Talks" as const },
  { partner: "Apex Protocol", type: "Sponsored Content", status: "Contract Sent" as const },
  { partner: "Tomorrow Labs", type: "Product Collaboration", status: "Active" as const },
] as const;

const SCHEDULER_TABS = ["Post", "Reel", "Story", "Carousel"] as const;
const ASSET_TABS = ["All", "Images", "Reels", "Templates", "Brand", "AI Assets"] as const;
const FEED_CELLS = [...TILES, mediaControlCrops.instagramReel1, TILES[0], TILES[1]].slice(0, 9);
const ASSET_STRIP = [...TILES, mediaControlCrops.instagramPoster, mediaControlCrops.instagramReel1];

export function InstagramPage() {
  const toast = useAppToast();
  const [schedulerTab, setSchedulerTab] = useState<(typeof SCHEDULER_TABS)[number]>("Post");
  const [assetTab, setAssetTab] = useState<(typeof ASSET_TABS)[number]>("All");
  const [composer, setComposer] = useState("");

  return (
    <MediaPlatformShell
      activePlatform="instagram"
      searchPlaceholder="Search content, hashtags, captions, or anything..."
      createAccent="gold"
      promo={{ platform: "instagram", caption: "Visuals move people. Ideas change the world." }}
      sidebarCaption="Bigger audiences. A higher humanity."
      statusItems={[
        { label: "Profile Status", value: "Healthy" },
        { label: "Content Flow", value: "On Track" },
        { label: "Engagement", value: "Excellent" },
        { label: "Growth Trend", value: "+32%" },
      ]}
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
          <div className="mp-profile-avatar" aria-hidden="true">
            <BrandMark id="ig-profile" />
          </div>
          <div className="mp-profile-meta">
            <div className="mp-profile-name">
              LEVIATHAN <VerifiedBadge />
            </div>
            <div className="mp-profile-handle">@leviathanofficial</div>
            <div className="mp-profile-bio">Vision · Technology · Civilization · Aesthetics</div>
            <div className="mp-profile-bio" style={{ marginTop: 2 }}>
              A higher humanity through greater minds.
            </div>
          </div>
          <div className="mp-profile-actions">
            <button className="mp-btn" type="button" onClick={() => toast("View Profile")}>
              View Profile
              <svg viewBox="0 0 24 24">
                <path d="M14 5h5v5M19 5l-9 9M10 5H5v14h14v-5" />
              </svg>
            </button>
            <button className="mp-btn" type="button" onClick={() => toast("Profile Settings")}>
              Profile Settings
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2" />
              </svg>
            </button>
          </div>
        </section>

        <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(6, minmax(0,1fr))" }}>
          <MetricCard label="Followers" value="1.24M" absolute="+18.2K" percent="+1.5%" sparkline={[40, 42, 45, 48, 52, 55, 58, 62]} sparkStroke="#20dc8c" />
          <MetricCard label="Reach" value="4.8M" percent="+27%" sparkline={[30, 38, 35, 48, 44, 58, 52, 66]} sparkStroke="#20dc8c" />
          <MetricCard label="Impressions" value="12.6M" percent="+32%" sparkline={[22, 28, 30, 36, 40, 48, 52, 60]} sparkStroke="#d6a957" />
          <MetricCard label="Engagement Rate" value="6.8%" percent="+1.4%" sparkline={[20, 35, 28, 48, 40, 55, 60, 58]} sparkStroke="#20dc8c" />
          <MetricCard label="Saves" value="186.4K" percent="+28%" sparkline={[18, 24, 28, 32, 36, 42, 48, 55]} sparkStroke="#d6a957" />
          <MetricCard label="Profile Visits" value="342.1K" percent="+19%" sparkline={[24, 28, 32, 30, 38, 44, 50, 56]} sparkStroke="#20dc8c" />
        </div>

        <div className="mp-grid-4" style={{ gridTemplateColumns: "1.5fr 0.85fr 0.85fr 0.95fr" }}>
          <Panel
            title="Audience Growth"
            action={
              <button className="mp-btn" type="button" onClick={() => toast("Last 28 days")}>
                Last 28 days
              </button>
            }
          >
            <div className="mp-chart-wrap">
              <LineChart
                series={[{ id: "followers", color: "#20dc8c", fill: "rgba(32,220,140,0.14)", values: GROWTH }]}
                labels={["Oct 1", "Oct 8", "Oct 15", "Oct 22", "Oct 28"]}
                height={180}
                marker={{ index: 11, label: "1.24M" }}
              />
              <div className="mp-side-stats" style={{ minWidth: 160 }}>
                <div className="mp-list-meta" style={{ letterSpacing: "0.1em", textTransform: "uppercase" }}>
                  Top Locations
                </div>
                {LOCATIONS.map((row) => (
                  <ProgressBar key={row.label} value={row.value} label={row.label} tone="teal" />
                ))}
                <div className="mp-list-meta" style={{ letterSpacing: "0.1em", textTransform: "uppercase", marginTop: 8 }}>
                  Top Age Range
                </div>
                {AGES.map((row) => (
                  <ProgressBar key={row.label} value={row.value} label={row.label} tone="green" />
                ))}
              </div>
            </div>
          </Panel>

          <Panel title="Reels Performance">
            <div className="mp-thumb-col">
              {REELS.map((reel) => (
                <button key={reel.title} type="button" className="mp-media-card" onClick={() => toast(reel.title)}>
                  <img src={reel.thumb} alt="" />
                  <div className="mp-media-card-meta">
                    <strong>{reel.views}</strong>
                    <span>{reel.title}</span>
                    <GrowthDelta percent={reel.delta} />
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Story Performance">
            <div className="mp-thumb-col">
              {STORIES.map((story) => (
                <button key={story.title} type="button" className="mp-media-card is-story" onClick={() => toast(story.title)}>
                  <img src={story.thumb} alt="" />
                  <div className="mp-media-card-meta">
                    <strong>{story.views}</strong>
                    <span>{story.title}</span>
                    <GrowthDelta percent={story.delta} />
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Inbox & DMs">
            <div className="mp-list">
              {INBOX.map((msg) => (
                <button
                  key={msg.name}
                  type="button"
                  className="mp-list-row"
                  style={{ width: "100%", background: "transparent", border: 0, cursor: "pointer", textAlign: "left", padding: 0 }}
                  onClick={() => toast(`DM · ${msg.name}`)}
                >
                  <img className="mp-avatar-sm" src={msg.avatar} alt="" />
                  <div className="mp-list-copy">
                    <div className="mp-comment-head">
                      <strong>{msg.name}</strong>
                      <span>{msg.time}</span>
                    </div>
                    <div className="mp-list-meta">{msg.preview}</div>
                  </div>
                </button>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-4">
          <Panel title="Top Performing Posts">
            <div className="mp-posts-row">
              {TOP_POSTS.map((post) => (
                <button key={post.title} type="button" className="mp-post-tile" onClick={() => toast(post.title)}>
                  <img src={post.thumb} alt="" />
                  <div className="mp-post-tile-meta">
                    <strong>{post.title}</strong>
                    <span>
                      ♥ {post.likes} · 💬 {post.comments}
                    </span>
                    <em>{post.date}</em>
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Content Calendar">
            <div className="mp-list">
              {CALENDAR.map((item) => (
                <div key={`${item.date}-${item.title}`} className="mp-list-row">
                  <div className="mp-sched-day">
                    <strong>{item.date}</strong>
                    <span>{item.time}</span>
                  </div>
                  <div className="mp-list-copy">
                    <div className="mp-list-title">
                      {item.type} · {item.title}
                    </div>
                  </div>
                  <span className={`mp-badge ${item.status === "Scheduled" ? "is-green" : "is-muted"}`}>{item.status}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel
            title="Post Scheduler"
            action={
              <div className="mp-tabs">
                {SCHEDULER_TABS.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={`mp-tab${schedulerTab === tab ? " is-active" : ""}`}
                    onClick={() => setSchedulerTab(tab)}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            }
          >
            <textarea
              className="mp-textarea"
              value={composer}
              onChange={(e) => setComposer(e.target.value)}
              placeholder="Share something with the world..."
              aria-label="Post caption"
            />
            <div className="mp-composer-bar">
              <div className="mp-chip-row">
                {(["Image", "Video", "Emoji", "Location"] as const).map((label) => (
                  <button key={label} type="button" className="mp-chip" onClick={() => toast(label)}>
                    {label}
                  </button>
                ))}
              </div>
              <button
                className="mp-btn mp-btn-solid"
                type="button"
                onClick={() => toast(`Schedule ${schedulerTab}${composer ? `: ${composer.slice(0, 40)}` : ""}`)}
              >
                Schedule
              </button>
            </div>
          </Panel>

          <Panel title="Hashtag Insights">
            <div className="mp-list">
              {HASHTAGS.map((row) => (
                <button
                  key={row.tag}
                  type="button"
                  className="mp-list-row"
                  style={{ width: "100%", background: "transparent", border: 0, cursor: "pointer", textAlign: "left", padding: 0 }}
                  onClick={() => toast(row.tag)}
                >
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{row.tag}</div>
                    <div className="mp-list-meta">{row.reach} reach</div>
                  </div>
                  <GrowthDelta percent={row.growth} />
                </button>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-3">
          <Panel title="Aesthetic Feed Planner" action={<span className="mp-badge is-muted">Drag to reorder</span>}>
            <div className="mp-feed-grid">
              {FEED_CELLS.map((src, index) => (
                <button key={`feed-${index}`} type="button" className="mp-feed-cell" onClick={() => toast(`Feed cell ${index + 1}`)}>
                  <img src={src} alt="" />
                </button>
              ))}
            </div>
          </Panel>

          <Panel
            title="Visual Asset Library"
            action={
              <div className="mp-tabs">
                {ASSET_TABS.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={`mp-tab${assetTab === tab ? " is-active" : ""}`}
                    onClick={() => {
                      setAssetTab(tab);
                      toast(`${tab} assets`);
                    }}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            }
          >
            <div className="mp-asset-strip">
              {ASSET_STRIP.map((src, index) => (
                <button key={`asset-${index}`} type="button" className="mp-asset-cell" onClick={() => toast(`${assetTab} asset ${index + 1}`)}>
                  <img src={src} alt="" />
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Collaborations & Brand Deals">
            <div className="mp-list">
              {COLLABS.map((row) => (
                <button
                  key={row.partner}
                  type="button"
                  className="mp-list-row"
                  style={{ width: "100%", background: "transparent", border: 0, cursor: "pointer", textAlign: "left", padding: 0 }}
                  onClick={() => toast(row.partner)}
                >
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{row.partner}</div>
                    <div className="mp-list-meta">{row.type}</div>
                  </div>
                  <span className={`mp-badge ${row.status === "Active" ? "is-green" : row.status === "In Talks" ? "is-muted" : "is-gold"}`}>
                    {row.status}
                  </span>
                </button>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </MediaPlatformShell>
  );
}
