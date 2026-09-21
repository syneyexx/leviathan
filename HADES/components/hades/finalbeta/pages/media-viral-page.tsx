/** FINALBETA Media Viral radar — live /media/trends + opportunities. */
"use client";

import { useMemo, useState } from "react";
import { useHadesMedia } from "@/components/hades/features/media/hooks/useHadesMedia";
import { hadesApi } from "@/lib/hades-api";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function MediaViralPage({ onNavigate }: Props) {
  const live = useHadesMedia();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const trends = useMemo(() => {
    const fromOverview = live.overview?.trending_opportunities ?? [];
    const fromTrends = live.trends?.items ?? [];
    const merged = [...fromTrends, ...fromOverview];
    const seen = new Set<string>();
    const out: Array<Record<string, unknown>> = [];
    for (const raw of merged) {
      const item = asRecord(raw);
      const id = String(item.id || item.topic || item.title || `${out.length}`);
      if (seen.has(id)) continue;
      seen.add(id);
      out.push({ ...item, id });
    }
    return out;
  }, [live.overview, live.trends]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return trends;
    return trends.filter((t) =>
      `${t.title || ""} ${t.topic || ""} ${t.platform || ""} ${t.summary || ""}`.toLowerCase().includes(q),
    );
  }, [trends, query]);

  const kpis = [
    {
      id: "signals",
      label: "Trend signalen",
      value: live.loading && !trends.length ? "…" : String(live.overview?.trend_signals ?? trends.length),
      hint: "Live radar",
      icon: "target" as const,
      tone: "cyan" as const,
    },
    {
      id: "opps",
      label: "Opportunities",
      value: String(live.overview?.opportunities ?? trends.length),
      hint: "Backend counter",
      icon: "bolt" as const,
      tone: "gold" as const,
    },
    {
      id: "channels",
      label: "Kanalen",
      value: String(live.overview?.channels ?? live.channels?.items?.length ?? 0),
      hint: "Configured",
      icon: "users" as const,
      tone: "blue" as const,
    },
    {
      id: "engine",
      label: "Engine",
      value: live.overview?.engine_status || "—",
      hint: "Media engine",
      icon: "flask" as const,
      tone: "green" as const,
    },
  ];

  async function discover() {
    if (busy) return;
    setBusy(true);
    setNote(null);
    try {
      const result = await hadesApi.discoverMediaTrends(query.trim() ? { query: query.trim() } : undefined);
      setNote(typeof result === "object" ? `Discover gestart/voltooid` : "Discover klaar");
      await live.refresh();
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const body = (
    <div className="mc-page mv-page" data-live="media-viral">
      <MediaWelcome
        title="Viral radar"
        subtitle="Live trend signalen en opportunities — geen fake momentumcijfers."
        quote="Catch the wave early. Prove it with data."
        right={
          <div className="pr-welcome-actions">
            <button className="btn btn-outline" type="button" disabled={busy} onClick={() => void live.refresh()}>
              <FbIcon name="bolt" size={13} />
              Vernieuwen
            </button>
            <button className="btn btn-gold" type="button" disabled={busy} onClick={() => void discover()}>
              <FbIcon name="target" size={13} />
              Discover
            </button>
          </div>
        }
      />

      {live.error ? (
        <div className="mc-panel" role="alert" style={{ marginBottom: 12 }}>
          <strong>Viral radar laden mislukt.</strong> {live.error}
        </div>
      ) : null}
      {note ? (
        <div className="mc-panel" style={{ marginBottom: 12, padding: "10px 14px" }}>
          {note}
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

      <section className="mc-panel">
        <div className="mc-panel-head">
          <div>
            <h2>Trend signalen</h2>
            <p>{filtered.length} live items</p>
          </div>
          <label className="prw-search">
            <FbIcon name="search" size={12} />
            <input
              type="search"
              placeholder="Filter of discover query…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
        </div>
        {!filtered.length ? (
          <p className="muted" style={{ padding: 12 }}>
            {live.loading
              ? "Trends laden…"
              : "Nog geen trend signalen. Start Discover of wacht tot de radar data heeft."}
          </p>
        ) : (
          <div className="mc-trend-list">
            {filtered.slice(0, 40).map((t, index) => (
              <div key={String(t.id)} className="mc-trend-row">
                <span className="mc-rank">{index + 1}</span>
                <div className="mc-trend-copy">
                  <strong>{String(t.title || t.topic || t.query || `Signal ${index + 1}`)}</strong>
                  <small>{String(t.summary || t.hint || t.platform || t.source || "—")}</small>
                </div>
                <div className="mc-trend-right">
                  <span className="growth">{String(t.score ?? t.growth ?? t.momentum ?? "—")}</span>
                  <span className="mc-pill blue">{String(t.status || t.badge || "SIGNAL")}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Catch the wave early. Prove it with data.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Viral Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">/media/trends · overview opportunities</span>
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
      page="media-viral"
      appClassName="mc-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
