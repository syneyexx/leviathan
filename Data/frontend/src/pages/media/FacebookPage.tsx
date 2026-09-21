import { useState } from "react";
import { BrandMark } from "../../components/BrandMark";
import {
  DonutChart,
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

const TILES = platformTiles.facebook;
const GROWTH = [0.9, 0.95, 0.98, 1.02, 1.05, 1.08, 1.12, 1.14, 1.16, 1.19, 1.22, 1.24];
const GROWTH_TABS = ["Followers", "Reach", "Engagement", "Page Views"] as const;

const LATEST = [
  { title: "A Higher Humanity Is Possible", when: "Oct 26 · 2:14 PM", reactions: "18.4K", comments: "1.2K", shares: "864", growth: "+28%", thumb: TILES[0] },
  { title: "Discipline Builds Freedom", when: "Oct 24 · 11:02 AM", reactions: "12.1K", comments: "842", shares: "512", growth: "+19%", thumb: TILES[1] },
  { title: "People Build Stronger Worlds", when: "Oct 22 · 6:40 PM", reactions: "9.6K", comments: "610", shares: "388", growth: "+14%", thumb: TILES[2] },
  { title: "Ideas Today, Brighter Tomorrow", when: "Oct 20 · 9:15 AM", reactions: "7.8K", comments: "420", shares: "296", growth: "+11%", thumb: TILES[3] },
] as const;

const CALENDAR = [
  { date: "Oct 28", type: "Video Post", title: "New World Series — Ep. 4", time: "10:00 AM", thumb: TILES[0] },
  { date: "Oct 29", type: "Live Video", title: "Community Roundtable", time: "7:00 PM", thumb: TILES[1] },
  { date: "Oct 31", type: "Carousel", title: "Civilization Frames", time: "12:00 PM", thumb: TILES[2] },
  { date: "Nov 1", type: "Image Post", title: "Discipline Protocol", time: "9:00 AM", thumb: TILES[3] },
  { date: "Nov 2", type: "User Story", title: "Audience Spotlights", time: "4:00 PM", thumb: TILES[4] },
] as const;

const TOP = [
  { rank: 1, title: "A Higher Humanity Is Possible", type: "Video", reach: "1.8M", engagement: "142K", er: "10.3%", thumb: TILES[0] },
  { rank: 2, title: "Discipline Builds Freedom", type: "Reel", reach: "1.4M", engagement: "118K", er: "9.2%", thumb: TILES[1] },
  { rank: 3, title: "People Build Stronger Worlds", type: "Image", reach: "986K", engagement: "74K", er: "8.1%", thumb: TILES[2] },
  { rank: 4, title: "Community Turns Vision", type: "Video", reach: "812K", engagement: "58K", er: "7.4%", thumb: TILES[3] },
  { rank: 5, title: "Ideas Today", type: "Carousel", reach: "640K", engagement: "41K", er: "6.1%", thumb: TILES[4] },
] as const;

const ADS = [
  { name: "Higher Minds Campaign", spend: "$1,284", reach: "4.2M", growth: "+18%" },
  { name: "Leviathan Community", spend: "$864", reach: "2.8M", growth: "+12%" },
  { name: "Discipline Series", spend: "$612", reach: "1.9M", growth: "+9%" },
] as const;

const AGES = [
  { label: "13–17", value: 7 },
  { label: "18–24", value: 24 },
  { label: "25–34", value: 38 },
  { label: "35–44", value: 21 },
  { label: "45+", value: 10 },
] as const;

const ACTIONS = [
  "Create Post",
  "Create Reel",
  "Go Live",
  "Create Event",
  "Create Ad",
  "Boost Post",
] as const;

export function FacebookPage() {
  const toast = useAppToast();
  const [growthTab, setGrowthTab] = useState<(typeof GROWTH_TABS)[number]>("Followers");

  return (
    <MediaPlatformShell
      activePlatform="facebook"
      searchPlaceholder="Search posts, comments, campaigns, or anything..."
      createAccent="blue"
      promo={{ platform: "facebook", caption: "Real people. Bigger possibilities." }}
      sidebarCaption="Bigger audiences. A higher humanity."
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
          <div className="mp-profile-avatar" aria-hidden="true">
            <BrandMark id="fb-profile" />
          </div>
          <div className="mp-profile-meta">
            <div className="mp-profile-name">
              LEVIATHAN <VerifiedBadge />
            </div>
            <div className="mp-profile-handle">@LeviathanOfficial · Public Figure · Higher Humanity</div>
            <div className="mp-profile-bio">A higher humanity through greater minds.</div>
          </div>
          <div className="mp-profile-actions">
            <button className="mp-btn" type="button" onClick={() => toast("View Page")}>
              View Page
              <svg viewBox="0 0 24 24">
                <path d="M14 5h5v5M19 5l-9 9M10 5H5v14h14v-5" />
              </svg>
            </button>
            <button className="mp-btn" type="button" onClick={() => toast("Page Settings")}>
              Page Settings
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2" />
              </svg>
            </button>
          </div>
        </section>

        <div className="mp-metrics" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))" }}>
          <MetricCard
            label="Page Followers"
            value="1.24M"
            absolute="+18.3K"
            percent="+1.5%"
            sparkline={[40, 42, 45, 48, 52, 55, 58, 62]}
            sparkStroke="#1877F2"
          />
          <MetricCard
            label="Post Reach"
            value="4.82M"
            absolute="+612K"
            percent="+14.5%"
            sparkline={[30, 38, 35, 48, 44, 58, 52, 66]}
            sparkStroke="#1877F2"
          />
          <MetricCard
            label="Post Engagement"
            value="386.7K"
            absolute="+28.4K"
            percent="+7.9%"
            sparkline={[20, 35, 28, 48, 40, 55, 60, 58]}
            sparkStroke="#1877F2"
          />
          <MetricCard
            label="Video Views"
            value="2.1M"
            absolute="+420K"
            percent="+25.0%"
            sparkline={[22, 28, 30, 36, 40, 48, 52, 60]}
            sparkStroke="#1877F2"
          />
          <MetricCard
            label="Link Clicks"
            value="124.6K"
            absolute="+11.2K"
            percent="+9.9%"
            sparkline={[18, 24, 28, 32, 36, 42, 48, 55]}
            sparkStroke="#d6a957"
          />
        </div>

        <div className="mp-grid-3">
          <Panel
            title="Audience Growth"
            action={
              <div className="mp-tabs">
                {GROWTH_TABS.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={`mp-tab${growthTab === tab ? " is-active" : ""}`}
                    onClick={() => setGrowthTab(tab)}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            }
          >
            <div className="mp-chart-wrap">
              <LineChart
                series={[{ id: "growth", color: "#1877F2", fill: "rgba(24,119,242,0.14)", values: GROWTH }]}
                labels={["Oct 1", "Oct 8", "Oct 15", "Oct 22", "Oct 28"]}
                height={190}
              />
              <div className="mp-side-stats">
                {[
                  ["Total Followers", "1.24M", "+1.5%"],
                  ["New Followers", "186.3K", "+22%"],
                  ["Post Reach", "4.82M", "+14.5%"],
                  ["Engagements", "386.7K", "+7.9%"],
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

          <Panel
            title="Latest Posts"
            action={
              <button className="mp-link-btn" type="button" onClick={() => toast("View All Posts")}>
                View All
              </button>
            }
          >
            <div className="mp-list">
              {LATEST.map((item) => (
                <div key={item.title} className="mp-list-row">
                  <img className="mp-thumb" src={item.thumb} alt="" />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{item.title}</div>
                    <div className="mp-list-meta">
                      {item.when} · ♥ {item.reactions} · 💬 {item.comments} · ↗ {item.shares}
                    </div>
                  </div>
                  <span className="mp-badge is-green">{item.growth}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel
            title="Content Calendar"
            action={
              <button className="mp-link-btn" type="button" onClick={() => toast("View Calendar")}>
                View Calendar
              </button>
            }
          >
            <div className="mp-list">
              {CALENDAR.map((item) => (
                <div key={item.date + item.title} className="mp-list-row">
                  <img className="mp-thumb" src={item.thumb} alt="" />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{item.title}</div>
                    <div className="mp-list-meta">
                      {item.date} · {item.type} · {item.time}
                    </div>
                  </div>
                  <span className="mp-badge is-muted">Scheduled</span>
                </div>
              ))}
              <button className="mp-btn" type="button" onClick={() => toast("Add scheduled post")}>
                + Add to calendar
              </button>
            </div>
          </Panel>
        </div>

        <div className="mp-grid-4" style={{ gridTemplateColumns: "1.4fr 0.9fr 0.95fr 0.75fr" }}>
          <Panel title="Top Performing Content">
            <table className="mp-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Post</th>
                  <th>Type</th>
                  <th>Reach</th>
                  <th>Engagement</th>
                  <th>ER</th>
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
                    <td>{row.type}</td>
                    <td>{row.reach}</td>
                    <td>{row.engagement}</td>
                    <td>{row.er}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel
            title="Ad Campaigns"
            action={
              <button className="mp-link-btn" type="button" onClick={() => toast("View All Ads")}>
                View All
              </button>
            }
          >
            <div className="mp-list">
              {ADS.map((ad) => (
                <div key={ad.name} className="mp-list-row">
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{ad.name}</div>
                    <div className="mp-list-meta">
                      Spend {ad.spend} · Reach {ad.reach}
                    </div>
                  </div>
                  <GrowthDelta percent={ad.growth} />
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Audience Demographics">
            <div className="mp-demo-wrap">
              <div className="mp-gender-block">
                <GenderDonut />
                <div className="mp-legend">
                  <span>
                    <i style={{ background: "#1877F2" }} /> Men 58%
                  </span>
                  <span>
                    <i style={{ background: "#63B3ED" }} /> Women 38%
                  </span>
                  <span>
                    <i style={{ background: "#4A5568" }} /> Other 4%
                  </span>
                </div>
              </div>
              <div className="mp-stack">
                {AGES.map((row) => (
                  <ProgressBar key={row.label} value={row.value} label={row.label} tone="teal" />
                ))}
              </div>
            </div>
          </Panel>

          <div className="mp-stack">
            <Panel title="Community Sentiment">
              <div className="mp-sentiment">
                <DonutChart value={92} size={96} stroke={10} color="#20dc8c" label="92%" />
                <div className="mp-legend">
                  <span>
                    <i style={{ background: "#20dc8c" }} /> Positive 92%
                  </span>
                  <span>
                    <i style={{ background: "#1877F2" }} /> Neutral 6%
                  </span>
                  <span>
                    <i style={{ background: "#e53935" }} /> Negative 2%
                  </span>
                </div>
              </div>
            </Panel>
            <Panel title="Inbox & Comments">
              <div className="mp-inbox-summary">
                <button type="button" onClick={() => toast("Unread Messages")}>
                  <strong>128</strong>
                  <span>Unread Messages</span>
                </button>
                <button type="button" onClick={() => toast("Comments to Review")}>
                  <strong>24</strong>
                  <span>Comments to Review</span>
                </button>
                <button type="button" onClick={() => toast("Mentions")}>
                  <strong>7</strong>
                  <span>Mentions</span>
                </button>
              </div>
            </Panel>
          </div>
        </div>

        <div className="mp-action-bar">
          <div className="mp-footer-quote" style={{ marginLeft: 0 }}>
            Community turns vision into reality
          </div>
          {ACTIONS.map((action) => (
            <button key={action} className="mp-btn" type="button" onClick={() => toast(action)}>
              {action}
            </button>
          ))}
          <div className="mp-footer-quote">Ideas today · A brighter tomorrow</div>
        </div>
      </div>
    </MediaPlatformShell>
  );
}

function GenderDonut() {
  const size = 88;
  const stroke = 12;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const men = 0.58 * c;
  const women = 0.38 * c;
  const other = 0.04 * c;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Gender split">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#4A5568" strokeWidth={stroke} strokeDasharray={`${other} ${c - other}`} strokeDashoffset={0} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="#63B3ED"
        strokeWidth={stroke}
        strokeDasharray={`${women} ${c - women}`}
        strokeDashoffset={-other}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="#1877F2"
        strokeWidth={stroke}
        strokeDasharray={`${men} ${c - men}`}
        strokeDashoffset={-(other + women)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x="50%" y="50%" dominantBaseline="middle" textAnchor="middle" fill="#e8e4dc" fontSize="11" fontWeight="600">
        58%
      </text>
    </svg>
  );
}
