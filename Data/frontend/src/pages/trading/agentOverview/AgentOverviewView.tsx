/**
 * Agent Overzicht — SCREEN 1 composition.
 * KPI strip → Agent Registry + detail → bottom four panels.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { UNMEASURED, fmtUsd } from "../workspaces/commandHub/hubFormat";
import type { AgentOverviewData, AoDetailTab, AoFilter, AoKpi } from "./useAgentOverviewData";

function Sparkline({ values, kind, tone }: { values: number[]; kind: "line" | "bars"; tone: string }) {
  if (!values.length) return <div className="lv-hub-spark lv-hub-spark--empty" aria-hidden="true" />;
  const w = 96;
  const h = 28;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  if (kind === "bars") {
    const bw = w / values.length;
    return (
      <svg className={`lv-hub-spark lv-hub-spark--tone-${tone}`} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
        {values.map((v, i) => {
          const bh = Math.max(2, ((v - min) / span) * (h - 4) + 4);
          return <rect key={i} x={i * bw + 1} y={h - bh} width={Math.max(1, bw - 2)} height={bh} rx={1} />;
        })}
      </svg>
    );
  }
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1 || 1)) * w;
      const y = h - ((v - min) / span) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className={`lv-hub-spark lv-hub-spark--tone-${tone}`} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={pts} fill="none" strokeWidth={1.6} />
    </svg>
  );
}

function KpiCard({ kpi }: { kpi: AoKpi }) {
  return (
    <article className={`lv-hub-kpi lv-hub-kpi--tone-${kpi.tone}`}>
      <p className="lv-hub-kpi__label">{kpi.label}</p>
      <p className="lv-hub-kpi__value">{kpi.value}</p>
      <div className="lv-hub-kpi__foot">
        <span className={`lv-hub-kpi__delta lv-hub-tone-${kpi.deltaTone}`}>{kpi.delta}</span>
        <Sparkline values={kpi.spark} kind={kpi.sparkKind} tone={kpi.tone} />
      </div>
    </article>
  );
}

const FILTERS: { id: AoFilter; label: string }[] = [
  { id: "all", label: "Alle Agents" },
  { id: "active", label: "Actief" },
  { id: "paused", label: "Pauze" },
  { id: "simulation", label: "Simulatie" },
];

const TABS: { id: AoDetailTab; label: string }[] = [
  { id: "overzicht", label: "Overzicht" },
  { id: "wallet", label: "Wallet" },
  { id: "sessies", label: "Sessies" },
  { id: "architectuur", label: "Architectuur" },
];

export function AgentOverviewView({
  data,
  onOpenPortfolio,
  onOpenControlRoom,
  onOpenOrchestra,
}: {
  data: AgentOverviewData;
  onOpenPortfolio: () => void;
  onOpenControlRoom: () => void;
  onOpenOrchestra: () => void;
}) {
  const [fundDelta, setFundDelta] = useState("10000");
  const [fundReason, setFundReason] = useState("Operator paper capital adjustment");
  const sel = data.selected;

  return (
    <section className="lv-ao" aria-label="Agent Overzicht" aria-busy={data.loading}>
      <div className="lv-ao__truth">
        <span className="lv-tc-badge lv-tc-badge--exec">PAPER MONEY</span>
        <span className="lv-tc-badge">LIVE DATA ≠ LIVE MONEY</span>
        <span className={`lv-hub-pill lv-hub-tone-${data.liveTrading === "BLOCKED" ? "red" : "gold"}`}>
          Live trading: {data.liveTrading}
        </span>
        {data.stale ? <span className="lv-hub-pill lv-hub-tone-gold">STALE</span> : null}
      </div>

      {data.error ? (
        <p className="lv-hub-error" role="alert">
          {data.error}
          <button type="button" className="lv-hub-btn" onClick={() => void data.refresh()}>
            Retry
          </button>
        </p>
      ) : null}

      <div className="lv-hub-kpis lv-ao-kpis">
        {data.kpis.map((k) => (
          <KpiCard key={k.id} kpi={k} />
        ))}
      </div>

      <div className="lv-ao-main">
        <section className="lv-ao-registry" aria-label="Agent Registry">
          <header className="lv-ao-panel__head">
            <h3>Agent Registry</h3>
            <div className="lv-ao-registry__actions">
              <input
                className="lv-ao-search"
                placeholder="Zoek agent…"
                value={data.search}
                onChange={(e) => data.setSearch(e.target.value)}
              />
              <button type="button" className="lv-hub-btn" onClick={onOpenOrchestra}>
                Orchestra
              </button>
              <button type="button" className="lv-hub-btn" onClick={onOpenControlRoom}>
                Control Room
              </button>
            </div>
          </header>
          <div className="lv-ao-tabs" role="tablist">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                role="tab"
                aria-selected={data.filter === f.id}
                className={`lv-ao-tab${data.filter === f.id ? " is-active" : ""}`}
                onClick={() => data.setFilter(f.id)}
              >
                {f.label} ({data.filterCounts[f.id]})
              </button>
            ))}
          </div>
          <div className="lv-ao-table-scroll">
            <table className="lv-hub-table lv-ao-table">
              <thead>
                <tr>
                  <th />
                  <th>Agent</th>
                  <th>Rol</th>
                  <th>Wallet</th>
                  <th>PnL vandaag</th>
                  <th>Exposure</th>
                  <th>Laatste trade</th>
                  <th>Status</th>
                  <th>Acties</th>
                </tr>
              </thead>
              <tbody>
                {data.agents.map((a) => (
                  <tr
                    key={a.id}
                    className={sel?.id === a.id ? "is-selected" : undefined}
                    onClick={() => data.setSelectedId(a.id)}
                  >
                    <td>
                      <input
                        type="checkbox"
                        checked={sel?.id === a.id}
                        onChange={() => data.setSelectedId(a.id)}
                        aria-label={`Select ${a.name}`}
                      />
                    </td>
                    <td>
                      <strong>{a.name}</strong>
                      <div className="lv-ao-muted">{a.orchestraName}</div>
                    </td>
                    <td>{a.role}</td>
                    <td>{a.walletCash != null ? fmtUsd(a.walletCash) : UNMEASURED}</td>
                    <td className={a.pnlToday != null && a.pnlToday >= 0 ? "lv-hub-tone-green" : "lv-hub-tone-red"}>
                      {a.pnlToday != null ? fmtUsd(a.pnlToday) : UNMEASURED}
                    </td>
                    <td>{a.exposurePct != null ? `${a.exposurePct.toFixed(1)}%` : UNMEASURED}</td>
                    <td>{a.lastTrade}</td>
                    <td>
                      <span className={`lv-hub-pill lv-hub-tone-${a.statusTone}`}>{a.status}</span>
                    </td>
                    <td>
                      <Link className="lv-hub-btn" to={`/trading/live-agents?agent=${encodeURIComponent(a.id)}`}>
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
                {!data.agents.length ? (
                  <tr>
                    <td colSpan={9} className="lv-hub-empty-cell">
                      Geen trading agents gevonden.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="lv-ao-detail" aria-label="Selected agent">
          <header className="lv-ao-panel__head">
            <div>
              <h3>{sel?.name ?? "Geen agent geselecteerd"}</h3>
              <p className="lv-ao-muted">
                {sel ? `${sel.role} · ${sel.orchestraName} · PAPER` : "Selecteer een agent in de registry."}
              </p>
            </div>
            {sel ? <span className={`lv-hub-pill lv-hub-tone-${sel.statusTone}`}>{sel.status}</span> : null}
          </header>
          <div className="lv-ao-tabs" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                disabled={!sel}
                aria-selected={data.detailTab === t.id}
                className={`lv-ao-tab${data.detailTab === t.id ? " is-active" : ""}`}
                onClick={() => data.setDetailTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>

          {!sel ? (
            <p className="lv-ao-empty">Geen selectie.</p>
          ) : data.detailTab === "overzicht" ? (
            <div className="lv-ao-detail__grid">
              <div>
                <span>Orchestra</span>
                <strong>{sel.orchestraName}</strong>
              </div>
              <div>
                <span>Strategie</span>
                <strong>{sel.strategy}</strong>
              </div>
              <div>
                <span>Wallet</span>
                <strong>{sel.walletCash != null ? fmtUsd(sel.walletCash) : UNMEASURED}</strong>
              </div>
              <div>
                <span>Realized PnL</span>
                <strong>{sel.pnlToday != null ? fmtUsd(sel.pnlToday) : UNMEASURED}</strong>
              </div>
              <div>
                <span>Exposure</span>
                <strong>{sel.exposurePct != null ? `${sel.exposurePct.toFixed(1)}%` : UNMEASURED}</strong>
              </div>
              <div>
                <span>Mode</span>
                <strong>PAPER EXECUTION</strong>
              </div>
              <div className="lv-ao-detail__actions">
                <button type="button" className="lv-hub-btn" onClick={onOpenPortfolio}>
                  Portfolio advanced
                </button>
                <Link className="lv-hub-btn lv-hub-btn--primary" to={`/trading/live-agents?agent=${encodeURIComponent(sel.id)}`}>
                  Agent openen
                </Link>
              </div>
            </div>
          ) : data.detailTab === "wallet" ? (
            <div className="lv-ao-wallet">
              <p className="lv-ao-muted">
                Paper capital mutaties via WalletLedger/PortfolioBook. Funding wijzigt <strong>niet</strong> trading PnL.
              </p>
              <div className="lv-ao-detail__grid">
                <div>
                  <span>Wallet</span>
                  <strong>{sel.walletLabel}</strong>
                </div>
                <div>
                  <span>Cash / equity</span>
                  <strong>{sel.walletCash != null ? fmtUsd(sel.walletCash) : UNMEASURED}</strong>
                </div>
                <div>
                  <span>Realized PnL</span>
                  <strong>
                    {data.selectedPortfolio
                      ? fmtUsd(Number(data.selectedPortfolio.realized_pnl))
                      : UNMEASURED}
                  </strong>
                </div>
              </div>
              {sel.walletId ? (
                <form
                  className="lv-ao-fund"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const delta = Number(fundDelta);
                    if (!Number.isFinite(delta) || delta === 0) return;
                    void data.fundSelectedWallet(delta, fundReason.trim() || "Operator paper capital adjustment");
                  }}
                >
                  <label>
                    Delta (paper USD)
                    <input value={fundDelta} onChange={(e) => setFundDelta(e.target.value)} />
                  </label>
                  <label>
                    Reden
                    <input value={fundReason} onChange={(e) => setFundReason(e.target.value)} />
                  </label>
                  <button type="submit" className="lv-hub-btn lv-hub-btn--primary" disabled={data.fundingBusy}>
                    {data.fundingBusy ? "Bezig…" : "Wallet aanpassen"}
                  </button>
                </form>
              ) : (
                <p className="lv-ao-empty">
                  Geen portfolio-wallet gekoppeld. Maak/koppel een paper portfolio via Portfolio advanced.
                </p>
              )}
              {data.fundingNotice ? <p className="lv-ao-notice">{data.fundingNotice}</p> : null}
            </div>
          ) : data.detailTab === "sessies" ? (
            <div className="lv-ao-sessions">
              <ul className="lv-ao-list">
                {data.deployments.slice(0, 12).map((d) => (
                    <li key={d.deployment_id}>
                      <strong>{d.status}</strong> · {d.mode || "paper"} · kill={d.kill_switch ? "ON" : "off"}
                      <div className="lv-ao-muted">{d.deployment_id}</div>
                    </li>
                  ))}
                {!data.deployments.length ? <li className="lv-ao-empty">Geen paper sessies / deployments.</li> : null}
              </ul>
            </div>
          ) : (
            <div className="lv-ao-arch-mini">
              {data.architecture.map((n) => (
                <div key={n.id} className={`lv-ao-arch-node lv-hub-tone-${n.tone}`}>
                  <strong>{n.label}</strong>
                  <span>{n.count}</span>
                  <small>{n.status}</small>
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>

      <div className="lv-ao-bottom">
        <section className="lv-ao-panel" aria-label="Kapitaal Allocatie">
          <header className="lv-ao-panel__head">
            <h3>Kapitaal Allocatie</h3>
            <button type="button" className="lv-hub-btn" onClick={onOpenPortfolio}>
              Portfolio
            </button>
          </header>
          <ul className="lv-ao-alloc">
            {data.allocations.map((a) => (
              <li key={a.id}>
                <div className="lv-ao-alloc__row">
                  <span>{a.name}</span>
                  <strong>{a.equity != null ? fmtUsd(a.equity) : UNMEASURED}</strong>
                </div>
                <div className="lv-ao-alloc__bar">
                  <i style={{ width: `${Math.min(100, a.pct ?? 0)}%` }} />
                </div>
                <div className="lv-ao-muted">
                  {a.pct != null ? `${a.pct.toFixed(1)}%` : UNMEASURED} · available{" "}
                  {a.available != null ? fmtUsd(a.available) : UNMEASURED} ·{" "}
                  {a.isolated ? "isolated paper" : "shared"}
                </div>
              </li>
            ))}
            {!data.allocations.length ? <li className="lv-ao-empty">Geen paper wallets.</li> : null}
          </ul>
        </section>

        <section className="lv-ao-panel" aria-label="Agent Architectuur">
          <header className="lv-ao-panel__head">
            <h3>Agent Architectuur</h3>
          </header>
          <div className="lv-ao-arch">
            {data.architecture.map((n) => (
              <button
                key={n.id}
                type="button"
                className={`lv-ao-arch-node lv-hub-tone-${n.tone}`}
                onClick={onOpenOrchestra}
              >
                <strong>{n.label}</strong>
                <span>{n.count}</span>
                <small>{n.status}</small>
              </button>
            ))}
          </div>
        </section>

        <section className="lv-ao-panel" aria-label="Sessie Activiteit">
          <header className="lv-ao-panel__head">
            <h3>Sessie Activiteit</h3>
          </header>
          <ul className="lv-ao-list">
            {data.activity.map((a) => (
              <li key={a.id}>
                <span className="lv-ao-muted">{a.time}</span> · <strong>{a.agent}</strong> · {a.event}
                <div className="lv-ao-muted">{a.detail}</div>
              </li>
            ))}
            {!data.activity.length ? <li className="lv-ao-empty">Geen recente events.</li> : null}
          </ul>
        </section>

        <section className="lv-ao-panel" aria-label="Risico Snapshot">
          <header className="lv-ao-panel__head">
            <h3>Risico Snapshot</h3>
          </header>
          <dl className="lv-ao-risk">
            <div>
              <dt>Max drawdown</dt>
              <dd>{data.risk.maxDrawdown}</dd>
            </div>
            <div>
              <dt>VaR</dt>
              <dd>{data.risk.var}</dd>
            </div>
            <div>
              <dt>Total exposure</dt>
              <dd>{data.risk.totalExposure}</dd>
            </div>
            <div>
              <dt>Open positions</dt>
              <dd>{data.risk.openPositions}</dd>
            </div>
            <div>
              <dt>Kill switch</dt>
              <dd>{data.risk.killSwitch}</dd>
            </div>
            <div>
              <dt>RiskGuard</dt>
              <dd>{data.risk.riskGuard}</dd>
            </div>
          </dl>
        </section>
      </div>
    </section>
  );
}
