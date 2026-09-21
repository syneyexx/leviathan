/** FINALBETA Media Control overview — live /media/* APIs (visual shell preserved). */
"use client";

import { useMemo } from "react";
import { useHadesMedia } from "@/components/hades/features/media/hooks/useHadesMedia";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

type PlatformId = "youtube" | "tiktok" | "instagram" | "facebook" | "x";

function PlatformMark({ platform }: { platform: string }) {
  const id = platform.toLowerCase() as PlatformId;
  if (id === "youtube") {
    return (
      <span className="mc-brand" title="YouTube" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <rect x="2" y="6" width="20" height="12" rx="3" fill="#ff3b3b" />
          <path d="M10 9.5v5l5-2.5-5-2.5Z" fill="#fff" />
        </svg>
      </span>
    );
  }
  if (id === "tiktok") {
    return (
      <span className="mc-brand" title="TikTok" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path
            d="M14 4c.6 2.4 2.2 4 4.6 4.4V11c-1.7 0-3.2-.5-4.6-1.4V15a5 5 0 1 1-5-5c.3 0 .7 0 1 .1V13a2.2 2.2 0 1 0 2.2 2.2V4h1.8Z"
            fill="#25f4ee"
          />
        </svg>
      </span>
    );
  }
  if (id === "instagram") {
    return (
      <span className="mc-brand" title="Instagram" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <defs>
            <linearGradient id="mc-ig-grad-live" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%" stopColor="#f58529" />
              <stop offset="45%" stopColor="#dd2a7b" />
              <stop offset="100%" stopColor="#515bd4" />
            </linearGradient>
          </defs>
          <rect x="3" y="3" width="18" height="18" rx="5" fill="url(#mc-ig-grad-live)" />
          <circle cx="12" cy="12" r="4" fill="none" stroke="#fff" strokeWidth="1.6" />
          <circle cx="17" cy="7" r="1.2" fill="#fff" />
        </svg>
      </span>
    );
  }
  if (id === "facebook") {
    return (
      <span className="mc-brand" title="Facebook" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <rect x="2" y="2" width="20" height="20" rx="5" fill="#1877f2" />
          <path
            d="M13.5 20v-7h2.2l.3-2.4h-2.5V9.2c0-.7.2-1.2 1.3-1.2H16V5.8c-.2 0-1-.1-1.9-.1-1.9 0-3.2 1.2-3.2 3.3v1.6H8.5V13h2.4v7h2.6Z"
            fill="#fff"
          />
        </svg>
      </span>
    );
  }
  return (
    <span className="mc-brand" title={platform || "X"} aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <path
          d="M5 5h3.2l4 5.4L16.8 5H19l-5.2 6.6L19.2 19h-3.2l-4.3-5.8L7.2 19H5l5.5-7L5 5Z"
          fill="#e8eef2"
        />
      </svg>
    </span>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function MediaPage({ onNavigate }: Props) {
  const live = useHadesMedia();
  const overview = live.overview;
  const channels = live.channels?.items ?? overview?.campaigns ?? [];
  const projects = live.projects?.items ?? overview?.active_generation ?? [];
  const queue = overview?.publish_queue ?? live.jobs?.items ?? [];
  const trends = overview?.trending_opportunities ?? live.trends?.items ?? [];
  const blockers = overview?.blockers ?? [];
  const platforms = overview?.platforms ?? {};

  const kpis = useMemo(
    () => [
      {
        id: "engine",
        label: "Engine",
        value: overview?.engine_status || (live.loading ? "…" : "—"),
        hint: "Media engine status",
        tone: "cyan" as const,
        icon: "bolt" as const,
        live: overview?.engine_status === "ACTIVE",
      },
      {
        id: "channels",
        label: "Kanalen",
        value: live.loading && !overview ? "…" : String(overview?.channels ?? channels.length),
        hint: `${channels.filter((c) => c.enabled !== false).length} enabled`,
        tone: "blue" as const,
        icon: "users" as const,
      },
      {
        id: "producing",
        label: "In productie",
        value: String(overview?.projects_producing ?? projects.length),
        hint: "Actieve projecten",
        tone: "gold" as const,
        icon: "bolt" as const,
      },
      {
        id: "queue",
        label: "Klaar om te publiceren",
        value: String(overview?.ready_to_publish ?? queue.length),
        hint: "Publish queue",
        tone: "purple" as const,
        icon: "list" as const,
      },
      {
        id: "published",
        label: "Gepubliceerd vandaag",
        value: String(overview?.published_today ?? 0),
        hint: "Vandaag",
        tone: "green" as const,
        icon: "checkcircle" as const,
      },
      {
        id: "failures",
        label: "Failures",
        value: String(overview?.failures ?? overview?.recent_failures?.length ?? 0),
        hint: "Recente fouten",
        tone: "gold" as const,
        icon: "flask" as const,
      },
    ],
    [overview, channels, projects, queue, live.loading],
  );

  const platformRows = useMemo(() => {
    const entries = Object.entries(platforms);
    if (!entries.length) {
      const fromChannels = new Map<string, number>();
      for (const ch of channels) {
        for (const p of ch.platforms || []) {
          fromChannels.set(p, (fromChannels.get(p) || 0) + 1);
        }
      }
      return Array.from(fromChannels.entries()).map(([id, count]) => ({
        id,
        label: id,
        value: String(count),
        status: "CONFIGURED",
        color: "#4ec8f5",
      }));
    }
    return entries.map(([id, cap]) => ({
      id,
      label: cap.label || id,
      value: cap.status,
      status: cap.status,
      color: "#4ec8f5",
      detail: cap.detail,
    }));
  }, [platforms, channels]);

  const body = (
    <div className="mc-page media-control-page" data-live="media">
      <MediaWelcome
        title="Media Control"
        subtitle="Content orkestratie, publicatie, bereik en groei. Eén platform, alle kanalen."
        quote="Content moves people. AI amplifies impact."
      />

      {live.error ? (
        <div className="mc-panel" role="alert" style={{ marginBottom: 12 }}>
          <strong>Media laden mislukt.</strong> {live.error}{" "}
          <button type="button" className="mc-link-btn" onClick={() => void live.refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="mc-kpi-row">
        {kpis.map((kpi) => (
          <article key={kpi.id} className="mc-kpi">
            <span className={`mc-kpi-ico ${kpi.tone}`}>
              <FbIcon name={kpi.icon} size={15} />
              {kpi.live ? <i className="mc-live-dot" /> : null}
            </span>
            <div className="mc-kpi-body">
              <div className="mc-kpi-label">{kpi.label}</div>
              <div className="mc-kpi-value">{kpi.value}</div>
              <div className="mc-kpi-hint">{kpi.hint}</div>
            </div>
          </article>
        ))}
      </div>

      <div className="mc-mid-grid">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="chart" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#4ec8f5" }} />
                Platform capability
              </h2>
              <p>Status per publicatieplatform (geen fake bereikcijfers)</p>
            </div>
            <button type="button" className="mc-link-btn" onClick={() => void live.refresh()}>
              Vernieuwen
            </button>
          </div>
          {!platformRows.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading
                ? "Platformstatus laden…"
                : "Nog geen kanalen of platformcapabilities. Configureer media setup."}
            </p>
          ) : (
            <div className="mc-platform-row">
              {platformRows.map((p) => (
                <div key={p.id} className="mc-platform-stat">
                  <div className="mc-platform-stat-top">
                    <PlatformMark platform={p.id} />
                    <span>{p.label}</span>
                  </div>
                  <strong>{p.value}</strong>
                  {"detail" in p && p.detail ? <small>{p.detail}</small> : null}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="list" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#4ec8f5" }} />
                Publicatiewachtrij
              </h2>
              <p>Live publish jobs / queue</p>
            </div>
            <button type="button" className="mc-link-btn" data-fb-page="media-queue">
              Alles bekijken
            </button>
          </div>
          {!queue.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Wachtrij laden…" : "Nog geen publicatiejobs in de wachtrij."}
            </p>
          ) : (
            <div className="mc-queue-list">
              {queue.slice(0, 8).map((raw, index) => {
                const item = asRecord(raw);
                const title = String(item.title || item.project_title || item.id || `Job ${index + 1}`);
                const platform = String(
                  (Array.isArray(item.platforms) ? item.platforms[0] : item.platform) || "youtube",
                );
                const when = String(item.scheduled_at || item.created_at || item.status || "—");
                return (
                  <div key={String(item.id || index)} className="mc-queue-row">
                    <span className="mc-thumb t-1" />
                    <PlatformMark platform={platform} />
                    <div className="mc-queue-copy">
                      <strong>{title}</strong>
                      <small>{String(item.stage || item.status || "queued")}</small>
                    </div>
                    <div className="mc-queue-meta">
                      <div className="mc-queue-when">
                        {when}
                        <b>{String(item.status || "")}</b>
                      </div>
                      <span className="mc-pill gold">{String(item.status || "QUEUE").toUpperCase()}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="bolt" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#f59e0b" }} />
                Trending signalen
              </h2>
              <p>Live trend opportunities</p>
            </div>
            <button type="button" className="mc-link-btn" data-fb-page="media-viral">
              Alles bekijken
            </button>
          </div>
          {!trends.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Trends laden…" : "Nog geen trend signalen. Radar is leeg tot er data is."}
            </p>
          ) : (
            <div className="mc-trend-list">
              {trends.slice(0, 8).map((raw, index) => {
                const t = asRecord(raw);
                return (
                  <div key={String(t.id || index)} className="mc-trend-row">
                    <span className="mc-rank">{index + 1}</span>
                    <div className="mc-trend-copy">
                      <strong>{String(t.title || t.topic || t.query || `Trend ${index + 1}`)}</strong>
                      <small>{String(t.hint || t.summary || t.platform || "—")}</small>
                    </div>
                    <div className="mc-trend-right">
                      <span className="growth">{String(t.score ?? t.growth ?? "—")}</span>
                      <span className="mc-pill blue">{String(t.badge || t.status || "SIGNAL")}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      <div className="mc-bottom-grid">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="folder" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#4ec8f5" }} />
                Actieve projecten
              </h2>
              <p>Productiepipeline</p>
            </div>
          </div>
          {!projects.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Projecten laden…" : "Nog geen mediaprojecten."}
            </p>
          ) : (
            <div className="mc-top-list">
              {projects.slice(0, 8).map((project, index) => (
                <div key={project.id} className="mc-top-row">
                  <span className="mc-crown muted">{index + 1}</span>
                  <span className="mc-thumb t-2" />
                  <PlatformMark platform={project.platforms?.[0] || "youtube"} />
                  <div className="mc-top-copy">
                    <strong>{project.title}</strong>
                    <div className="mc-top-stats">
                      <span>{project.stage}</span>
                      <span>{Math.round(project.progress || 0)}%</span>
                    </div>
                  </div>
                  <div className="mc-top-meta">{project.updated_at || project.created_at || "—"}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="users" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#4ec8f5" }} />
                Kanalen
              </h2>
              <p>Geregistreerde media channels</p>
            </div>
            <button type="button" className="mc-link-btn" data-fb-page="youtube">
              Beheer
            </button>
          </div>
          {!channels.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Kanalen laden…" : "Nog geen kanalen geconfigureerd."}
            </p>
          ) : (
            <div className="mc-queue-list">
              {channels.slice(0, 8).map((ch) => (
                <div key={ch.id} className="mc-queue-row">
                  <PlatformMark platform={ch.platforms?.[0] || "youtube"} />
                  <div className="mc-queue-copy">
                    <strong>{ch.name}</strong>
                    <small>
                      {(ch.platforms || []).join(", ") || "geen platforms"} · {ch.autonomy_level}
                    </small>
                  </div>
                  <span className={`mc-pill ${ch.enabled === false ? "gold" : "green"}`}>
                    {ch.enabled === false ? "UIT" : "AAN"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="shield" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#f0b429" }} />
                Blockers
              </h2>
              <p>Capability / setup blockers</p>
            </div>
            <button type="button" className="mc-link-btn" data-fb-page="media">
              Setup
            </button>
          </div>
          {!blockers.length ? (
            <p className="muted" style={{ padding: 12 }}>
              Geen actieve blockers gerapporteerd.
            </p>
          ) : (
            <div className="mc-trend-list">
              {blockers.slice(0, 6).map((b) => (
                <div key={b.id} className="mc-trend-row">
                  <span className="mc-dot gold" />
                  <div className="mc-trend-copy">
                    <strong>{b.label}</strong>
                    <small>{b.detail || b.remediation || b.status}</small>
                  </div>
                  <span className="mc-pill gold">{b.status}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Content moves people. AI amplifies impact.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Media Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">/media/overview · channels · projects · trends</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Status</span>
            <span className={`v ${live.error ? "gold" : "green"}`}>
              {live.loading ? "Laden…" : live.error ? "Fout" : "Live"}
            </span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Engine</span>
            <span className="v">{overview?.engine_status || "—"}</span>
          </div>
        </div>
      </section>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Quick Actions</h3>
        <div className="stats-quick-grid">
          <button type="button" className="stats-quick-btn" onClick={() => void live.refresh()}>
            <FbIcon name="bolt" size={16} />
            <span>Vernieuwen</span>
          </button>
          <button type="button" className="stats-quick-btn" data-fb-page="media-queue">
            <FbIcon name="list" size={16} />
            <span>Wachtrij</span>
          </button>
          <button type="button" className="stats-quick-btn" data-fb-page="media-viral">
            <FbIcon name="target" size={16} />
            <span>Viral</span>
          </button>
          <button type="button" className="stats-quick-btn" data-fb-page="media-analytics">
            <FbIcon name="chart" size={16} />
            <span>Analytics</span>
          </button>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="media"
      appClassName="mc-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
