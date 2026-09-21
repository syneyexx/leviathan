/** FINALBETA Media Calendar — live projects + publish queue as schedule. */
"use client";

import { useMemo, useState } from "react";
import { useHadesMedia } from "@/components/hades/features/media/hooks/useHadesMedia";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

const MONTH_NAMES = [
  "januari",
  "februari",
  "maart",
  "april",
  "mei",
  "juni",
  "juli",
  "augustus",
  "september",
  "oktober",
  "november",
  "december",
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function parseDay(value: unknown): string | null {
  if (!value) return null;
  const s = String(value);
  const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1]! : null;
}

export function MediaCalendarPage({ onNavigate }: Props) {
  const live = useHadesMedia();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth());

  const entries = useMemo(() => {
    const projects = live.projects?.items ?? live.overview?.active_generation ?? [];
    const queue = (live.overview?.publish_queue ?? live.jobs?.items ?? []).map(asRecord);
    const rows: Array<{ id: string; title: string; day: string | null; platform: string; status: string }> = [];
    for (const p of projects) {
      rows.push({
        id: p.id,
        title: p.title,
        day: parseDay(p.updated_at || p.created_at),
        platform: p.platforms?.[0] || "—",
        status: p.stage,
      });
    }
    for (const q of queue) {
      rows.push({
        id: String(q.id || q.job_id || rows.length),
        title: String(q.title || q.project_title || "Publish job"),
        day: parseDay(q.scheduled_at || q.created_at),
        platform: String((Array.isArray(q.platforms) ? q.platforms[0] : q.platform) || "—"),
        status: String(q.status || q.stage || "queued"),
      });
    }
    return rows;
  }, [live.projects, live.overview, live.jobs]);

  const cells = useMemo(() => {
    const first = new Date(year, month, 1);
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const startOffset = (first.getDay() + 6) % 7;
    const out: Array<number | null> = [];
    for (let i = 0; i < startOffset; i += 1) out.push(null);
    for (let d = 1; d <= daysInMonth; d += 1) out.push(d);
    while (out.length % 7 !== 0) out.push(null);
    return out;
  }, [year, month]);

  const byDay = useMemo(() => {
    const map = new Map<number, typeof entries>();
    const prefix = `${year}-${String(month + 1).padStart(2, "0")}-`;
    for (const e of entries) {
      if (!e.day || !e.day.startsWith(prefix)) continue;
      const day = Number(e.day.slice(8, 10));
      if (!map.has(day)) map.set(day, []);
      map.get(day)!.push(e);
    }
    return map;
  }, [entries, year, month]);

  const upcoming = useMemo(
    () =>
      entries
        .filter((e) => e.day)
        .sort((a, b) => String(a.day).localeCompare(String(b.day)))
        .slice(0, 12),
    [entries],
  );

  const body = (
    <div className="mc-page mcal-page" data-live="media-calendar">
      <MediaWelcome
        title="Calendar"
        subtitle="Planning uit live projecten en publish jobs — geen demo-afspraken."
        quote="Plan only what the pipeline can ship."
      />

      {live.error ? (
        <div className="mc-panel" role="alert" style={{ marginBottom: 12 }}>
          <strong>Calendar laden mislukt.</strong> {live.error}
        </div>
      ) : null}

      <div className="mc-kpi-row">
        <article className="mc-kpi">
          <span className="mc-kpi-ico cyan">
            <FbIcon name="calendar" size={15} />
          </span>
          <div className="mc-kpi-body">
            <div className="mc-kpi-label">Entries</div>
            <div className="mc-kpi-value">{live.loading ? "…" : String(entries.length)}</div>
            <div className="mc-kpi-hint">Projects + queue</div>
          </div>
        </article>
        <article className="mc-kpi">
          <span className="mc-kpi-ico blue">
            <FbIcon name="list" size={15} />
          </span>
          <div className="mc-kpi-body">
            <div className="mc-kpi-label">Deze maand</div>
            <div className="mc-kpi-value">{String([...byDay.values()].reduce((n, a) => n + a.length, 0))}</div>
            <div className="mc-kpi-hint">
              {MONTH_NAMES[month]} {year}
            </div>
          </div>
        </article>
        <article className="mc-kpi">
          <span className="mc-kpi-ico gold">
            <FbIcon name="bolt" size={15} />
          </span>
          <div className="mc-kpi-body">
            <div className="mc-kpi-label">Ready to publish</div>
            <div className="mc-kpi-value">{String(live.overview?.ready_to_publish ?? 0)}</div>
            <div className="mc-kpi-hint">Overview</div>
          </div>
        </article>
      </div>

      <div className="mc-mid-grid">
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                {MONTH_NAMES[month]} {year}
              </h2>
              <p>Maandoverzicht</p>
            </div>
            <div className="mc-tabs">
              <button
                type="button"
                className="mc-tab"
                onClick={() => {
                  const d = new Date(year, month - 1, 1);
                  setYear(d.getFullYear());
                  setMonth(d.getMonth());
                }}
              >
                ←
              </button>
              <button
                type="button"
                className="mc-tab"
                onClick={() => {
                  const d = new Date(year, month + 1, 1);
                  setYear(d.getFullYear());
                  setMonth(d.getMonth());
                }}
              >
                →
              </button>
              <button type="button" className="mc-link-btn" onClick={() => void live.refresh()}>
                Vernieuwen
              </button>
            </div>
          </div>
          <div className="mcal-grid" style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6, padding: 12 }}>
            {["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"].map((d) => (
              <div key={d} style={{ textAlign: "center", opacity: 0.6, fontSize: 11 }}>
                {d}
              </div>
            ))}
            {cells.map((day, index) => {
              const dayEntries = day != null ? byDay.get(day) || [] : [];
              return (
                <div
                  key={index}
                  className="mcal-cell"
                  style={{
                    minHeight: 64,
                    border: "1px solid rgba(90,140,180,0.18)",
                    borderRadius: 6,
                    padding: 6,
                    opacity: day == null ? 0.25 : 1,
                  }}
                >
                  {day != null ? <strong style={{ fontSize: 12 }}>{day}</strong> : null}
                  {dayEntries.slice(0, 2).map((e) => (
                    <div key={e.id} style={{ fontSize: 10, marginTop: 4, opacity: 0.85 }}>
                      {e.title}
                    </div>
                  ))}
                  {dayEntries.length > 2 ? (
                    <div style={{ fontSize: 10, opacity: 0.55 }}>+{dayEntries.length - 2}</div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>

        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Aankomend / recent</h2>
              <p>Gesorteerd op datum</p>
            </div>
            <button type="button" className="mc-link-btn" data-fb-page="media-queue">
              Wachtrij
            </button>
          </div>
          {!upcoming.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Laden…" : "Nog geen geplande of gedateerde media-items."}
            </p>
          ) : (
            <div className="mc-queue-list">
              {upcoming.map((e) => (
                <div key={e.id} className="mc-queue-row">
                  <div className="mc-queue-copy">
                    <strong>{e.title}</strong>
                    <small>
                      {e.day || "geen datum"} · {e.platform}
                    </small>
                  </div>
                  <span className="mc-pill blue">{e.status}</span>
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
      <p className="mc-insp-quote">“Plan only what the pipeline can ship.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Calendar Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">projects · publish queue</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Entries</span>
            <span className="v">{entries.length}</span>
          </div>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="media-calendar"
      appClassName="mc-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
