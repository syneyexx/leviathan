/** FINALBETA Media publish queue — live /media/publish jobs. */
"use client";

import { useMemo, useState } from "react";
import { useHadesMedia } from "@/components/hades/features/media/hooks/useHadesMedia";
import { donutSegments } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function statusTone(status: string): "green" | "gold" | "red" | "blue" | "gray" {
  const s = status.toLowerCase();
  if (s.includes("ready") || s.includes("approved") || s.includes("published") || s.includes("done")) return "green";
  if (s.includes("block") || s.includes("fail") || s.includes("error")) return "red";
  if (s.includes("review") || s.includes("wait") || s.includes("schedul")) return "gold";
  if (s.includes("queue") || s.includes("pending")) return "blue";
  return "gray";
}

export function MediaQueuePage({ onNavigate }: Props) {
  const live = useHadesMedia();
  const [query, setQuery] = useState("");
  const overview = live.overview;
  const queue = useMemo(() => {
    const fromOverview = overview?.publish_queue ?? [];
    const fromJobs = live.jobs?.items ?? [];
    const merged = [...fromJobs, ...fromOverview];
    const seen = new Set<string>();
    const out: Array<Record<string, unknown>> = [];
    for (const raw of merged) {
      const item = asRecord(raw);
      const id = String(item.id || item.job_id || `${item.title}-${item.created_at}-${out.length}`);
      if (seen.has(id)) continue;
      seen.add(id);
      out.push({ ...item, id });
    }
    return out;
  }, [overview, live.jobs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return queue;
    return queue.filter((item) => {
      const hay = `${item.title || ""} ${item.status || ""} ${item.platform || ""} ${item.stage || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [queue, query]);

  const slices = useMemo(() => {
    const counts = { ready: 0, review: 0, blocked: 0, queue: 0, other: 0 };
    for (const item of queue) {
      const s = String(item.status || item.stage || "").toLowerCase();
      if (s.includes("ready") || s.includes("approved") || s.includes("publish")) counts.ready += 1;
      else if (s.includes("review") || s.includes("wait")) counts.review += 1;
      else if (s.includes("block") || s.includes("fail")) counts.blocked += 1;
      else if (s.includes("queue") || s.includes("pending") || s.includes("schedul")) counts.queue += 1;
      else counts.other += 1;
    }
    return [
      { label: "Klaar", count: counts.ready, color: "#20e38d" },
      { label: "Review", count: counts.review, color: "#f0b429" },
      { label: "Geblokkeerd", count: counts.blocked, color: "#e85b5b" },
      { label: "Wachtrij", count: counts.queue, color: "#1aa4ff" },
      { label: "Overig", count: counts.other, color: "#6f8490" },
    ];
  }, [queue]);

  const donut = donutSegments(slices);
  const total = slices.reduce((n, s) => n + s.count, 0);

  const kpis = [
    {
      id: "total",
      label: "Jobs",
      value: live.loading && !queue.length ? "…" : String(queue.length),
      hint: "Publish queue",
      tone: "cyan" as const,
      icon: "list" as const,
    },
    {
      id: "ready",
      label: "Klaar om te publiceren",
      value: String(overview?.ready_to_publish ?? slices.find((s) => s.label === "Klaar")?.count ?? 0),
      hint: "Backend counter",
      tone: "green" as const,
      icon: "checkcircle" as const,
    },
    {
      id: "producing",
      label: "In productie",
      value: String(overview?.projects_producing ?? 0),
      hint: "Actieve projecten",
      tone: "gold" as const,
      icon: "bolt" as const,
    },
    {
      id: "failures",
      label: "Failures",
      value: String(overview?.failures ?? 0),
      hint: "Recente fouten",
      tone: "gold" as const,
      icon: "flask" as const,
    },
  ];

  const body = (
    <div className="mc-page mq-page" data-live="media-queue">
      <MediaWelcome
        title="Publicatiewachtrij"
        subtitle="Live publish jobs — geen fake planning of bereikcijfers."
        quote="Ship what is ready. Block what is not."
      />

      {live.error ? (
        <div className="mc-panel" role="alert" style={{ marginBottom: 12 }}>
          <strong>Wachtrij laden mislukt.</strong> {live.error}{" "}
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
              <h2>Statusverdeling</h2>
              <p>Op basis van live job status/stage</p>
            </div>
            <button type="button" className="mc-link-btn" onClick={() => void live.refresh()}>
              Vernieuwen
            </button>
          </div>
          <div className="stats-donut-wrap">
            <div className="stats-donut">
              <svg viewBox="0 0 42 42">
                <circle cx="21" cy="21" r="14" fill="none" stroke="#223544" strokeWidth="5" />
                {donut.map((seg, index) => (
                  <circle
                    key={`${seg.color}-${index}`}
                    cx="21"
                    cy="21"
                    r="14"
                    fill="none"
                    stroke={seg.color}
                    strokeWidth="5"
                    strokeDasharray={seg.dash}
                    strokeDashoffset={seg.offset}
                    transform="rotate(-90 21 21)"
                  />
                ))}
              </svg>
              <div className="stats-donut-center">
                <strong>{total}</strong>
                <span>jobs</span>
              </div>
            </div>
            <ul className="stats-donut-legend">
              {slices.map((slice) => (
                <li key={slice.label}>
                  <i style={{ background: slice.color }} />
                  <span>{slice.label}</span>
                  <b>{slice.count}</b>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Wachtrij</h2>
              <p>{filtered.length} items</p>
            </div>
            <label className="prw-search">
              <FbIcon name="search" size={12} />
              <input
                type="search"
                placeholder="Zoek jobs…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
          </div>
          {!filtered.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Jobs laden…" : "Nog geen publicatiejobs in de wachtrij."}
            </p>
          ) : (
            <div className="mc-queue-list">
              {filtered.slice(0, 40).map((item) => {
                const title = String(item.title || item.project_title || item.id);
                const status = String(item.status || item.stage || "queued");
                const platform = String(
                  (Array.isArray(item.platforms) ? item.platforms[0] : item.platform) || "—",
                );
                return (
                  <div key={String(item.id)} className="mc-queue-row">
                    <span className="mc-thumb t-1" />
                    <div className="mc-queue-copy">
                      <strong>{title}</strong>
                      <small>
                        {platform} · {String(item.scheduled_at || item.created_at || "—")}
                      </small>
                    </div>
                    <span className={`mc-pill ${statusTone(status)}`}>{status.toUpperCase()}</span>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Ship what is ready. Block what is not.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Queue Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">/media/publish · overview.publish_queue</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Status</span>
            <span className={`v ${live.error ? "gold" : "green"}`}>
              {live.loading ? "Laden…" : live.error ? "Fout" : "Live"}
            </span>
          </div>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="media-queue"
      appClassName="mc-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
