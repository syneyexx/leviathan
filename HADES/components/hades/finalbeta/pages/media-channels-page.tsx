/** FINALBETA media channel pages — pixel mockup UI (YouTube / TikTok / Instagram / Facebook). */
"use client";

import type { ReactNode } from "react";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter, McTrend } from "../media/media-chrome";
import {
  CAL_HOURS,
  FB_CAMPAIGNS,
  FB_COMMUNITY,
  FB_KPIS,
  FB_QUEUE,
  FB_SCHEDULE,
  IG_ASSETS,
  IG_CAL_EVENTS,
  IG_KPIS,
  IG_RECENT,
  IG_TOP,
  TT_BEST,
  TT_CAL_EVENTS,
  TT_KPIS,
  TT_PUB_STATUS,
  TT_TRENDS,
  TT_WEEK_STATS,
  WEEK_DAYS,
  YT_COMMUNITY,
  YT_KPIS,
  YT_PERF_STATS,
  YT_PIPELINE,
  YT_TOP,
  YT_TRAFFIC,
  YT_UPLOAD_STATUS,
  YT_UPLOADS,
} from "../mocks/media-channels";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function YtLogo({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M23.5 7.2a3 3 0 0 0-2.1-2.1C19.5 4.6 12 4.6 12 4.6s-7.5 0-9.4.5A3 3 0 0 0 .5 7.2 31.5 31.5 0 0 0 0 12a31.5 31.5 0 0 0 .5 4.8 3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1A31.5 31.5 0 0 0 24 12a31.5 31.5 0 0 0-.5-4.8Z" />
      <path fill="#fff" d="M9.8 15.5V8.5L16 12l-6.2 3.5Z" />
    </svg>
  );
}

function FbLogo({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M14 8h3V4h-3c-2.8 0-5 2.2-5 5v2H7v4h2v7h4v-7h3l1-4h-4V9c0-.6.4-1 1-1Z" />
    </svg>
  );
}

function IgLogo({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="5" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="17.5" cy="6.5" r="1.2" fill="currentColor" />
    </svg>
  );
}

function MultiLineChart({
  series,
  labels = ["18 aug", "25 aug", "1 sep", "8 sep", "15 sep"],
}: {
  series: { color: string; points: string }[];
  labels?: string[];
}) {
  return (
    <svg className="ch-chart tall" viewBox="0 0 560 180" preserveAspectRatio="none" aria-hidden="true">
      {[40, 80, 120].map((y) => (
        <line key={y} x1="36" y1={y} x2="548" y2={y} stroke="rgba(70,120,160,0.18)" strokeWidth="1" />
      ))}
      {series.map((s) => (
        <path key={s.color} d={s.points} fill="none" stroke={s.color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
      ))}
      {labels.map((label, i) => (
        <text key={label} x={36 + i * 128} y="172" fill="#6f8490" fontSize="10">
          {label}
        </text>
      ))}
    </svg>
  );
}

function RetentionChart() {
  return (
    <svg className="ch-chart tall" viewBox="0 0 420 180" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="retFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.45" />
          <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path
        d="M28 28 C 90 30, 120 38, 160 55 C 210 78, 250 95, 290 108 C 330 120, 360 128, 400 132 L 400 160 L 28 160 Z"
        fill="url(#retFill)"
      />
      <path
        d="M28 28 C 90 30, 120 38, 160 55 C 210 78, 250 95, 290 108 C 330 120, 360 128, 400 132"
        fill="none"
        stroke="#38bdf8"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <circle cx="290" cy="108" r="4" fill="#38bdf8" />
      <line x1="290" y1="40" x2="290" y2="150" stroke="rgba(56,189,248,0.35)" strokeDasharray="3 3" />
      <text x="250" y="36" fill="#9db4bf" fontSize="10">
        62% Gemiddeld
      </text>
      {["0:00", "2:00", "4:00", "6:00", "8:00", "10:00"].map((t, i) => (
        <text key={t} x={28 + i * 74} y="172" fill="#6f8490" fontSize="10">
          {t}
        </text>
      ))}
    </svg>
  );
}

function WeekCalendar({
  events,
  highlightDay = 1,
}: {
  events: readonly { day: number; time: string; label: string; tone: string }[];
  highlightDay?: number;
}) {
  const hourIndex = (time: string) => Math.max(0, CAL_HOURS.findIndex((h) => h === time));
  return (
    <div className="ch-cal">
      <div />
      {WEEK_DAYS.map((d, i) => (
        <div key={d.key} className={`ch-cal-head${i === highlightDay ? " active" : ""}`}>
          {d.label} {d.date}
        </div>
      ))}
      {CAL_HOURS.map((hour, hi) => (
        <div key={hour} style={{ display: "contents" }}>
          <div className="ch-cal-hour">{hour}</div>
          {WEEK_DAYS.map((d, di) => {
            const ev = events.find((e) => e.day === di && hourIndex(e.time) === hi);
            return (
              <div key={`${d.key}-${hour}`} className="ch-cal-cell">
                {ev ? <div className={`ch-cal-event ${ev.tone}`}>{ev.label}</div> : null}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function ChannelShell({
  page,
  appExtra,
  body,
  inspector,
  onNavigate,
}: {
  page: "youtube" | "tiktok" | "instagram" | "facebook";
  appExtra: string;
  body: ReactNode;
  inspector: ReactNode;
  onNavigate: FinalBetaNavigate;
}) {
  return (
    <FinalBetaShell
      page={page}
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName={`mc-app media-channel-app ${appExtra}`}
      mainClassName="mc-main"
      footer={<McFooter />}
    />
  );
}

/* ───────────────────────── YouTube ───────────────────────── */

export function YoutubePage({ onNavigate }: Props) {
  const body = (
    <div className="ch-page">
      <MediaWelcome
        title={
          <>
            <span className="ch-brand-ico yt">
              <YtLogo size={15} />
            </span>
            YouTube
          </>
        }
        subtitle="Analyseer, creëer en beheer je YouTube kanaal. Van idee tot impact, volledig geïntegreerd."
        quote="Content today. Opportunities tomorrow."
      />

      <div className="mc-kpi-row">
        {YT_KPIS.map((k) => (
          <article key={k.id} className="mc-kpi ch-kpi">
            <span className="ch-kpi-ico">
              <FbIcon name={k.icon} size={14} />
            </span>
            <div>
              <div className="mc-kpi-label">{k.label}</div>
              <div className="ch-kpi-top">
                <div className="mc-kpi-value">{k.value}</div>
                <McTrend value={`↑ ${k.trend}`} />
              </div>
              <div className="mc-kpi-hint">{k.hint}</div>
            </div>
          </article>
        ))}
      </div>

      <div className="ch-grid-2">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Kanaalprestatie</h2>
              <p>Weergaven, abonnees en kijktijd in de afgelopen 30 dagen.</p>
            </div>
          </div>
          <div className="ch-mini-stats">
            {YT_PERF_STATS.map((s) => (
              <div key={s.label} className="ch-mini-stat">
                <div className="lbl">{s.label}</div>
                <div className="val">
                  {s.value} <McTrend value={s.trend} />
                </div>
              </div>
            ))}
          </div>
          <MultiLineChart
            series={[
              { color: "#eab94f", points: "M36 120 C 100 110, 160 95, 220 78 C 280 62, 340 48, 420 42 C 480 38, 520 36, 548 34" },
              { color: "#22d3ee", points: "M36 140 C 100 132, 160 118, 220 108 C 280 96, 340 88, 420 80 C 480 74, 520 70, 548 66" },
              { color: "#f472b6", points: "M36 130 C 100 124, 160 112, 220 100 C 280 90, 340 78, 420 70 C 480 64, 520 58, 548 54" },
              { color: "#22c55e", points: "M36 150 C 100 146, 160 138, 220 128 C 280 118, 340 110, 420 100 C 480 94, 520 90, 548 86" },
            ]}
          />
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Publieksretentie</h2>
              <p>Gemiddelde kijkduur per video.</p>
            </div>
          </div>
          <div className="ch-retention-head">
            <div className="ch-retention-big">
              62%
              <small>Gemiddelde retentie</small>
            </div>
            <McTrend value="↑ +8%" />
          </div>
          <RetentionChart />
        </section>
      </div>

      <div className="ch-grid-2">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Video pipeline</h2>
              <p>Van idee tot publicatie. Beheer je content workflow.</p>
            </div>
          </div>
          <div className="ch-kanban">
            {(
              [
                ["Ideeën", YT_PIPELINE.ideeën],
                ["In productie", YT_PIPELINE.productie],
                ["Review", YT_PIPELINE.review],
                ["Klaar", YT_PIPELINE.klaar],
              ] as const
            ).map(([title, items]) => (
              <div key={title} className="ch-kanban-col">
                <div className="ch-kanban-head">
                  <span>{title}</span>
                  <span className="ch-kanban-count">({items.length})</span>
                </div>
                {items.map((item) => (
                  <div key={item.title} className="ch-kanban-card">
                    <strong>{item.title}</strong>
                    <small>
                      {item.meta === "Gereed" ? <span className="mc-pill green">Gereed</span> : item.meta}
                    </small>
                  </div>
                ))}
                <button type="button" className="ch-kanban-add" data-toast="+ Nieuwe video">
                  + Nieuwe video
                </button>
              </div>
            ))}
          </div>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Recente uploads</h2>
              <p>Laatst gepubliceerde video&apos;s op je kanaal.</p>
            </div>
          </div>
          <div className="ch-upload-list">
            {YT_UPLOADS.map((u) => (
              <div key={u.title} className="ch-upload-row">
                <div className="mc-thumb lg" />
                <div className="ch-upload-copy">
                  <strong>
                    {u.title} · {u.duration}
                  </strong>
                  <div className="ch-upload-meta">
                    <span>{u.views} views</span>
                    <span>{u.likes} likes</span>
                    <span>{u.comments} reacties</span>
                  </div>
                </div>
                <span className="ch-upload-ago">{u.ago}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="ch-grid-3">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Community & reacties</h2>
              <p>Activiteit rondom je content.</p>
            </div>
          </div>
          <div className="ch-community-grid">
            {YT_COMMUNITY.map((c) => (
              <div key={c.label} className="ch-community-cell">
                <span className="ico">
                  <FbIcon name={c.icon} size={13} />
                </span>
                <div>
                  <div className="lbl">{c.label}</div>
                  <div className="val">{c.value}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Top traffic sources</h2>
              <p>Waar je kijkers vandaan komen.</p>
            </div>
          </div>
          <div className="ch-bars">
            {YT_TRAFFIC.map((t) => (
              <div key={t.label} className="ch-bar-row">
                <span className="lbl">{t.label}</span>
                <div className="ch-bar-track">
                  <span style={{ width: `${t.pct}%` }} />
                </div>
                <span className="pct">{t.pct}%</span>
              </div>
            ))}
          </div>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Top video&apos;s (30 dagen)</h2>
              <p>Best presterende uploads.</p>
            </div>
          </div>
          <div className="ch-top-list">
            {YT_TOP.map((v) => (
              <div key={v.rank} className="ch-top-row">
                <span className="rank">{v.rank}</span>
                <span className="title">{v.title}</span>
                <span className="views">{v.views}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Create. Inspire. Grow beyond limits.”</p>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Kanaalprofiel</h3>
        <div className="mc-insp-card">
          <div className="ch-profile">
            <span className="ch-avatar">H</span>
            <div>
              <strong>HADES @HADES</strong>
              <small>AI, technology & a brighter tomorrow.</small>
            </div>
          </div>
          <div className="ch-tags">
            {["Tech", "AI", "Automation", "Education"].map((t) => (
              <span key={t} className="ch-tag">
                {t}
              </span>
            ))}
          </div>
          <div className="mc-detail-row">
            <span className="k">Abonnees</span>
            <span className="v">125K</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Video&apos;s</span>
            <span className="v">248</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Weergaven</span>
            <span className="v">12.8M</span>
          </div>
          <button type="button" className="btn btn-sm btn-outline btn-block" style={{ marginTop: 8 }} data-toast="Link kanaal">
            Link kanaal
          </button>
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Live metrics</h3>
        <div className="mc-insp-card">
          <div className="ch-live-badge">
            <span className="mc-dot green" /> Live
          </div>
          <div className="mc-detail-row">
            <span className="k">Huidige kijkers</span>
            <span className="v">1.2K</span>
          </div>
          <svg className="ch-chart" viewBox="0 0 260 56" aria-hidden="true">
            {[18, 28, 22, 36, 30, 42, 38, 48, 40, 52, 46, 44].map((h, i) => (
              <rect key={i} x={8 + i * 20} y={56 - h} width="12" height={h} rx="2" fill="#22d3ee" opacity={0.75} />
            ))}
          </svg>
          <small style={{ color: "#7f96a4", fontSize: 10 }}>Realtime weergaven (laatste 60 min)</small>
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Upload status</h3>
        <div className="mc-insp-card ch-status-list">
          {YT_UPLOAD_STATUS.map((u) => (
            <div key={u.name} className="ch-status-row">
              <strong>{u.name}</strong>
              <div className="meta">
                <span>{u.status}</span>
                <span>
                  {u.pct}% · {u.hint}
                </span>
              </div>
              <div className="mc-progress">
                <span style={{ width: `${u.pct}%`, background: u.pct === 100 ? "linear-gradient(90deg,#22c55e,#4ade80)" : undefined }} />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Snelle acties</h3>
        <div className="mc-action-stack">
          {[
            ["Nieuwe video publiceren", "upload"],
            ["Script genereren met AI", "bolt"],
            ["Thumbnail maken", "image"],
            ["Video analyseren", "chart"],
          ].map(([label, icon]) => (
            <button key={label} type="button" className="btn btn-sm btn-outline btn-block" data-toast={label}>
              <FbIcon name={icon} size={13} />
              {label}
            </button>
          ))}
        </div>
      </section>
    </>
  );

  return <ChannelShell page="youtube" appExtra="yt-app" body={body} inspector={inspector} onNavigate={onNavigate} />;
}

/* ───────────────────────── TikTok ───────────────────────── */

export function TiktokPage({ onNavigate }: Props) {
  const body = (
    <div className="ch-page">
      <MediaWelcome
        title={
          <>
            <span className="ch-brand-ico tt">
              <FbIcon name="play" size={14} />
            </span>
            TikTok
          </>
        }
        subtitle="Beheer je short-form content, ontdek trends en maximaliseer je bereik."
        quote="Short form. Longer impact."
      />

      <div className="mc-kpi-row">
        {TT_KPIS.map((k) => (
          <article key={k.id} className="mc-kpi ch-kpi">
            <span className="ch-kpi-ico">
              <FbIcon name={k.icon} size={14} />
            </span>
            <div>
              <div className="mc-kpi-label">{k.label}</div>
              <div className="ch-kpi-top">
                <div className="mc-kpi-value">{k.value}</div>
                <McTrend value={`↑ ${k.trend}`} />
              </div>
              <div className="mc-kpi-hint">{k.hint}</div>
            </div>
          </article>
        ))}
      </div>

      <div className="ch-grid-2">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Contentprestaties</h2>
              <p>Views, engagement en volgersgroei over de tijd.</p>
            </div>
            <div className="ch-panel-tools">
              <button type="button" className="btn btn-sm btn-outline" data-toast="Periode">
                Laatste 30 dagen
                <FbIcon name="chevron" size={11} />
              </button>
            </div>
          </div>
          <MultiLineChart
            series={[
              { color: "#22d3ee", points: "M36 130 C 100 120, 160 105, 220 90 C 280 72, 340 58, 420 48 C 480 42, 520 38, 548 34" },
              { color: "#a78bfa", points: "M36 145 C 100 138, 160 128, 220 118 C 280 108, 340 98, 420 90 C 480 84, 520 80, 548 76" },
              { color: "#22c55e", points: "M36 155 C 100 150, 160 142, 220 134 C 280 126, 340 118, 420 110 C 480 104, 520 100, 548 96" },
            ]}
          />
          <div className="ch-legend" style={{ marginTop: 6 }}>
            <span>
              <i className="mc-dot cyan" /> Views
            </span>
            <span>
              <i className="mc-dot purple" /> Engagement
            </span>
            <span>
              <i className="mc-dot green" /> Volgers
            </span>
          </div>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Trenddetectie</h2>
              <p>AI-detectie van opkomende trends in jouw niche.</p>
            </div>
            <button type="button" className="btn btn-sm btn-outline" data-toast="Alles bekijken">
              Alles bekijken
            </button>
          </div>
          <div className="ch-trend-list">
            {TT_TRENDS.map((t) => (
              <div key={t.title} className="ch-trend-row">
                <div className="mc-thumb sq" />
                <div className="ch-trend-copy">
                  <strong>{t.title}</strong>
                  <small>{t.tags}</small>
                </div>
                <div className="ch-trend-right">
                  <McTrend value={`↑ ${t.growth}`} />
                  <span className={`mc-pill ${t.tone}`}>{t.status}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="ch-grid-2 equal">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Beste presterende video&apos;s</h2>
              <p>Top content op basis van views, engagement en conversie.</p>
            </div>
          </div>
          <table className="mc-table">
            <thead>
              <tr>
                <th>#</th>
                <th />
                <th>Titel</th>
                <th>Views</th>
                <th>Likes</th>
                <th>Reacties</th>
                <th>Engagement</th>
                <th>Gepubliceerd</th>
              </tr>
            </thead>
            <tbody>
              {TT_BEST.map((v, i) => (
                <tr key={v.title}>
                  <td>{i + 1}</td>
                  <td>
                    <div className="mc-thumb" />
                  </td>
                  <td>{v.title}</td>
                  <td>{v.views}</td>
                  <td>{v.likes}</td>
                  <td>{v.comments}</td>
                  <td>{v.eng}</td>
                  <td>{v.ago}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Contentkalender</h2>
              <p>Geplande en recente TikTok publicaties.</p>
            </div>
            <div className="ch-panel-tools">
              <button type="button" className="btn btn-sm btn-gold" data-toast="+ Nieuwe video">
                + Nieuwe video
              </button>
              <button type="button" className="btn btn-sm btn-outline" data-toast="Vandaag">
                Vandaag
              </button>
              <button type="button" className="btn btn-sm btn-outline" data-toast="Week">
                11 – 17 sep 2026
              </button>
            </div>
          </div>
          <WeekCalendar events={TT_CAL_EVENTS} />
          <div className="ch-legend">
            <span>
              <i className="mc-dot blue" /> Gepubliceerd
            </span>
            <span>
              <i className="mc-dot cyan" /> Gepland
            </span>
            <span>
              <i className="mc-dot gold" /> In concept
            </span>
            <span>
              <i className="mc-dot orange" /> In review
            </span>
          </div>
        </section>
      </div>

      <div className="ch-ai-strip">
        <div className="ch-ai-copy">
          <strong>Optimaliseer je content</strong>
          <small>Gebruik AI om betere hooks, scripts en thumbnails te maken.</small>
        </div>
        {[
          ["AI hook generator", "bolt"],
          ["Script schrijven", "file"],
          ["Thumbnail suggesties", "image"],
          ["Beste publicatietijd", "clock"],
          ["Content repurposing", "refresh"],
        ].map(([label, icon]) => (
          <button key={label} type="button" className="ch-ai-btn" data-toast={label}>
            <span className="ico">
              <FbIcon name={icon} size={14} />
            </span>
            {label}
          </button>
        ))}
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Trends today. Communities tomorrow.”</p>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Kanaaloverzicht</h3>
        <div className="mc-insp-card">
          <div className="ch-profile">
            <span className="ch-avatar">H</span>
            <div>
              <strong>HADES</strong>
              <small>@hades.ai</small>
            </div>
          </div>
          {[
            ["Volgers", "89K", "+28%"],
            ["Totaal likes", "2.4M", "+34%"],
            ["Totaal views", "18.6M", "+41%"],
            ["Video's", "412", "+12%"],
            ["Gem. engagement", "8.4%", "+32%"],
          ].map(([k, v, t]) => (
            <div key={k} className="mc-detail-row">
              <span className="k">{k}</span>
              <span className="v">
                {v} <McTrend value={t} />
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Prestatie laatste 7 dagen</h3>
        <div className="mc-insp-card">
          <div className="ch-week-bars">
            {[40, 55, 48, 70, 62, 78, 85].map((h, i) => (
              <span key={i} style={{ height: `${h}%` }} />
            ))}
          </div>
          {TT_WEEK_STATS.map((s) => (
            <div key={s.label} className="mc-detail-row">
              <span className="k">{s.label}</span>
              <span className="v">
                {s.value} <McTrend value={s.trend} />
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Publicatiestatus</h3>
        <div className="mc-insp-card">
          {TT_PUB_STATUS.map((s) => (
            <div key={s.label} className="mc-detail-row">
              <span className="k">{s.label}</span>
              <span className="v">
                {s.value} <McTrend value={s.trend} tone={s.tone} />
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Snelle acties</h3>
        <div className="mc-action-stack">
          {[
            ["Nieuwe TikTok video", "Upload of maak content", "upload"],
            ["Reeks plannen", "Plan meerdere video's", "calendar"],
            ["Trend analyse", "Ontdek trending geluiden", "chart"],
            ["AI script genereren", "Genereer hooks en scripts", "bolt"],
          ].map(([label, hint, icon]) => (
            <button key={label} type="button" className="btn btn-sm btn-outline btn-block" data-toast={label}>
              <FbIcon name={icon} size={13} />
              <span style={{ textAlign: "left" }}>
                <strong style={{ display: "block", fontWeight: 600 }}>{label}</strong>
                <small style={{ color: "#7f96a4", fontWeight: 400 }}>{hint}</small>
              </span>
            </button>
          ))}
        </div>
      </section>
    </>
  );

  return <ChannelShell page="tiktok" appExtra="tt-app" body={body} inspector={inspector} onNavigate={onNavigate} />;
}

/* ───────────────────────── Facebook ───────────────────────── */

export function FacebookPage({ onNavigate }: Props) {
  const body = (
    <div className="ch-page">
      <MediaWelcome
        title={
          <>
            <span className="ch-brand-ico fb">
              <FbLogo size={15} />
            </span>
            Facebook
          </>
        }
        subtitle="Beheer je pagina, publiceer content en bouw je community vanuit één commandocentrum."
        quote="Community vandaag. Grotere kansen morgen."
      />

      <div className="mc-kpi-row">
        {FB_KPIS.map((k) => (
          <article key={k.id} className="mc-kpi ch-kpi">
            <span className="ch-kpi-ico">
              <FbIcon name={k.icon} size={14} />
            </span>
            <div>
              <div className="mc-kpi-label">{k.label}</div>
              <div className="ch-kpi-top">
                <div className="mc-kpi-value">{k.value}</div>
                <McTrend value={`↑ ${k.trend}`} />
              </div>
              <div className="mc-kpi-hint">{k.hint}</div>
            </div>
          </article>
        ))}
      </div>

      <div className="ch-grid-2">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Geplande posts</h2>
              <p>Overzicht van geplande Facebook content.</p>
            </div>
            <div className="ch-panel-tools">
              <div className="mc-tabs">
                <button type="button" className="mc-tab">
                  Vandaag
                </button>
                <button type="button" className="mc-tab active">
                  Week
                </button>
              </div>
              <button type="button" className="btn btn-sm btn-outline" data-toast="Periode">
                11 – 17 sep 2026
              </button>
              <button type="button" className="btn btn-sm btn-gold" data-toast="+ Nieuwe post">
                + Nieuwe post
              </button>
            </div>
          </div>
          <WeekCalendar events={FB_SCHEDULE} />
          <div className="ch-legend">
            <span>
              <i className="mc-dot blue" /> Pagina post
            </span>
            <span>
              <i className="mc-dot cyan" /> Video
            </span>
            <span>
              <i className="mc-dot purple" /> Afbeelding
            </span>
            <span>
              <i className="mc-dot red" /> Live
            </span>
            <span>
              <i className="mc-dot blue" /> Link
            </span>
            <span>
              <i className="mc-dot gold" /> Concept
            </span>
            <span>
              <i className="mc-dot cyan" /> Gepland
            </span>
            <span>
              <i className="mc-dot green" /> Gepubliceerd
            </span>
          </div>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Campagne distributie</h2>
              <p>Actieve en geplande campagnes.</p>
            </div>
            <button type="button" className="btn btn-sm btn-gold" data-toast="+ Nieuwe campagne">
              + Nieuwe campagne
            </button>
          </div>
          <div className="ch-campaigns">
            {FB_CAMPAIGNS.map((c) => (
              <div key={c.title} className="ch-campaign-row">
                <div className="mc-thumb sq" />
                <div className="ch-campaign-copy">
                  <strong>{c.title}</strong>
                  <div className="ch-campaign-meta">
                    <span className={`mc-pill ${c.tone}`}>{c.status}</span>
                    <div className="ch-bar-track" style={{ flex: 1 }}>
                      <span style={{ width: `${Math.round((c.done / c.total) * 100)}%` }} />
                    </div>
                    <span className="frac">
                      {c.done}/{c.total}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="ch-grid-2 equal">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Community interacties</h2>
              <p>Recente reacties, berichten en vermeldingen.</p>
            </div>
            <div className="ch-panel-tools">
              <div className="mc-tabs">
                {["Alle", "Reacties", "Berichten", "Vermeldingen"].map((t, i) => (
                  <button key={t} type="button" className={`mc-tab${i === 0 ? " active" : ""}`}>
                    {t}
                  </button>
                ))}
              </div>
              <button type="button" className="btn btn-sm btn-outline" data-toast="Alles bekijken">
                Alles bekijken
              </button>
            </div>
          </div>
          <div className="ch-feed">
            {FB_COMMUNITY.map((c) => (
              <div key={c.name + c.ago} className="ch-feed-row">
                <span className="ch-feed-avatar">{c.name.slice(0, 1)}</span>
                <div className="ch-feed-copy">
                  <strong>
                    {c.name}
                    <span className="ago">{c.ago}</span>
                  </strong>
                  <p>{c.text}</p>
                </div>
                <button type="button" className="btn btn-sm btn-outline" data-toast="Beantwoorden">
                  Beantwoorden
                </button>
              </div>
            ))}
          </div>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Content queue</h2>
              <p>Concepten en klaar voor publicatie.</p>
            </div>
            <button type="button" className="btn btn-sm btn-outline" data-toast="Alles bekijken">
              Alles bekijken
            </button>
          </div>
          <div className="ch-queue-list">
            {FB_QUEUE.map((q) => (
              <div key={q.title} className="ch-queue-row">
                <div className="mc-thumb lg" />
                <div className="ch-queue-copy">
                  <strong>{q.title}</strong>
                  <small>
                    {q.kind} · {q.when}
                  </small>
                </div>
                <span className={`mc-pill ${q.status === "Gereed" ? "green" : "gray"}`}>{q.status}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="ch-ai-strip fb-tools">
        <div className="ch-ai-copy">
          <strong>Maak snel Facebook content</strong>
          <small>Gebruik AI en templates om sneller te creëren.</small>
        </div>
        {[
          ["Post genereren", "file"],
          ["Afbeelding maken", "image"],
          ["Video genereren", "play"],
          ["Copy voorstellen", "bolt"],
          ["Planning instellen", "calendar"],
        ].map(([label, icon]) => (
          <button key={label} type="button" className="ch-ai-btn" data-toast={label}>
            <span className="ico">
              <FbIcon name={icon} size={14} />
            </span>
            {label}
          </button>
        ))}
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Same story. A bigger tomorrow.”</p>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Pagina overzicht</h3>
        <div className="mc-insp-card">
          <div className="ch-profile">
            <span className="ch-avatar">H</span>
            <div>
              <strong>HADES @HADES</strong>
              <small>
                <span className="mc-pill green">Actief</span>
              </small>
            </div>
          </div>
          <div className="ch-insp-stats">
            <div className="ch-insp-stat">
              <div className="lbl">Volgers</div>
              <div className="val">38K</div>
            </div>
            <div className="ch-insp-stat">
              <div className="lbl">Bereik (30d)</div>
              <div className="val">
                316K <McTrend value="+9%" />
              </div>
            </div>
            <div className="ch-insp-stat">
              <div className="lbl">Betrokkenheid</div>
              <div className="val">
                4.2K <McTrend value="+36%" />
              </div>
            </div>
          </div>
          <div className="ch-link-list" style={{ marginTop: 8 }}>
            {["Pagina bekijken", "Analytics", "Advertentieaccount", "Instellingen"].map((l) => (
              <button key={l} type="button" className="ch-link-btn" data-toast={l}>
                {l}
                <FbIcon name="chevron" size={12} />
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Community groei</h3>
        <div className="mc-insp-card">
          <MultiLineChart
            series={[{ color: "#22d3ee", points: "M36 140 C 100 130, 160 118, 220 100 C 280 84, 340 70, 420 58 C 480 50, 520 44, 548 40" }]}
          />
          <div className="mc-detail-row">
            <span className="k">Volgers</span>
            <span className="v">
              38K <McTrend value="+9%" />
            </span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Nieuwe volgers</span>
            <span className="v">
              612 <McTrend value="+28%" />
            </span>
          </div>
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Snelle acties</h3>
        <div className="mc-action-stack">
          {[
            ["Nieuwe post", "Maak en plan een bericht", "plus"],
            ["Live gaan", "Start een live video", "play"],
            ["Advertentie maken", "Promoot je content", "target"],
            ["Inzichten bekijken", "Bekijk paginastatistieken", "chart"],
            ["Berichten beheren", "Reageer op comments & DM's", "chat"],
          ].map(([label, hint, icon]) => (
            <button key={label} type="button" className="btn btn-sm btn-outline btn-block" data-toast={label}>
              <FbIcon name={icon} size={13} />
              <span style={{ textAlign: "left" }}>
                <strong style={{ display: "block", fontWeight: 600 }}>{label}</strong>
                <small style={{ color: "#7f96a4", fontWeight: 400 }}>{hint}</small>
              </span>
            </button>
          ))}
        </div>
      </section>
    </>
  );

  return <ChannelShell page="facebook" appExtra="fb-app" body={body} inspector={inspector} onNavigate={onNavigate} />;
}

/* ───────────────────────── Instagram ───────────────────────── */

export function InstagramPage({ onNavigate }: Props) {
  const body = (
    <div className="ch-page">
      <MediaWelcome
        title={
          <>
            <span className="ch-brand-ico ig">
              <IgLogo size={14} />
            </span>
            Instagram
          </>
        }
        subtitle="Beheer en optimaliseer je Instagram content, groei je bereik en engageer je community."
        quote="Visual stories. Real impact."
      />

      <div className="mc-kpi-row">
        {IG_KPIS.map((k) => (
          <article key={k.id} className="mc-kpi ch-kpi">
            <span className="ch-kpi-ico">
              <FbIcon name={k.icon} size={14} />
            </span>
            <div>
              <div className="mc-kpi-label">{k.label}</div>
              <div className="ch-kpi-top">
                <div className="mc-kpi-value">{k.value}</div>
                <McTrend value={`↑ ${k.trend}`} />
              </div>
              <div className="mc-kpi-hint">{k.hint}</div>
            </div>
          </article>
        ))}
      </div>

      <div className="ch-grid-2">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Contentkalender</h2>
              <p>Posts, reels en stories deze week.</p>
            </div>
            <div className="ch-panel-tools">
              <button type="button" className="btn btn-sm btn-outline" data-toast="Vandaag">
                Vandaag
              </button>
              <button type="button" className="btn btn-sm btn-outline" data-toast="Week">
                11 – 17 sep 2026 · Week
              </button>
            </div>
          </div>
          <WeekCalendar events={IG_CAL_EVENTS} />
          <div className="ch-legend">
            <span>
              <i className="mc-dot blue" /> Post
            </span>
            <span>
              <i className="mc-dot pink" /> Reel
            </span>
            <span>
              <i className="mc-dot purple" /> Story
            </span>
            <span>
              <i className="mc-dot gold" /> Concept
            </span>
            <span>
              <i className="mc-dot cyan" /> Gepland
            </span>
            <span>
              <i className="mc-dot green" /> Gepubliceerd
            </span>
          </div>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Recente content</h2>
              <p>Laatst gepubliceerde posts, reels en stories.</p>
            </div>
            <div className="ch-panel-tools">
              <div className="mc-tabs">
                {["Alle", "Posts", "Reels", "Stories"].map((t, i) => (
                  <button key={t} type="button" className={`mc-tab${i === 0 ? " active" : ""}`}>
                    {t}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="ch-content-grid">
            {IG_RECENT.map((c) => (
              <div key={c.title} className="ch-content-card">
                <span className="kind">{c.kind}</span>
                <div className="meta">
                  <strong>{c.title}</strong>
                  <span>
                    {c.views} · {c.likes}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="ch-grid-2 equal">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Prestaties</h2>
              <p>Bereik, views, engagement over 30 dagen.</p>
            </div>
            <button type="button" className="btn btn-sm btn-outline" data-toast="Periode">
              Laatste 30 dagen
              <FbIcon name="chevron" size={11} />
            </button>
          </div>
          <div className="ch-mini-stats">
            {[
              ["Bereik", "316K", "+28%"],
              ["Weergaven", "1.2M", "+46%"],
              ["Engagement", "8.4%", "+22%"],
              ["Profiel kliks", "24K", "+21%"],
            ].map(([l, v, t]) => (
              <div key={l} className="ch-mini-stat">
                <div className="lbl">{l}</div>
                <div className="val">
                  {v} <McTrend value={t} />
                </div>
              </div>
            ))}
          </div>
          <MultiLineChart
            series={[
              { color: "#eab94f", points: "M36 120 C 100 110, 160 95, 220 78 C 280 62, 340 48, 420 42 C 480 38, 520 36, 548 34" },
              { color: "#22d3ee", points: "M36 140 C 100 132, 160 118, 220 108 C 280 96, 340 88, 420 80 C 480 74, 520 70, 548 66" },
              { color: "#a78bfa", points: "M36 130 C 100 124, 160 112, 220 100 C 280 90, 340 78, 420 70 C 480 64, 520 58, 548 54" },
              { color: "#22c55e", points: "M36 150 C 100 146, 160 138, 220 128 C 280 118, 340 110, 420 100 C 480 94, 520 90, 548 86" },
            ]}
          />
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Asset queue</h2>
              <p>Media waiting for publication.</p>
            </div>
            <button type="button" className="btn btn-sm btn-outline" data-toast="Alles bekijken">
              Alles bekijken
            </button>
          </div>
          <div className="ch-status-list">
            {IG_ASSETS.map((a) => (
              <div key={a.name} className="ch-queue-row">
                <div className="mc-thumb sq" />
                <div className="ch-status-row" style={{ flex: 1 }}>
                  <strong>{a.name}</strong>
                  <div className="meta">
                    <span>{a.res}</span>
                    <span className={`mc-pill ${a.tone}`}>{a.status}</span>
                  </div>
                  <div className="mc-progress">
                    <span
                      style={{
                        width: `${a.pct}%`,
                        background:
                          a.tone === "green"
                            ? "linear-gradient(90deg,#22c55e,#4ade80)"
                            : a.tone === "gold"
                              ? "linear-gradient(90deg,#eab94f,#f59e0b)"
                              : undefined,
                      }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="ch-ai-strip">
        <div className="ch-ai-copy">
          <strong>Maak snel nieuwe content</strong>
          <small>Posts, reels, stories en planning in één strip.</small>
        </div>
        {[
          ["Post maken", "squareplus"],
          ["Reel maken", "play"],
          ["Story maken", "image"],
          ["Content plannen", "calendar"],
          ["AI assistentie", "bolt"],
        ].map(([label, icon]) => (
          <button key={label} type="button" className="ch-ai-btn" data-toast={label}>
            <span className="ico">
              <FbIcon name={icon} size={14} />
            </span>
            {label}
          </button>
        ))}
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Create today. Inspire tomorrow.”</p>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Account overzicht</h3>
        <div className="mc-insp-card">
          <div className="ch-profile">
            <span className="ch-avatar">H</span>
            <div>
              <strong>@hades.ai</strong>
              <small>
                64K followers <McTrend value="+16%" />
              </small>
            </div>
          </div>
          <div className="ch-insp-stats">
            {[
              ["Berichten", "482", "+12%"],
              ["Reels", "168", "+38%"],
              ["Stories", "921", "+25%"],
            ].map(([l, v, t]) => (
              <div key={l} className="ch-insp-stat">
                <div className="lbl">{l}</div>
                <div className="val">
                  {v} <McTrend value={t} />
                </div>
              </div>
            ))}
          </div>
          {[
            ["Totaal bereik", "316K", "+28%"],
            ["Profielbezoeken", "24K", "+21%"],
            ["Website clicks", "6.8K", "+34%"],
          ].map(([k, v, t]) => (
            <div key={k} className="mc-detail-row">
              <span className="k">{k}</span>
              <span className="v">
                {v} <McTrend value={t} />
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Top content (30 dagen)</h3>
        <div className="mc-insp-card ch-top-list">
          {IG_TOP.map((t, i) => (
            <div key={t.title} className="ch-top-row" style={{ gridTemplateColumns: "auto 1fr auto" }}>
              <div className="mc-thumb" />
              <span className="title">
                {i + 1}. {t.title}
              </span>
              <span className="views">{t.views}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Snelle acties</h3>
        <div className="mc-action-stack">
          {[
            ["Nieuwe post", "Maak een Instagram post", "squareplus"],
            ["Nieuwe reel", "Start een nieuwe reel", "play"],
            ["Nieuwe story", "Deel een story", "image"],
            ["Content plannen", "Plan je volgende post", "calendar"],
            ["Trend analyse", "Ontdek trending content", "chart"],
          ].map(([label, hint, icon]) => (
            <button key={label} type="button" className="btn btn-sm btn-outline btn-block" data-toast={label}>
              <FbIcon name={icon} size={13} />
              <span style={{ textAlign: "left" }}>
                <strong style={{ display: "block", fontWeight: 600 }}>{label}</strong>
                <small style={{ color: "#7f96a4", fontWeight: 400 }}>{hint}</small>
              </span>
            </button>
          ))}
        </div>
      </section>
    </>
  );

  return <ChannelShell page="instagram" appExtra="ig-app" body={body} inspector={inspector} onNavigate={onNavigate} />;
}
