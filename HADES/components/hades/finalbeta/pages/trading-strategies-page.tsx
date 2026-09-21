/** FINALBETA TradingCenter Strategieën — live paper/lab strategy catalog. */
"use client";

import { useEffect, useMemo, useState } from "react";
import { useHadesTrading } from "@/components/hades/features/trading/hooks/useHadesTrading";
import type { TradingStrategy } from "@/lib/hades-api";
import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import { TcFooterBanner, TcPill, TcSpark, TradingWelcome } from "../trading/trading-chrome";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function statusTone(status: string): "green" | "gold" | "red" | "blue" | "gray" {
  const s = status.toLowerCase();
  if (s.includes("active") || s.includes("ready") || s.includes("promoted")) return "green";
  if (s.includes("fail") || s.includes("error")) return "red";
  if (s.includes("draft") || s.includes("pause")) return "gold";
  if (s.includes("disabled")) return "gray";
  return "blue";
}

export function TradingStrategiesPage({ onNavigate }: Props) {
  const live = useHadesTrading();
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return live.strategies.filter((s) => {
      if (!q) return true;
      return (
        s.name.toLowerCase().includes(q) ||
        s.kind.toLowerCase().includes(q) ||
        s.id.toLowerCase().includes(q) ||
        String(s.status).toLowerCase().includes(q)
      );
    });
  }, [live.strategies, query]);

  useEffect(() => {
    if (!filtered.length) {
      setSelectedId("");
      return;
    }
    setSelectedId((cur) => (cur && filtered.some((s) => s.id === cur) ? cur : filtered[0]!.id));
  }, [filtered]);

  const selected: TradingStrategy | null = filtered.find((s) => s.id === selectedId) || null;

  const kpis = [
    {
      id: "total",
      label: "Strategieën",
      value: live.loading ? "…" : String(live.strategies.length),
      hint: `${filtered.length} gefilterd`,
      tone: "up" as const,
      spark: [2, 3, 3, 4, 5, 4, live.strategies.length || 1],
    },
    {
      id: "kinds",
      label: "Kinds",
      value: String(new Set(live.strategies.map((s) => s.kind)).size),
      hint: (live.dashboard?.strategy_kinds || []).slice(0, 3).join(", ") || "—",
      tone: "flat" as const,
      spark: [1, 2, 2, 3, 3, 4, 3],
    },
    {
      id: "runs",
      label: "Runs",
      value: String(live.runs.length),
      hint: "discover / backtest / paper_bot",
      tone: "up" as const,
      spark: [1, 1, 2, 2, 3, 3, live.runs.length || 1],
    },
    {
      id: "lab",
      label: "Lab mode",
      value: live.lab?.mode || "—",
      hint: live.lab?.warnings?.length ? `${live.lab.warnings.length} warnings` : "ok",
      tone: "warn" as const,
      spark: [3, 3, 4, 4, 5, 4, 5],
    },
  ];

  const body = (
    <div className="tc-page tc-strat-page" data-live="trading-strategies">
      <TradingWelcome
        title={
          <>
            <FbIcon name="list" size={22} style={{ color: "#eab94f" }} />
            Strategieën
          </>
        }
        subtitle="Ontwerp, beheer en analyseer tradingstrategieën (paper / lab)."
        quote="Een goede strategie maakt onzekerheid handelbaar."
      />

      <div className="tc-panel" style={{ marginBottom: 12, padding: "10px 14px" }}>
        <strong>SIMULATIE / PAPER.</strong> Scores en metrics komen uit lokale runs — geen live broker claims.
      </div>

      {live.error ? (
        <div className="tc-panel" role="alert" style={{ marginBottom: 12, padding: "10px 14px" }}>
          <strong>Strategieën laden mislukt.</strong> {live.error}{" "}
          <button type="button" className="tc-link-btn" onClick={() => void live.refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="tc-kpi-row">
        {kpis.map((kpi) => (
          <article key={kpi.id} className="tc-kpi">
            <div className="tc-kpi-label">{kpi.label}</div>
            <div className="tc-kpi-value">{kpi.value}</div>
            <div className="tc-kpi-meta">
              <span className={`tc-kpi-hint ${kpi.tone}`}>{kpi.hint}</span>
              <TcSpark values={kpi.spark} tone={kpi.tone === "warn" ? "warn" : kpi.tone} />
            </div>
          </article>
        ))}
      </div>

      <div className="tc-strat-mid">
        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>Strategie catalogus</h2>
              <p>Live `/trading/dashboard` strategies</p>
            </div>
            <button type="button" className="tc-link-btn" onClick={() => void live.refresh()}>
              Vernieuwen
            </button>
          </div>
          <div className="tc-strat-filters">
            <input
              type="search"
              placeholder="Zoek strategie…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Zoek strategie"
            />
          </div>
          {!filtered.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Strategieën laden…" : "Nog geen strategieën. Discover/backtest via Trading Lab."}
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Naam</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((s) => (
                  <tr
                    key={s.id}
                    className={selected?.id === s.id ? "active" : undefined}
                    style={{ cursor: "pointer" }}
                    onClick={() => setSelectedId(s.id)}
                  >
                    <td>
                      <strong>{s.name}</strong>
                    </td>
                    <td>{s.kind}</td>
                    <td>
                      <TcPill tone={statusTone(s.status)}>{s.status}</TcPill>
                    </td>
                    <td>{typeof s.score === "number" ? s.score.toFixed(2) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>{selected?.name || "Selecteer een strategie"}</h2>
              <p>{selected ? selected.id : "Details verschijnen hier"}</p>
            </div>
            {selected ? <TcPill tone={statusTone(selected.status)}>{selected.status}</TcPill> : null}
          </div>
          {!selected ? (
            <p className="muted" style={{ padding: 12 }}>
              Kies een strategie uit de catalogus.
            </p>
          ) : (
            <div className="tc-account-grid">
              <div>
                {[
                  ["Kind", selected.kind],
                  ["Score", typeof selected.score === "number" ? selected.score.toFixed(3) : "—"],
                  ["Updated", selected.updated_at || selected.created_at || "—"],
                  ["Knowledge", selected.knowledge_source_id || "—"],
                ].map(([k, v]) => (
                  <div key={k} className="tc-detail-row">
                    <span className="k">{k}</span>
                    <span className="v">{v}</span>
                  </div>
                ))}
              </div>
              <div>
                <div className="tc-detail-row">
                  <span className="k">Notes</span>
                  <span className="v">{selected.notes || "Geen notities"}</span>
                </div>
                <div className="tc-detail-row">
                  <span className="k">Params</span>
                  <span className="v">
                    {Object.keys(selected.params || {}).length
                      ? JSON.stringify(selected.params)
                      : "geen params"}
                  </span>
                </div>
                <div className="tc-detail-row">
                  <span className="k">Metrics</span>
                  <span className="v">
                    {Object.keys(selected.metrics || {}).length
                      ? JSON.stringify(selected.metrics)
                      : "nog geen metrics"}
                  </span>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>

      <section className="tc-panel">
        <div className="tc-panel-head">
          <div>
            <h2>Gerelateerde runs</h2>
            <p>Filter op geselecteerde strategie waar mogelijk</p>
          </div>
          <button type="button" className="tc-link-btn" data-fb-page="trading-simulation">
            Simulatie
          </button>
        </div>
        {!live.runs.length ? (
          <p className="muted" style={{ padding: 12 }}>
            Nog geen runs.
          </p>
        ) : (
          <table className="tc-table">
            <thead>
              <tr>
                <th>Kind</th>
                <th>Symbool</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Strategy</th>
              </tr>
            </thead>
            <tbody>
              {live.runs
                .filter((r) => !selected || !r.strategy_id || r.strategy_id === selected.id)
                .slice(0, 12)
                .map((run) => (
                  <tr key={run.id}>
                    <td>{run.kind}</td>
                    <td>{run.symbol}</td>
                    <td>
                      <TcPill tone={statusTone(run.status)}>{run.status}</TcPill>
                    </td>
                    <td>{Math.round(run.progress || 0)}%</td>
                    <td>{run.strategy_id || "—"}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Een goede strategie maakt onzekerheid handelbaar.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Strategy Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">trading dashboard strategies</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Selected</span>
            <span className="v">{selected?.name || "—"}</span>
          </div>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="trading-strategies"
      appClassName="tc-app"
      mainClassName="tc-main"
      body={body}
      inspector={inspector}
      footer={<TcFooterBanner left="Strategieën · paper/lab" right="Geen live broker" />}
      onNavigate={onNavigate}
    />
  );
}
