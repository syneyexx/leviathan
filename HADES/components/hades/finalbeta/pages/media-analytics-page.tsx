/** FINALBETA Media Analytics — live /media/analytics (honest empty when unset). */
"use client";

import { useMemo, useState } from "react";
import { useHadesMedia } from "@/components/hades/features/media/hooks/useHadesMedia";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function MediaAnalyticsPage({ onNavigate }: Props) {
  const live = useHadesMedia();
  const [platform, setPlatform] = useState("all");
  const items = useMemo(() => (live.analytics?.items ?? []).map(asRecord), [live.analytics]);
  const platforms = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      const p = String(item.platform || "").toLowerCase();
      if (p) set.add(p);
    }
    for (const key of Object.keys(live.overview?.platforms || {})) set.add(key.toLowerCase());
    return Array.from(set).sort();
  }, [items, live.overview]);

  const filtered = useMemo(() => {
    if (platform === "all") return items;
    return items.filter((item) => String(item.platform || "").toLowerCase() === platform);
  }, [items, platform]);

  const kpis = [
    {
      id: "rows",
      label: "Analytics rows",
      value: live.loading && !items.length ? "…" : String(items.length),
      hint: "Live /media/analytics",
      tone: "cyan" as const,
      icon: "chart" as const,
    },
    {
      id: "platforms",
      label: "Platforms",
      value: String(platforms.length),
      hint: platforms.slice(0, 3).join(", ") || "geen",
      tone: "blue" as const,
      icon: "globe" as const,
    },
    {
      id: "published",
      label: "Gepubliceerd vandaag",
      value: String(live.overview?.published_today ?? 0),
      hint: "Overview counter",
      tone: "green" as const,
      icon: "checkcircle" as const,
    },
    {
      id: "failures",
      label: "Failures",
      value: String(live.overview?.failures ?? 0),
      hint: "Recente fouten",
      tone: "gold" as const,
      icon: "flask" as const,
    },
  ];

  const body = (
    <div className="mc-page ma-page" data-live="media-analytics">
      <MediaWelcome
        title="Analytics"
        subtitle="Live post-/platform metrics. Geen fake bereik of engagement."
        quote="Measure what shipped. Ignore vanity."
      />

      {live.error ? (
        <div className="mc-panel" role="alert" style={{ marginBottom: 12 }}>
          <strong>Analytics laden mislukt.</strong> {live.error}{" "}
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

      <section className="mc-panel">
        <div className="mc-panel-head">
          <div>
            <h2>Metric inventory</h2>
            <p>Rows uit `/media/analytics`</p>
          </div>
          <div className="mc-tabs" role="tablist">
            <button
              type="button"
              className={`mc-tab${platform === "all" ? " active" : ""}`}
              onClick={() => setPlatform("all")}
            >
              Alle
            </button>
            {platforms.map((p) => (
              <button
                key={p}
                type="button"
                className={`mc-tab${platform === p ? " active" : ""}`}
                onClick={() => setPlatform(p)}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
        {!filtered.length ? (
          <p className="muted" style={{ padding: 12 }}>
            {live.loading
              ? "Analytics laden…"
              : "Nog geen analytics data. Publiceer content of koppel platform credentials — bereikcijfers worden niet verzonnen."}
          </p>
        ) : (
          <table className="mc-table">
            <thead>
              <tr>
                <th>Platform</th>
                <th>Post / project</th>
                <th>Metric</th>
                <th>Waarde</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 50).map((row, index) => (
                <tr key={String(row.id || index)}>
                  <td>{String(row.platform || "—")}</td>
                  <td>{String(row.external_post_id || row.project_id || row.title || "—")}</td>
                  <td>{String(row.metric || row.name || Object.keys(row).find((k) => k.includes("view")) || "row")}</td>
                  <td>
                    {String(
                      row.value ??
                        row.views ??
                        row.likes ??
                        row.engagement ??
                        row.count ??
                        "—",
                    )}
                  </td>
                  <td>{String(row.updated_at || row.created_at || "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="mc-panel" style={{ marginTop: 12 }}>
        <div className="mc-panel-head">
          <div>
            <h2>Platform capability</h2>
            <p>Auth / readiness (geen fake KPIs)</p>
          </div>
        </div>
        {!Object.keys(live.overview?.platforms || {}).length ? (
          <p className="muted" style={{ padding: 12 }}>
            Nog geen platform capabilities gerapporteerd.
          </p>
        ) : (
          <div className="mc-platform-row">
            {Object.entries(live.overview!.platforms).map(([id, cap]) => (
              <div key={id} className="mc-platform-stat">
                <div className="mc-platform-stat-top">
                  <span>{cap.label || id}</span>
                </div>
                <strong>{cap.status}</strong>
                {cap.detail ? <small>{cap.detail}</small> : null}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Measure what shipped. Ignore vanity.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Analytics Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">/media/analytics</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Rows</span>
            <span className="v">{items.length}</span>
          </div>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="media-analytics"
      appClassName="mc-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
