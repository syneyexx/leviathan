/**
 * Research Centrum — SCREEN 3 composition over Strategy Lab + Market Data authorities.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { UNMEASURED } from "../workspaces/commandHub/hubFormat";
import type { DiscoveryRow, StrategyLabData } from "../workspaces/strategyLab/useStrategyLabData";
import type { MarketDataWorkspaceData } from "../workspaces/marketData/useMarketDataWorkspace";

export function ResearchCenterView({
  data,
  marketData,
  selectedRow,
  onSelectRow,
  onOpenCreateRun,
  onOpenAdvanced,
  onOpenMarketData,
  onAssignToAgent,
  compareIds,
  onToggleCompare,
  onOpenCompare,
}: {
  data: StrategyLabData;
  marketData: MarketDataWorkspaceData;
  selectedRow: DiscoveryRow | null;
  onSelectRow: (row: DiscoveryRow) => void;
  onOpenCreateRun: () => void;
  onOpenAdvanced: () => void;
  onOpenMarketData: () => void;
  /** Opens DeployPaperDrawer with selected strategy — real paper deployment assignment. */
  onAssignToAgent: () => void;
  compareIds: string[];
  onToggleCompare: (id: string) => void;
  onOpenCompare: () => void;
}) {
  const [filter, setFilter] = useState<"all" | "training" | "backtest" | "sandbox" | "blocked">("all");

  const rows = useMemo(() => {
    const all = data.discovery;
    if (filter === "all") return all;
    return all.filter((r) => {
      const s = r.status.toUpperCase();
      if (filter === "training") return ["LEARNING", "DISCOVERING", "RUNNING", "TRAINING"].some((t) => s.includes(t));
      if (filter === "backtest") return ["BACKTEST", "CANDIDATE", "READY"].some((t) => s.includes(t));
      if (filter === "sandbox") return ["PAPER", "SANDBOX", "SHADOW"].some((t) => s.includes(t));
      if (filter === "blocked") return ["REJECT", "FAIL", "BLOCK", "CANCEL"].some((t) => s.includes(t));
      return true;
    });
  }, [data.discovery, filter]);

  const bestSharpe = useMemo(() => {
    const vals = data.discovery
      .map((r) => {
        const n = Number(r.sharpe);
        return Number.isFinite(n) ? n : null;
      })
      .filter((n): n is number => n != null);
    if (!vals.length) return UNMEASURED;
    return Math.max(...vals).toFixed(2);
  }, [data.discovery]);

  const activeLabs = data.labs.filter((l) =>
    /RUN|ACTIVE|LEARN/i.test(String((l as Record<string, unknown>).status || (l as Record<string, unknown>).state || "")),
  ).length;

  const kpis = [
    {
      id: "exp",
      label: "Actieve experimenten",
      value: String(activeLabs || data.labs.length),
      delta: UNMEASURED,
    },
    {
      id: "new",
      label: "Nieuwe strategieën",
      value: String(data.strategies.length),
      delta: UNMEASURED,
    },
    {
      id: "bt",
      label: "Backtests vandaag",
      value: UNMEASURED,
      delta: UNMEASURED,
    },
    {
      id: "sharpe",
      label: "Best Sharpe",
      value: bestSharpe,
      delta: UNMEASURED,
    },
    {
      id: "sandbox",
      label: "Live sandboxes",
      value: String(data.discovery.filter((r) => /PAPER|SANDBOX|SHADOW/i.test(r.status)).length),
      delta: UNMEASURED,
    },
  ];

  const pipeline = [
    { id: "idea", label: "Ideegeneratie", count: data.discovery.length || UNMEASURED },
    { id: "feat", label: "Feature engineering", count: UNMEASURED },
    { id: "syn", label: "Strategie synthese", count: data.strategies.length || UNMEASURED },
    { id: "bt", label: "Backtest", count: data.labs.length || UNMEASURED },
    { id: "val", label: "Validatie", count: UNMEASURED },
    { id: "prom", label: "Promotie", count: UNMEASURED },
  ];

  return (
    <section className="lv-rc" aria-label="Research Centrum" aria-busy={data.loading}>
      <div className="lv-ao__truth">
        <span className="lv-tc-badge lv-tc-badge--exec">PAPER / RESEARCH ONLY</span>
        <span className="lv-tc-badge">LIVE DATA sandbox ≠ LIVE MONEY</span>
      </div>

      <div className="lv-hub-kpis">
        {kpis.map((k) => (
          <article key={k.id} className="lv-hub-kpi lv-hub-kpi--tone-purple">
            <p className="lv-hub-kpi__label">{k.label}</p>
            <p className="lv-hub-kpi__value">{k.value}</p>
            <div className="lv-hub-kpi__foot">
              <span className="lv-hub-kpi__delta lv-hub-tone-muted">{k.delta}</span>
            </div>
          </article>
        ))}
      </div>

      <div className="lv-rc-main">
        <section className="lv-ao-registry" aria-label="Strategie Inventaris">
          <header className="lv-ao-panel__head">
            <h3>Strategie Inventaris</h3>
            <div className="lv-ao-registry__actions">
              <button type="button" className="lv-hub-btn lv-hub-btn--primary" onClick={onOpenCreateRun}>
                Autonome discovery
              </button>
              <button type="button" className="lv-hub-btn" onClick={onOpenAdvanced}>
                Advanced lab
              </button>
              <button
                type="button"
                className="lv-hub-btn"
                disabled={compareIds.length < 2}
                onClick={onOpenCompare}
              >
                Compare ({compareIds.length})
              </button>
            </div>
          </header>
          <div className="lv-ao-tabs">
            {(
              [
                ["all", "Alle strategieën"],
                ["training", "In training"],
                ["backtest", "Backtest klaar"],
                ["sandbox", "Live sandbox"],
                ["blocked", "Afgekeurd"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={`lv-ao-tab${filter === id ? " is-active" : ""}`}
                onClick={() => setFilter(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="lv-ao-table-scroll">
            <table className="lv-hub-table">
              <thead>
                <tr>
                  <th />
                  <th>Strategie</th>
                  <th>Regime</th>
                  <th>Markt</th>
                  <th>Sharpe</th>
                  <th>Max DD</th>
                  <th>Win rate</th>
                  <th>Status</th>
                  <th>Acties</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  return (
                    <tr
                      key={r.id}
                      className={selectedRow?.id === r.id ? "is-selected" : undefined}
                      onClick={() => onSelectRow(r)}
                    >
                      <td>
                        <input
                          type="checkbox"
                          checked={compareIds.includes(r.id)}
                          onChange={() => onToggleCompare(r.id)}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </td>
                      <td>
                        <strong>{r.name}</strong>
                        <div className="lv-ao-muted">{r.family}</div>
                      </td>
                      <td>{r.mode || UNMEASURED}</td>
                      <td>{r.market}</td>
                      <td>{r.sharpe}</td>
                      <td>{r.maxDrawdown}</td>
                      <td>{r.winRate}</td>
                      <td>
                        <span className="lv-hub-pill lv-hub-tone-blue">{r.status}</span>
                      </td>
                      <td>
                        <button type="button" className="lv-hub-btn" onClick={() => onSelectRow(r)}>
                          Open
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {!rows.length ? (
                  <tr>
                    <td colSpan={9} className="lv-hub-empty-cell">
                      Geen strategieën in inventaris.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="lv-ao-detail" aria-label="Strategy detail">
          <header className="lv-ao-panel__head">
            <div>
              <h3>{selectedRow?.name ?? "Strategy Detail"}</h3>
              <p className="lv-ao-muted">
                {selectedRow ? `${selectedRow.family} · ${selectedRow.market}` : "Selecteer een strategie."}
              </p>
            </div>
            {selectedRow ? <span className="lv-hub-pill lv-hub-tone-blue">{selectedRow.status}</span> : null}
          </header>
          {selectedRow ? (
            <div className="lv-ao-detail__grid">
              <div>
                <span>Sharpe</span>
                <strong>{selectedRow.sharpe}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>{selectedRow.status}</strong>
              </div>
              <div>
                <span>Markt</span>
                <strong>{selectedRow.market}</strong>
              </div>
              <div>
                <span>Family</span>
                <strong>{selectedRow.family}</strong>
              </div>
              <div className="lv-ao-detail__actions">
                <button type="button" className="lv-hub-btn" onClick={onOpenAdvanced}>
                  Backtest / Lab
                </button>
                <Link
                  className="lv-hub-btn lv-hub-btn--primary"
                  to={`/trading/live-agents?mode=realtime`}
                >
                  Naar sandbox / Live Agents
                </Link>
                <button
                  type="button"
                  className="lv-hub-btn"
                  onClick={onAssignToAgent}
                  disabled={!selectedRow.strategyId}
                  title={
                    selectedRow.strategyId
                      ? "Maakt een echte paper deployment via market_sim"
                      : "Selecteer een strategie met strategyId"
                  }
                >
                  Toewijzen aan agent
                </button>
              </div>
            </div>
          ) : (
            <p className="lv-ao-empty">Geen selectie.</p>
          )}

          <div className="lv-la-control__block">
            <h4>Testomgeving (Paper Money)</h4>
            <button type="button" className="lv-hub-btn" onClick={onOpenAdvanced}>
              Offline replay / backtest
            </button>
            <Link className="lv-hub-btn" to="/trading/live-agents?mode=realtime">
              Realtime sandbox (PAPER)
            </Link>
            <Link className="lv-hub-btn" to="/trading/research?section=lab">
              Research Lab
            </Link>
            <Link className="lv-hub-btn" to="/trading/research?section=research-command">
              Research Command
            </Link>
          </div>
        </aside>
      </div>

      <div className="lv-rc-bottom">
        <section className="lv-ao-panel">
          <header className="lv-ao-panel__head">
            <h3>Autonome Ontdekking Pipeline</h3>
          </header>
          <div className="lv-rc-pipeline">
            {pipeline.map((p) => (
              <div key={p.id} className="lv-rc-pipe">
                <strong>{p.label}</strong>
                <span>{p.count}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="lv-ao-panel">
          <header className="lv-ao-panel__head">
            <h3>Research Agent Jobs</h3>
          </header>
          <ul className="lv-ao-list">
            {data.labs.slice(0, 12).map((l) => {
              const lab = l as Record<string, unknown>;
              return (
                <li key={String(lab.lab_id)}>
                  <strong>{String(lab.lab_id)}</strong> · {String(lab.status || lab.state || UNMEASURED)} ·
                  progress=
                  {lab.progress != null && Number.isFinite(Number(lab.progress))
                    ? `${lab.progress}%`
                    : UNMEASURED}
                </li>
              );
            })}
            {!data.labs.length ? <li className="lv-ao-empty">Geen lab jobs.</li> : null}
          </ul>
        </section>
        <section className="lv-ao-panel">
          <header className="lv-ao-panel__head">
            <h3>Experiment Activiteit</h3>
          </header>
          <ul className="lv-ao-list">
            {data.discovery.slice(0, 12).map((r) => (
              <li key={r.id}>
                {r.name} · {r.status}
              </li>
            ))}
            {!data.discovery.length ? <li className="lv-ao-empty">Geen activiteit.</li> : null}
          </ul>
        </section>
        <section className="lv-ao-panel">
          <header className="lv-ao-panel__head">
            <h3>Dataset &amp; Markt Universum</h3>
            <button type="button" className="lv-hub-btn" onClick={onOpenMarketData}>
              Open data drawer
            </button>
          </header>
          <ul className="lv-ao-list">
            {marketData.library.slice(0, 10).map((row) => (
              <li key={row.id}>
                <strong>{row.symbol}</strong> · {row.timeframe} · {row.status}
              </li>
            ))}
            {!marketData.library.length ? <li className="lv-ao-empty">Geen datasets geïndexeerd.</li> : null}
          </ul>
        </section>
      </div>
    </section>
  );
}
