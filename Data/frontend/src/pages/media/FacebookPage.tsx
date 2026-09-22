import { useState } from "react";
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
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";

const TILES = platformTiles.facebook;
const FOLLOWERS = [0.86, 0.9, 0.92, 0.98, 1.04, 1.08, 1.12, 1.15, 1.18, 1.2, 1.22, 1.24];
const TABS = ["Followers", "Reach", "Engagement", "Page Views"] as const;

const POSTS = [
  { title: "A Higher Humanity Is Possible", when: "Oct 26 · Video", likes: "48.2K", comments: "3.1K", shares: "6.4K", growth: "+28%", thumb: TILES[0] },
  { title: "People Build Stronger Worlds", when: "Oct 24 · Image", likes: "36.8K", comments: "2.4K", shares: "4.9K", growth: "+19%", thumb: TILES[1] },
  { title: "Discipline Creates Freedom", when: "Oct 21 · Reel", likes: "29.1K", comments: "1.8K", shares: "3.6K", growth: "+14%", thumb: TILES[2] },
  { title: "Community Turns Vision Into Reality", when: "Oct 18 · Carousel", likes: "22.4K", comments: "1.2K", shares: "2.8K", growth: "+11%", thumb: TILES[3] },
] as const;

const CALENDAR = [
  { date: "Oct 28", title: "New World Series", meta: "Video Post · 10:00 AM", thumb: TILES[0] },
  { date: "Oct 29", title: "Community Q&A", meta: "Live Video · 7:00 PM", thumb: TILES[1] },
  { date: "Oct 30", title: "Higher Minds Still", meta: "Image Post · 12:00 PM", thumb: TILES[2] },
  { date: "Oct 31", title: "Discipline Series", meta: "Carousel · 3:00 PM", thumb: TILES[3] },
  { date: "Nov 1", title: "Leviathan Community", meta: "Video Post · 6:00 PM", thumb: TILES[4] },
  { date: "Nov 2", title: "Ideas Today", meta: "User Story · 9:00 AM", thumb: TILES[5] },
] as const;

const TOP = [
  { rank: 1, title: "A Higher Humanity Is Possible", type: "Video", reach: "1.24M", eng: "86.4K", er: "7.0%", thumb: TILES[0] },
  { rank: 2, title: "People Build Stronger Worlds", type: "Image", reach: "964K", eng: "62.1K", er: "6.4%", thumb: TILES[1] },
  { rank: 3, title: "Discipline Creates Freedom", type: "Reel", reach: "812K", eng: "54.8K", er: "6.7%", thumb: TILES[2] },
  { rank: 4, title: "Attention Moves Humanity", type: "Video", reach: "701K", eng: "41.2K", er: "5.9%", thumb: TILES[4] },
  { rank: 5, title: "Create a Higher Reality", type: "Image", reach: "628K", eng: "36.9K", er: "5.9%", thumb: TILES[5] },
] as const;

const ADS = [
  { name: "Higher Minds Campaign", spend: "$12.4K", reach: "1.8M", trend: "+24%" },
  { name: "Leviathan Community", spend: "$8.6K", reach: "1.1M", trend: "+18%" },
  { name: "Discipline Series", spend: "$6.2K", reach: "842K", trend: "+15%" },
] as const;

const AGES = [
  { label: "13-17", pct: 7 },
  { label: "18-24", pct: 24 },
  { label: "25-34", pct: 38 },
  { label: "35-44", pct: 21 },
  { label: "45+", pct: 10 },
] as const;

const ACTIONS = ["Create Post", "Create Reel", "Go Live", "Create Event", "Create Ad", "Boost Post"] as const;

function GenderDonut() {
  const size = 118;
  const stroke = 14;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const segments = [
    { pct: 58, color: "#1877f2" },
    { pct: 38, color: "#60a5fa" },
    { pct: 4, color: "#93c5fd" },
  ];
  let offset = 0;

  return (
    <svg className="mp-fb-gender-donut" width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="1.24M followers">
      {segments.map((seg) => {
        const length = (seg.pct / 100) * circumference;
        const node = (
          <circle
            key={seg.color}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={seg.color}
            strokeWidth={stroke}
            strokeDasharray={`${length} ${circumference - length}`}
            strokeDashoffset={-offset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        );
        offset += length;
        return node;
      })}
      <text x="50%" y="46%" textAnchor="middle" fill="#e8e4dc" fontSize="16" fontWeight="700">
        1.24M
      </text>
      <text x="50%" y="60%" textAnchor="middle" fill="rgba(138,134,128,0.95)" fontSize="9">
        followers
      </text>
    </svg>
  );
}

export function FacebookPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Followers");

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Media Mode"
      searchPlaceholder="Search posts, comments, campaigns, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--media-platform"
    >
      <main className="lv-main mp-main-in-shell" data-accent="blue">
      <div className="mp-page mp-fb">
        <section className="mp-hero mp-fb-hero">
          <div className="mp-hero-media">
            <img src={mediaControlCrops.facebookHero} alt="" draggable={false} />
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
        <section className="mp-profile mp-fb-profile">
          <div className="mp-profile-avatar">
            <BrandMark id="fb-profile" />
          </div>
          <div className="mp-profile-meta">
            <div className="mp-profile-name">
              LEVIATHAN <VerifiedBadge />
            </div>
            <div className="mp-profile-handle">@LeviathanOfficial</div>
            <div className="mp-fb-cat">Public Figure · Higher Humanity</div>
            <div className="mp-profile-bio">A higher humanity through greater minds.</div>
          </div>
          <div className="mp-profile-actions">
            <button className="mp-btn" type="button" onClick={() => toast("View Page")}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M14 5h5v5M19 5l-9 9M10 5H5v14h14v-5" />
              </svg>
              View Page
            </button>
            <button className="mp-btn" type="button" onClick={() => toast("Page Settings")}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6.1 6.1l1.6 1.6M16.3 16.3l1.6 1.6M17.9 6.1l-1.6 1.6M7.7 16.3l-1.6 1.6" />
              </svg>
              Page Settings
            </button>
          </div>
        </section>

        <div className="mp-metrics mp-fb-metrics">
          <MetricCard label="Page Followers" value="1.24M" absolute="+18.3K" percent="+1.5%" sparkline={FOLLOWERS} sparkStroke="#1877f2" />
          <MetricCard label="Post Reach" value="4.82M" absolute="+612K" percent="+14.5%" sparkline={[3, 3.4, 3.8, 4, 4.2, 4.4, 4.6, 4.82]} sparkStroke="#1877f2" />
          <MetricCard label="Post Engagement" value="386.7K" absolute="+28.4K" percent="+7.9%" sparkline={[250, 280, 300, 320, 340, 360, 370, 386]} sparkStroke="#1877f2" />
          <MetricCard label="Video Views" value="2.1M" absolute="+420K" percent="+25.0%" sparkline={[1.2, 1.4, 1.5, 1.6, 1.7, 1.85, 2.0, 2.1]} sparkStroke="#d6a957" />
          <MetricCard label="Link Clicks" value="124.6K" absolute="+11.2K" percent="+9.9%" sparkline={[80, 90, 95, 100, 108, 114, 120, 124]} sparkStroke="#d6a957" />
        </div>

        <div className="mp-grid-3 mp-fb-mid">
          <Panel
            title="Audience Growth"
            action={
              <div className="mp-tabs">
                {TABS.map((t) => (
                  <button
                    key={t}
                    type="button"
                    className={`mp-tab${tab === t ? " is-active" : ""}`}
                    onClick={() => {
                      setTab(t);
                      toast(`${t} growth`);
                    }}
                  >
                    {t}
                  </button>
                ))}
              </div>
            }
          >
            <div className="mp-fb-chart-meta">
              <button type="button" className="mp-fb-range" onClick={() => toast("Last 28 days")}>
                Last 28 days
              </button>
              <span className="mp-fb-tooltip-chip">Oct 17 · 1.24M followers</span>
            </div>
            <div className="mp-chart-wrap">
              <LineChart
                series={[{ id: "f", color: "#1877f2", fill: "rgba(24,119,242,0.16)", values: FOLLOWERS }]}
                labels={["Oct 1", "Oct 8", "Oct 15", "Oct 22", "Oct 28"]}
                height={180}
                marker={{ index: 6, label: "1.24M followers" }}
              />
              <div className="mp-side-stats">
                {[
                  ["Total Followers", "1.24M", "+1.5%"],
                  ["New Followers", "186.3K", "+22%"],
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
                <button key={p.title} type="button" className="mp-fb-post-row" onClick={() => toast(p.title)}>
                  <img className="mp-thumb square" src={p.thumb} alt="" draggable={false} />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{p.title}</div>
                    <div className="mp-list-meta">{p.when}</div>
                    <div className="mp-list-meta">
                      👍 {p.likes} · 💬 {p.comments} · ↗ {p.shares}
                    </div>
                  </div>
                  <GrowthDelta percent={p.growth} />
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Content Calendar">
            <div className="mp-list">
              {CALENDAR.map((c) => (
                <button key={c.date} type="button" className="mp-fb-cal-row" onClick={() => toast(c.title)}>
                  <div className="mp-fb-cal-date">{c.date}</div>
                  <img className="mp-thumb" src={c.thumb} alt="" draggable={false} />
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{c.title}</div>
                    <div className="mp-list-meta">{c.meta}</div>
                  </div>
                  <span className="mp-badge is-green">Scheduled</span>
                </button>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-grid-4 mp-fb-lower">
          <div className="mp-fb-table-span">
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
                  {TOP.map((r) => (
                    <tr key={r.title}>
                      <td>{r.rank}</td>
                      <td>
                        <button type="button" className="mp-fb-table-post" onClick={() => toast(r.title)}>
                          <img className="mp-thumb" src={r.thumb} alt="" draggable={false} />
                          <span className="mp-list-title">{r.title}</span>
                        </button>
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
                <button key={a.name} type="button" className="mp-fb-ad-row" onClick={() => toast(a.name)}>
                  <div className="mp-list-copy">
                    <div className="mp-list-title">{a.name}</div>
                    <div className="mp-list-meta">
                      Spend {a.spend} · Reach {a.reach}
                    </div>
                  </div>
                  <GrowthDelta percent={a.trend} />
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Audience Demographics">
            <div className="mp-fb-demo">
              <GenderDonut />
              <ul className="mp-fb-legend">
                <li>
                  <span className="is-men" /> Men 58%
                </li>
                <li>
                  <span className="is-women" /> Women 38%
                </li>
                <li>
                  <span className="is-other" /> Other 4%
                </li>
              </ul>
            </div>
            <div className="mp-ig-subhead mp-fb-subhead">Top Age Groups</div>
            {AGES.map((a) => (
              <div key={a.label} className="mp-bar-row">
                <span>{a.label}</span>
                <div className="mp-bar-track">
                  <div className="mp-bar-fill mp-fb-bar" style={{ width: `${Math.min(100, a.pct * 2.2)}%` }} />
                </div>
                <span>{a.pct}%</span>
              </div>
            ))}
          </Panel>
        </div>

        <div className="mp-grid-2 mp-fb-sentiment-row">
          <Panel title="Community Sentiment">
            <div className="mp-fb-sentiment">
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
                <button key={l} type="button" className="mp-fb-inbox-row" onClick={() => toast(l)}>
                  <strong className="mp-fb-inbox-n">{n}</strong>
                  <span className="mp-list-title">{l}</span>
                </button>
              ))}
            </div>
          </Panel>
        </div>

        <div className="mp-action-bar mp-fb-actionbar">
          <span className="mp-footer-quote" style={{ marginLeft: 0 }}>
            Community turns vision into reality
          </span>
          <div className="mp-fb-actions">
            {ACTIONS.map((label) => (
              <button key={label} className="mp-btn mp-fb-action-btn" type="button" onClick={() => toast(label)}>
                {label}
              </button>
            ))}
          </div>
          <span className="mp-footer-quote">Ideas today · A brighter tomorrow</span>
        </div>
      </div>
      </main>
    </AppShell>
  );
}
