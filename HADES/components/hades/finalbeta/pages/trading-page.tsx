/** FINALBETA TradingCenter Overzicht — live paper/lab APIs (sim/paper only). */
"use client";

import { useMemo, useState } from "react";
import { useHadesTrading } from "@/components/hades/features/trading/hooks/useHadesTrading";
import { donutSegments } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import { TcFooterBanner, TcPill, TcSpark, TradingWelcome } from "../trading/trading-chrome";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

function money(n: number | null | undefined): string {
  if (typeof n !== "number" || Number.isNaN(n)) return "—";
  return n.toLocaleString("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
}

function statusTone(status: string): "green" | "gold" | "red" | "blue" | "gray" {
  const s = status.toLowerCase();
  if (s.includes("active") || s.includes("running") || s === "open" || s === "ready") return "green";
  if (s.includes("fail") || s.includes("error") || s.includes("kill")) return "red";
  if (s.includes("pause") || s.includes("draft") || s.includes("queued")) return "gold";
  if (s.includes("disabled") || s.includes("off")) return "gray";
  return "blue";
}

export function TradingPage({ onNavigate }: Props) {
  const live = useHadesTrading();
  const [busy, setBusy] = useState(false);
  const paper = live.paper;
  const wallets = paper?.wallets ?? [];
  const positions = paper?.positions ?? [];
  const openPositions = positions.filter((p) => p.status === "open");
  const events = paper?.events ?? [];
  const cash =
    wallets.find((w) => w.asset === "EUR" || w.asset === "USD" || w.asset === "USDT")?.balance ??
    wallets[0]?.balance;
  const realized = positions.reduce((n, p) => n + (p.realized_pnl || 0), 0);

  const allocation = useMemo(() => {
    const bySymbol = new Map<string, number>();
    for (const p of openPositions) {
      const notional = Math.abs((p.quantity || 0) * (p.entry_price || 0));
      bySymbol.set(p.symbol, (bySymbol.get(p.symbol) || 0) + notional);
    }
    const entries = Array.from(bySymbol.entries()).sort((a, b) => b[1] - a[1]).slice(0, 6);
    const total = entries.reduce((n, [, v]) => n + v, 0) || 1;
    const colors = ["#22d3ee", "#eab94f", "#a78bfa", "#22c55e", "#f87171", "#60a5fa"];
    if (!entries.length) {
      return [{ label: "Cash", count: 1, color: colors[0]!, pct: "100%" }];
    }
    return entries.map(([label, value], i) => ({
      label,
      count: Math.max(1, Math.round(value)),
      color: colors[i % colors.length]!,
      pct: `${Math.round((value / total) * 100)}%`,
    }));
  }, [openPositions]);

  const donut = donutSegments(allocation.map((a) => ({ label: a.label, count: a.count, color: a.color })));

  const kpis = [
    {
      id: "mode",
      label: "Modus",
      value: paper?.settings.enabled ? "Paper AAN" : "Paper UIT",
      hint: paper?.settings.kill_switch ? "Kill-switch ARMED" : "Simulatie / paper only",
      tone: paper?.settings.kill_switch ? ("warn" as const) : ("up" as const),
      spark: [20, 30, 28, 40, 35, 42, 38],
    },
    {
      id: "cash",
      label: "Cash (paper)",
      value: money(cash),
      hint: wallets[0]?.asset || "wallet",
      tone: "up" as const,
      spark: [10, 12, 11, 14, 13, 15, 16],
    },
    {
      id: "positions",
      label: "Open posities",
      value: String(openPositions.length),
      hint: `${positions.length} totaal`,
      tone: "flat" as const,
      spark: [5, 6, 4, 7, 8, 6, openPositions.length || 1],
    },
    {
      id: "pnl",
      label: "Gerealiseerd P&L",
      value: money(realized),
      hint: "Paper ledger",
      tone: realized < 0 ? ("down" as const) : ("up" as const),
      spark: [8, 9, 7, 10, 12, 11, Math.max(1, Math.abs(realized))],
    },
    {
      id: "strategies",
      label: "Strategieën",
      value: String(live.strategies.length),
      hint: `${live.runs.length} runs`,
      tone: "up" as const,
      spark: [3, 4, 4, 5, 6, 5, live.strategies.length || 1],
    },
    {
      id: "symbols",
      label: "Marktsymbolen",
      value: String(live.symbols.length),
      hint: live.lab?.mode ? `Lab: ${live.lab.mode}` : "Lokale bars",
      tone: "flat" as const,
      spark: [2, 3, 3, 4, 4, 5, live.symbols.length || 1],
    },
  ];

  async function togglePaper(enabled: boolean) {
    if (busy) return;
    setBusy(true);
    try {
      await live.setEnabled(enabled);
    } finally {
      setBusy(false);
    }
  }

  async function toggleKill(armed: boolean) {
    if (busy) return;
    setBusy(true);
    try {
      await live.setKillSwitch(armed);
    } finally {
      setBusy(false);
    }
  }

  const body = (
    <div className="tc-page tc-overview-page" data-live="trading">
      <TradingWelcome
        title={
          <>
            <FbIcon name="chart" size={22} style={{ color: "#eab94f" }} />
            TradingCenter
          </>
        }
        subtitle="Marktdata, simulatie, strategieën en portfolio-intelligentie vanuit één commandocentrum."
        quote="Markten zijn geen toeval, maar een weerspiegeling van menselijk gedrag."
      />

      <div className="tc-panel" style={{ marginBottom: 12, padding: "10px 14px" }}>
        <strong>SIMULATIE / PAPER — geen echt geld.</strong>{" "}
        Broker/live balances worden hier nooit gefaked.
      </div>

      {live.error ? (
        <div className="tc-panel" role="alert" style={{ marginBottom: 12, padding: "10px 14px" }}>
          <strong>Trading laden mislukt.</strong> {live.error}{" "}
          <button type="button" className="tc-link-btn" onClick={() => void live.refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="tc-kpi-row">
        {kpis.map((kpi) => (
          <article key={kpi.id} className="tc-kpi">
            <div className="tc-kpi-top">
              <div>
                <div className="tc-kpi-label">{kpi.label}</div>
                <div className="tc-kpi-value">{live.loading && kpi.value === "—" ? "…" : kpi.value}</div>
              </div>
            </div>
            <div className="tc-kpi-meta">
              <span className={`tc-kpi-hint ${kpi.tone}`}>{kpi.hint}</span>
              <TcSpark values={kpi.spark} tone={kpi.tone} />
            </div>
          </article>
        ))}
      </div>

      <div className="tc-overview-mid">
        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>
                <FbIcon name="globe" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#22d3ee" }} />
                Marktoverzicht
              </h2>
              <p>Lokale marktbars / symbolen</p>
            </div>
            <button type="button" className="tc-link-btn" data-fb-page="trading-marketdata">
              Marktdata
            </button>
          </div>
          {!live.symbols.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading
                ? "Symbolen laden…"
                : "Nog geen marktdata. Seed of importeer bars via Marktdata / Paper desk."}
            </p>
          ) : (
            <div className="tc-market-grid">
              {live.symbols.slice(0, 8).map((m) => (
                <div key={`${m.symbol}-${m.timeframe}`} className="tc-market-card">
                  <div className="tc-market-card-top">
                    <span className="sym">{m.symbol}</span>
                    <TcSpark values={[m.last_close * 0.9, m.last_close * 0.95, m.last_close]} tone="flat" width={56} height={18} />
                  </div>
                  <div className="price">{m.last_close?.toFixed?.(4) ?? m.last_close}</div>
                  <div className="tc-market-card-foot">
                    <span style={{ fontSize: 11 }}>
                      {m.timeframe} · {m.bars} bars
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>
                <FbIcon name="list" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#22d3ee" }} />
                Strategieën status
              </h2>
              <p>Paper / lab strategieën</p>
            </div>
            <button type="button" className="tc-link-btn" data-fb-page="trading-strategies">
              Alles bekijken
            </button>
          </div>
          {!live.strategies.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Strategieën laden…" : "Nog geen strategieën."}
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Naam</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {live.strategies.slice(0, 10).map((s) => (
                  <tr key={s.id}>
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
              <h2>
                <FbIcon name="chart" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#eab94f" }} />
                Portfolio verdeling
              </h2>
              <p>Open paper posities per symbool</p>
            </div>
          </div>
          <div className="tc-donut-body">
            <div className="tc-donut-wrap">
              <svg viewBox="0 0 42 42" className="tc-donut" aria-hidden="true">
                <circle cx="21" cy="21" r="14" fill="none" stroke="rgba(74,163,255,0.12)" strokeWidth="5" />
                {donut.map((seg, index) => (
                  <circle
                    key={allocation[index]!.label}
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
              <div className="tc-donut-center">
                <strong>{money(cash)}</strong>
                <span>Paper cash</span>
              </div>
            </div>
            <ul className="tc-donut-legend">
              {allocation.map((slice) => (
                <li key={slice.label}>
                  <i style={{ background: slice.color }} />
                  <span>{slice.label}</span>
                  <b>{slice.pct}</b>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>

      <div className="tc-overview-bottom">
        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>
                <FbIcon name="bolt" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#22d3ee" }} />
                Recente paper events
              </h2>
              <p>Ledger / runtime events</p>
            </div>
          </div>
          {!events.length ? (
            <p className="muted" style={{ padding: 12 }}>
              Nog geen paper events.
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Tijd</th>
                  <th>Niveau</th>
                  <th>Bericht</th>
                </tr>
              </thead>
              <tbody>
                {events.slice(0, 10).map((row) => (
                  <tr key={row.id}>
                    <td>{row.created_at}</td>
                    <td>
                      <TcPill tone={statusTone(row.level)}>{row.level}</TcPill>
                    </td>
                    <td>{row.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>
                <FbIcon name="line" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#22d3ee" }} />
                Runs
              </h2>
              <p>Discover / backtest / paper_bot</p>
            </div>
            <button type="button" className="tc-link-btn" data-fb-page="trading-simulation">
              Simulatie
            </button>
          </div>
          {!live.runs.length ? (
            <p className="muted" style={{ padding: 12 }}>
              Nog geen trading runs.
            </p>
          ) : (
            <table className="tc-table">
              <thead>
                <tr>
                  <th>Kind</th>
                  <th>Symbool</th>
                  <th>Status</th>
                  <th>Progress</th>
                </tr>
              </thead>
              <tbody>
                {live.runs.slice(0, 8).map((run) => (
                  <tr key={run.id}>
                    <td>{run.kind}</td>
                    <td>{run.symbol}</td>
                    <td>
                      <TcPill tone={statusTone(run.status)}>{run.status}</TcPill>
                    </td>
                    <td>{Math.round(run.progress || 0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="mc-panel tc-panel">
          <div className="tc-panel-head">
            <div>
              <h2>
                <FbIcon name="shield" size={14} style={{ marginRight: 6, verticalAlign: -2, color: "#f0b429" }} />
                Risico / controls
              </h2>
              <p>Paper enable + kill-switch</p>
            </div>
          </div>
          <div className="tc-risk-grid">
            <div className="tc-risk-card">
              <div className="label">Paper trading</div>
              <div className="value">{paper?.settings.enabled ? "AAN" : "UIT"}</div>
              <div className="hint">
                <button
                  type="button"
                  className="tc-link-btn"
                  disabled={busy}
                  onClick={() => void togglePaper(!paper?.settings.enabled)}
                >
                  {paper?.settings.enabled ? "Uitschakelen" : "Inschakelen"}
                </button>
              </div>
            </div>
            <div className="tc-risk-card">
              <div className="label">Kill-switch</div>
              <div className="value">{paper?.settings.kill_switch ? "ARMED" : "clear"}</div>
              <div className={`hint ${paper?.settings.kill_switch ? "warn" : ""}`}>
                <button
                  type="button"
                  className="tc-link-btn"
                  disabled={busy}
                  onClick={() => void toggleKill(!paper?.settings.kill_switch)}
                >
                  {paper?.settings.kill_switch ? "Clear" : "Arm"}
                </button>
              </div>
            </div>
            <div className="tc-risk-card">
              <div className="label">Lab mode</div>
              <div className="value">{live.lab?.mode || "—"}</div>
              <div className="hint">{live.lab?.warnings?.length ? `${live.lab.warnings.length} warnings` : "ok"}</div>
            </div>
            <div className="tc-risk-card">
              <div className="label">Open exposure</div>
              <div className="value">{openPositions.length}</div>
              <div className="hint">posities</div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“Paper first. Never fake live balances.”</p>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Trading Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">/trading/dashboard · /trading/lab/overview</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Status</span>
            <span className={`v ${live.error ? "gold" : "green"}`}>
              {live.loading ? "Laden…" : live.error ? "Fout" : "Live"}
            </span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Paper</span>
            <span className="v">{paper?.settings.enabled ? "enabled" : "disabled"}</span>
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
          <button type="button" className="stats-quick-btn" data-fb-page="trading-paper">
            <FbIcon name="file" size={16} />
            <span>Paper</span>
          </button>
          <button type="button" className="stats-quick-btn" data-fb-page="trading-strategies">
            <FbIcon name="list" size={16} />
            <span>Strategieën</span>
          </button>
          <button type="button" className="stats-quick-btn" data-fb-page="trading-portfolio">
            <FbIcon name="database" size={16} />
            <span>Portefeuille</span>
          </button>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="trading"
      appClassName="tc-app"
      mainClassName="tc-main"
      body={body}
      inspector={inspector}
      footer={<TcFooterBanner left="TradingCenter · paper/sim" right="Geen live broker balances" />}
      onNavigate={onNavigate}
    />
  );
}
