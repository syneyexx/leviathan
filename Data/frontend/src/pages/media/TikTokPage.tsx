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
import { MediaPlatformShell } from "../../layouts/MediaPlatformShell";
import { useAppToast } from "../../state/useAppToast";

const TILES = platformTiles.tiktok;

const FOLLOWER_SERIES = [1.2, 1.28, 1.32, 1.4, 1.45, 1.5, 1.55, 1.58, 1.62, 1.68, 1.74, 1.8];
const VIEW_SERIES = [22, 24, 26, 28, 30, 32, 34, 35, 38.4, 40, 41.5, 42.7];

const LATEST = [
  { title: "Discipline Builds Freedom", meta: "42.1K views · 2 hours ago", growth: "+280%", duration: "00:32", thumb: TILES[0] },
  { title: "AI Will Change Everything", meta: "128K views · 1 day ago", growth: "+164%", duration: "00:48", thumb: TILES[1] },
  { title: "The Leviathan Mindset", meta: "96.4K views · 2 days ago", growth: "+91%", duration: "00:41", thumb: TILES[2] },
  { title: "Shorter Stories, Bigger Impact", meta: "71.2K views · 3 days ago", growth: "+54%", duration: "00:28", thumb: TILES[3] },
] as const;

const SOUNDS = [
  { rank: 1, title: "The Calling", creator: "Original Sound", uses: "1.2M videos", thumb: TILES[0] },
  { rank: 2, title: "Higher Frequency", creator: "@LeviathanOfficial", uses: "842K videos", thumb: TILES[1] },
  { rank: 3, title: "Discipline Pulse", creator: "Original Sound", uses: "618K videos", thumb: TILES[2] },
  { rank: 4, title: "Night Signal", creator: "@SignalLab", uses: "401K videos", thumb: TILES[3] },
  { rank: 5, title: "Bright Tomorrow", creator: "Original Sound", uses: "276K videos", thumb: TILES[4] },
] as const;

const QUEUE = [
  { title: "The Leviathan Mindset", status: "Ready to publish", tone: "green" as const, thumb: TILES[0] },
  { title: "AI Will Change Everything", status: "Edited · Add caption", tone: "gold" as const, thumb: TILES[1] },
  { title: "Attention Moves Culture", status: "Finalizing", tone: "muted" as const, thumb: TILES[2] },
] as const;

const TOP = [
  { rank: 1, title: "AI Will Change Everything", views: "4.2M", watch: "18.4s", likeRate: "12.8%", shares: "186K", thumb: TILES[1] },
  { rank: 2, title: "The Leviathan Mindset", views: "3.1M", watch: "19.1s", likeRate: "11.4%", shares: "142K", thumb: TILES[0] },
  { rank: 3, title: "Discipline Builds Freedom", views: "2.6M", watch: "17.8s", likeRate: "13.2%", shares: "118K", thumb: TILES[2] },
  { rank: 4, title: "Create a Higher Reality", views: "1.9M", watch: "16.9s", likeRate: "10.6%", shares: "94K", thumb: TILES[3] },
  { rank: 5, title: "Stories Shape Civilization", views: "1.4M", watch: "18.2s", likeRate: "9.8%", shares: "71K", thumb: TILES[4] },
] as const;

const HASHTAGS = [
  { tag: "#HigherHumanity", views: "12.4M", growth: "+146%" },
  { tag: "#Discipline", views: "8.7M", growth: "+92%" },
  { tag: "#Leviathan", views: "6.1M", growth: "+78%" },
  { tag: "#GreaterMinds", views: "4.3M", growth: "+64%" },
  { tag: "#BrightTomorrow", views: "3.2M", growth: "+51%" },
] as const;

const IDEAS = [
  "AI vs Human Potential (Short companion series)",
  "Day in the Life — Founder Mode",
  "30-second Discipline Drill",
  "Behind the Leviathan Voice",
  "Trend remix: Attention Moves Humanity",
] as const;

const SCHEDULE = [
  { day: "Mon", when: "Oct 28 · 09:00", title: "Discipline Builds Freedom", thumb: TILES[0] },
  { day: "Tue", when: "Oct 29 · 12:00", title: "AI Will Change Everything", thumb: TILES[1] },
  { day: "Wed", when: "Oct 30 · 18:00", title: "The Leviathan Mindset", thumb: TILES[2] },
  { day: "Thu", when: "Oct 31 · 09:30", title: "Higher Frequency Cut", thumb: TILES[3] },
  { day: "Fri", when: "Nov 1 · 16:00", title: "Community Reply Round", thumb: TILES[4] },
] as const;

const COLLABS = [
  { handle: "@NovaCircuit", followers: "412K", status: "Invite" as const, avatar: TILES[0] },
  { handle: "@SignalLab", followers: "288K", status: "Pending" as const, avatar: TILES[1] },
  { handle: "@MindForge", followers: "196K", status: "Invite" as const, avatar: TILES[2] },
  { handle: "@AetherPulse", followers: "154K", status: "Invite" as const, avatar: TILES[3] },
] as const;

const COMMENTS = [
  { user: "FutureSignal", time: "2m", text: "This sound is going to own the feed.", likes: "1.2K", avatar: mediaControlCrops.tiktokTile1 },
  { user: "DisciplineDaily", time: "14m", text: "Caption hit hard. Need the full series.", likes: "864", avatar: mediaControlCrops.tiktokTile2 },
  { user: "CultureShift", time: "1h", text: "Cross-post this to Reels too — insane retention.", likes: "512", avatar: TILES[3] },
] as const;

const PUBLISH_TABS = ["Post Video", "Drafts (4)", "Scheduled (6)"] as const;
const HASHTAG_PILLS = ["#HigherHumanity", "#Discipline", "#Leviathan"] as const;

export function TikTokPage() {
  const toast = useAppToast();
  const [publishTab, setPublishTab] = useState<(typeof PUBLISH_TABS)[number]>("Post Video");
  const [scheduleLater, setScheduleLater] = useState(false);
  const [crossPost, setCrossPost] = useState(true);

  return (
    <MediaPlatformShell
      activePlatform="tiktok"
      searchPlaceholder="Search videos, creators, sounds, hashtags, or anything..."
      createAccent="red"
      promo={{ platform: "tiktok", caption: "Ideas today. A brighter tomorrow." }}
      sidebarCaption="Short ideas. Bigger audiences. A higher humanity."
      statusItems={[
        { label: "Channel Status", value: "Healthy" },
        { label: "Monetization", value: "Enabled" },
        { label: "Content Quality", value: "Excellent" },
        { label: "Community Growth", value: "On Track" },
      ]}
    >
      <div className="mp-page">
        <section className="mp-hero">
          <div className="mp-hero-media">
            <img src={mediaControlCrops.tiktokHero} alt="" />
          </div>
          <div className="mp-hero-shade" />
          <div className="mp-hero-content">
            <div className="mp-hero-icon">
              <PlatformIcon platform="tiktok" />
            </div>
            <div className="mp-hero-copy">
              <h1 className="mp-hero-title">TikTok Control</h1>
              <div className="mp-hero-flow">Shorts → Trends → Community → Culture → Impact</div>
            </div>
            <div className="mp-hero-quotes">
              <span>Shorter stories. Brighter tomorrows.</span>
              <span>Attention moves humanity. — Leviathan</span>
            </div>
          </div>
        </section>

        <section className="mp-profile">
          <div className="mp-profile-avatar" aria-hidden="true">
            <BrandMark id="tt-profile" />
          </div>
          <div className="mp-profile-meta">
            <div className="mp-profile-name">
              LEVIATHAN <VerifiedBadge />
            </div>
            <div className="mp-profile-handle">@Leviathanofficial</div>
            <div className="mp-profile-stats">
              <span>
                <strong>1.8M</strong> followers
              </span>
              <span>
                <strong>42</strong> following
              </span>
              <span>
                <strong>98.4M</strong> likes
              </span>
            </div>
            <div className="mp-profile-bio">A higher humanity through greater minds.</div>
          </div>
          <div className="mp-profile-actions">
            <button className="mp-btn" type="button" onClick={() => toast("View Profile")}>
              View Profile
              <svg viewBox="0 0 24 24">
                <path d="M14 5h5v5M19 5l-9 9M10 5H5v14h14v-5" />
              </svg>
            </button>
            <button className="mp-btn" type="button" onClick={() => toast("Account Settings")}>
              Account Settings
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2" />
              </svg>
            </button>
          </div>
        </section>

        <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))" }}>
          <MetricCard
            label="Followers"
            value="1.8M"
            absolute="+24.8K"
            percent="+1.4%"
            sparkline={[40, 42, 45, 48, 52, 55, 58, 62]}
            sparkStroke="#25F4EE"
          />
          <MetricCard
            label="Video Views (28 days)"
            value="42.7M"
            absolute="+6.2M"
            percent="+17.0%"
            sparkline={[30, 38, 35, 48, 44, 58, 52, 66]}
            sparkStroke="#25F4EE"
          />
          <MetricCard
            label="Avg. Watch Time"
            value="18.6s"
            absolute="+2.4s"
            percent="+14.8%"
            sparkline={[20, 35, 28, 48, 40, 55, 60, 58]}
            sparkStroke="#d6a957"
          />
          <MetricCard
            label="Watch-Through Rate"
            value="68%"
            absolute="+12%"
            percent="+21.4%"
            sparkline={[50, 52, 54, 58, 60, 63, 66, 68]}
            sparkStroke="#d6a957"
          />
          <MetricCard
            label="Shares"
            value="327.4K"
            absolute="+48.2K"
            percent="+17.3%"
            sparkline={[22, 28, 30, 36, 40, 48, 52, 60]}
            sparkStroke="#FE2C55"
          />
        </div>

        <div className="mp-grid-4" style={{ gridTemplateColumns: "1.4fr 1fr 0.9fr 0.9fr" }}>
          <Panel
            title="Audience Growth"
            action={
              <button className="mp-btn" type="button" onClick={() => toast("Last 28 days")}>
                Last 28 days
              </button>
            }
          >
            <div className="mp-chip-row" style={{ marginBottom: 8 }}>
              <span className="mp-chip" style={{ borderColor: "rgba(254,44,85,0.4)", background: "rgba(254,44,85,0.12)", color: "#FE2C55" }}>
                Followers
              </span>
              <span className="mp-chip" style={{ borderColor: "rgba(37,244,238,0.4)", background: "rgba(37,244,238,0.12)", color: "#25F4EE" }}>
                Video Views
              </span>
              <span className="mp-badge is-muted">Oct 17 · 1.62M · 38.4M</span>
            </div>
            <LineChart
              series={[
                { id: "followers", color: "#FE2C55", values: FOLLOWER_SERIES },
                { id: "views", color: "#25F4EE", values: VIEW_SERIES.map((v) => v / 25) },
              ]}
              labels={["Oct 1", "Oct 8", "Oct 15", "Oct 22", "Oct 28"]}
              height={190}
              marker={{ index: 8, label: "Oct 17" }}
            />
          </Panel>

          <Panel title="Latest Uploads">
            <div className="mp-list">
              {LATEST.map((item) => (
                <button
                  key={item.title}
                  type="button"
                  className="mp-list-row"
                  style={{ width: "100%", background: "transparent", border: 0, cursor: "pointer", textAlign: "left", padding: 0 }}
                  onClick={() => toast(item.title)}
                >
                  <div className="mp-thumb-stack">
                    <img className="mp-thumb portrait" src={item.thumb} alt="" />
                    <span className="mp-thumb-duration">{item.duration}</span>
                  </div>
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{item.title}</div>
                    <div className="mp-list-meta">{item.meta}</div>
                  </div>
                  <span className="mp-badge is-green">{item.growth}</span>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Trending Sounds">
            <div className="mp-list">
              {SOUNDS.map((s) => (
                <button
                  key={s.rank}
                  type="button"
                  className="mp-numbered"
                  style={{ width: "100%", background: "transparent", border: 0, cursor: "pointer", textAlign: "left", padding: 0 }}
                  onClick={() => toast(s.title)}
                >
                  <span className="mp-numbered-index">{s.rank}</span>
                  <img className="mp-thumb square" src={s.thumb} alt="" />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{s.title}</div>
                    <div className="mp-list-meta">
                      {s.creator} · {s.uses}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Viral Clip Queue">
            <div className="mp-list">
              {QUEUE.map((item) => (
                <div key={item.title} className="mp-list-row">
                  <img className="mp-thumb portrait" src={item.thumb} alt="" />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{item.title}</div>
                    <span className={`mp-badge is-${item.tone}`}>{item.status}</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-4" style={{ gridTemplateColumns: "1.5fr 0.85fr 0.85fr 0.9fr" }}>
          <Panel title="Top Performing Videos">
            <table className="mp-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Video</th>
                  <th>Views</th>
                  <th>Watch Time</th>
                  <th>Like Rate</th>
                  <th>Shares</th>
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
                    <td>{row.likeRate}</td>
                    <td>{row.shares}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Hashtags & Trends">
            <div className="mp-list">
              {HASHTAGS.map((h, i) => (
                <button
                  key={h.tag}
                  type="button"
                  className="mp-numbered"
                  style={{ width: "100%", background: "transparent", border: 0, cursor: "pointer", textAlign: "left", padding: 0, alignItems: "center" }}
                  onClick={() => toast(h.tag)}
                >
                  <span className="mp-numbered-index">{i + 1}</span>
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{h.tag}</div>
                    <div className="mp-list-meta">{h.views} views</div>
                  </div>
                  <GrowthDelta percent={h.growth} />
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Content Ideas">
            <div className="mp-list">
              {IDEAS.map((idea) => (
                <button
                  key={idea}
                  type="button"
                  className="mp-list-row"
                  style={{ width: "100%", background: "transparent", border: 0, cursor: "pointer", textAlign: "left", padding: 0 }}
                  onClick={() => toast(idea)}
                >
                  <span className="mp-idea-icon" aria-hidden="true">
                    ✦
                  </span>
                  <div className="mp-list-title" style={{ whiteSpace: "normal" }}>
                    {idea}
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Posting Schedule">
            <div className="mp-list">
              {SCHEDULE.map((item) => (
                <div key={item.day + item.title} className="mp-list-row">
                  <div className="mp-sched-day">
                    <strong>{item.day}</strong>
                    <span>{item.when}</span>
                  </div>
                  <img className="mp-thumb" src={item.thumb} alt="" />
                  <div className="mp-list-title">{item.title}</div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-3" style={{ gridTemplateColumns: "1fr 1fr 1.3fr" }}>
          <Panel title="Creator Collaborations">
            <div className="mp-collab-row">
              {COLLABS.map((c) => (
                <div key={c.handle} className="mp-collab-card">
                  <img className="mp-avatar-sm" src={c.avatar} alt="" />
                  <strong>{c.handle}</strong>
                  <span>{c.followers}</span>
                  <button
                    className="mp-btn"
                    type="button"
                    style={{ height: 26, fontSize: 10 }}
                    onClick={() => toast(`${c.status} ${c.handle}`)}
                  >
                    {c.status}
                  </button>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Community & Comments">
            <div className="mp-list">
              {COMMENTS.map((c) => (
                <div key={c.user + c.time} className="mp-comment">
                  <img className="mp-avatar-sm" src={c.avatar} alt="" />
                  <div className="mp-comment-body">
                    <div className="mp-comment-head">
                      <strong>@{c.user}</strong>
                      <span>{c.time}</span>
                      <span className="mp-list-meta">♥ {c.likes}</span>
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

          <Panel
            title="Upload & Publish"
            action={
              <div className="mp-tabs">
                {PUBLISH_TABS.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={`mp-tab${publishTab === tab ? " is-active" : ""}`}
                    onClick={() => {
                      setPublishTab(tab);
                      toast(tab);
                    }}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            }
          >
            <div className="mp-publish-grid">
              <button className="mp-dropzone" type="button" onClick={() => toast("Browse video file")}>
                <strong>Drag & drop your video here</strong>
                or click to browse · MP4, MOV, up to 10 minutes, 2GB
              </button>
              <div className="mp-stack">
                <label className="mp-field-label">Caption</label>
                <textarea className="mp-textarea" placeholder="Write a compelling caption..." rows={3} />
                <label className="mp-field-label">Hashtags</label>
                <div className="mp-chip-row">
                  {HASHTAG_PILLS.map((tag) => (
                    <button key={tag} type="button" className="mp-chip" onClick={() => toast(tag)}>
                      {tag}
                    </button>
                  ))}
                </div>
                <label className="mp-toggle">
                  <input
                    type="checkbox"
                    checked={scheduleLater}
                    onChange={(e) => {
                      setScheduleLater(e.target.checked);
                      toast(e.target.checked ? "Schedule for later" : "Publish now");
                    }}
                  />
                  Schedule for later
                </label>
                <label className="mp-toggle">
                  <input
                    type="checkbox"
                    checked={crossPost}
                    onChange={(e) => {
                      setCrossPost(e.target.checked);
                      toast(e.target.checked ? "Cross-post enabled" : "Cross-post disabled");
                    }}
                  />
                  Cross-post (YouTube, Instagram)
                </label>
                <button className="mp-btn mp-btn-solid" type="button" onClick={() => toast("Publish to TikTok")}>
                  Publish to TikTok
                </button>
              </div>
            </div>
          </Panel>
        </div>

        <div className="mp-footer-quote" style={{ marginLeft: 0, padding: "4px 2px" }}>
          Attention is a force · Ideas today · A brighter tomorrow
        </div>
      </div>
    </MediaPlatformShell>
  );
}
