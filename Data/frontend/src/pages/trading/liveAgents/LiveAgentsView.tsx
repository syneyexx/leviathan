/**
 * Live Agents — SCREEN 2 composition.
 */
import { Link } from "react-router-dom";
import { UNMEASURED, fmtUsd } from "../workspaces/commandHub/hubFormat";
import type { LiveAgentsData } from "./useLiveAgentsData";

function Spark({ values }: { values: number[] }) {
  if (!values.length) return <div className="lv-hub-spark lv-hub-spark--empty" aria-hidden="true" />;
  const w = 96;
  const h = 28;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1 || 1)) * w;
      const y = h - ((v - min) / span) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className="lv-hub-spark lv-hub-spark--tone-green" viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={pts} fill="none" strokeWidth={1.6} />
    </svg>
  );
}

export function LiveAgentsView({
  data,
  onOpenAdvanced,
}: {
  data: LiveAgentsData;
  onOpenAdvanced: () => void;
}) {
  const sel = data.selected;

  return (
    <section className="lv-la" aria-label="Live Agents" aria-busy={data.loading}>
      <div className="lv-ao__truth">
        <span className="lv-tc-badge lv-tc-badge--exec">PAPER EXECUTION</span>
        <span className="lv-tc-badge">
          {data.dataMode === "realtime" ? "REALTIME FEED" : "OFFLINE REPLAY"} ≠ LIVE MONEY
        </span>
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
      {data.notice ? <p className="lv-ao-notice">{data.notice}</p> : null}

      <div className="lv-hub-kpis">
        {data.kpis.map((k) => (
          <article key={k.id} className="lv-hub-kpi lv-hub-kpi--tone-blue">
            <p className="lv-hub-kpi__label">{k.label}</p>
            <p className="lv-hub-kpi__value">{k.value}</p>
            <div className="lv-hub-kpi__foot">
              <span className="lv-hub-kpi__delta lv-hub-tone-muted">{k.delta}</span>
              <Spark values={k.spark} />
            </div>
          </article>
        ))}
      </div>

      <div className="lv-la-main">
        <section className="lv-la-grid-wrap" aria-label="Live Agent Grid">
          <header className="lv-ao-panel__head">
            <h3>
              Live Agent Grid{" "}
              <span className="lv-ao-muted">
                ({data.agents.filter((a) => a.statusTone === "green").length} actief · PAPER)
              </span>
            </h3>
            <div className="lv-ao-registry__actions">
              <input
                className="lv-ao-search"
                placeholder="Zoek agent…"
                value={data.search}
                onChange={(e) => data.setSearch(e.target.value)}
              />
              <button type="button" className="lv-hub-btn" onClick={onOpenAdvanced}>
                Advanced deploy
              </button>
            </div>
          </header>
          <div className="lv-la-grid">
            {data.agents.map((a) => (
              <article
                key={a.id}
                className={`lv-la-card${sel?.id === a.id ? " is-selected" : ""}`}
                onClick={() => data.setSelectedId(a.id)}
              >
                <header>
                  <div>
                    <strong>{a.name}</strong>
                    <div className="lv-ao-muted">
                      {a.role} · {a.strategy}
                    </div>
                  </div>
                  <span className={`lv-hub-pill lv-hub-tone-${a.statusTone}`}>{a.status}</span>
                </header>
                <Spark values={a.spark} />
                <dl className="lv-la-card__stats">
                  <div>
                    <dt>PnL (paper)</dt>
                    <dd>{a.sessionPnl != null ? fmtUsd(a.sessionPnl) : UNMEASURED}</dd>
                  </div>
                  <div>
                    <dt>Wallet</dt>
                    <dd>{a.wallet != null ? fmtUsd(a.wallet) : UNMEASURED}</dd>
                  </div>
                  <div>
                    <dt>Open posities</dt>
                    <dd>{a.openPositions}</dd>
                  </div>
                  <div>
                    <dt>Order queue</dt>
                    <dd>{a.queueDepth}</dd>
                  </div>
                  <div>
                    <dt>Laatste actie</dt>
                    <dd>{a.latestAction}</dd>
                  </div>
                  <div>
                    <dt>Latency</dt>
                    <dd>{a.latency}</dd>
                  </div>
                </dl>
                <div className="lv-la-card__actions">
                  <Link className="lv-hub-btn" to={`/trading/agents?agent=${encodeURIComponent(a.id)}`}>
                    Open
                  </Link>
                  <button type="button" className="lv-hub-btn" onClick={() => data.setSelectedId(a.id)}>
                    Focus
                  </button>
                  <span className="lv-tc-badge">PAPER</span>
                </div>
              </article>
            ))}
            {!data.agents.length ? <p className="lv-ao-empty">Geen live agents.</p> : null}
          </div>
        </section>

        <aside className="lv-la-control" aria-label="Trading Control">
          <header className="lv-ao-panel__head">
            <h3>Trading Control</h3>
          </header>
          <div className="lv-ao-tabs">
            <button
              type="button"
              className={`lv-ao-tab${data.dataMode === "realtime" ? " is-active" : ""}`}
              onClick={() => data.setDataMode("realtime")}
            >
              Realtime marktdata
            </button>
            <button
              type="button"
              className={`lv-ao-tab${data.dataMode === "offline" ? " is-active" : ""}`}
              onClick={() => data.setDataMode("offline")}
            >
              Offline replay
            </button>
          </div>

          {data.dataMode === "realtime" ? (
            <div className="lv-la-control__block">
              <p className="lv-ao-muted">Databronnen (alleen geconfigureerde providers — geen screenshot-fictie).</p>
              <ul className="lv-ao-list">
                {data.providers.map((p, i) => (
                  <li key={String(p.id || p.provider_id || i)}>
                    {String(p.id || p.provider_id || p.name || "provider")} ·{" "}
                    {String(p.status || p.reachable || UNMEASURED)}
                  </li>
                ))}
                {!data.providers.length ? (
                  <li className="lv-ao-empty">Geen provider-lijst beschikbaar — feed health via Advanced.</li>
                ) : null}
              </ul>
            </div>
          ) : (
            <div className="lv-la-control__block">
              <label>
                Scenario preset
                <select value={data.scenarioPreset} onChange={(e) => data.setScenarioPreset(e.target.value)}>
                  {(data.presets.length ? data.presets : [{ id: "crash_recovery" }, { id: "range_chop" }, { id: "trend_up" }]).map(
                    (p) => (
                      <option key={p.id} value={p.id}>
                        {p.id}
                      </option>
                    ),
                  )}
                </select>
              </label>
              <label>
                Replay snelheid
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={data.replaySpeed}
                  onChange={(e) => data.setReplaySpeed(Number(e.target.value) || 1)}
                />
              </label>
              <div className="lv-la-card__actions">
                <button
                  type="button"
                  className="lv-hub-btn"
                  disabled={!!data.busy}
                  onClick={() => void data.generateScenario()}
                >
                  {data.busy === "scenario" ? "Genereren…" : "AI-generated scenario"}
                </button>
                <button
                  type="button"
                  className="lv-hub-btn lv-hub-btn--primary"
                  disabled={!!data.busy}
                  onClick={() => void data.startReplay()}
                >
                  {data.busy === "replay" ? "Start…" : "Start offline replay"}
                </button>
              </div>
              <p className="lv-ao-muted">
                AI genereert gestructureerde constraints; OHLCV is deterministisch uit seed — geen freehand candles.
              </p>
            </div>
          )}

          <div className="lv-la-control__block">
            <h4>Risk &amp; Execution</h4>
            <label>
              Max. posities per agent
              <input value={data.maxPositions} onChange={(e) => data.setMaxPositions(e.target.value)} />
            </label>
            <label>
              Max. positie grootte (%)
              <input value={data.maxPosSize} onChange={(e) => data.setMaxPosSize(e.target.value)} />
            </label>
            <label className="lv-la-check">
              <input type="checkbox" checked={data.paperOnly} onChange={(e) => data.setPaperOnly(e.target.checked)} disabled />
              Paper trading modus (verplicht)
            </label>
            <label className="lv-la-check">
              <input
                type="checkbox"
                checked={data.riskGuards}
                onChange={(e) => data.setRiskGuards(e.target.checked)}
              />
              Risk guards actief
            </label>
            <div className="lv-la-card__actions">
              <button type="button" className="lv-hub-btn lv-hub-btn--primary" onClick={onOpenAdvanced}>
                Start paper trading
              </button>
              <button
                type="button"
                className="lv-hub-btn lv-hub-btn--danger"
                disabled={!!data.busy}
                onClick={() => void data.killAll()}
              >
                Stop alle agents / kill
              </button>
            </div>
          </div>

          {sel ? (
            <div className="lv-la-control__block">
              <h4>Geselecteerde Agent: {sel.name}</h4>
              <p className="lv-ao-muted">
                {sel.role} · Execution=PAPER · Data={data.dataMode}
              </p>
              <Link className="lv-hub-btn" to={`/trading/agents?agent=${encodeURIComponent(sel.id)}&tab=overzicht`}>
                Open in Agent Overzicht
              </Link>
            </div>
          ) : null}
        </aside>
      </div>

      <div className="lv-la-bottom">
        <section className="lv-ao-panel">
          <header className="lv-ao-panel__head">
            <h3>Order &amp; Execution Stream</h3>
          </header>
          <div className="lv-ao-table-scroll">
            <table className="lv-hub-table">
              <thead>
                <tr>
                  <th>Tijd</th>
                  <th>Symbool</th>
                  <th>Side</th>
                  <th>Aantal</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.orders.map((o, i) => (
                  <tr key={String(o.order_id || o.id || i)}>
                    <td>{String(o.created_at || o.timestamp || UNMEASURED)}</td>
                    <td>{String(o.symbol || UNMEASURED)}</td>
                    <td>{String(o.side || UNMEASURED)}</td>
                    <td>{String(o.qty || o.quantity || UNMEASURED)}</td>
                    <td>{String(o.status || UNMEASURED)}</td>
                  </tr>
                ))}
                {!data.orders.length ? (
                  <tr>
                    <td colSpan={5} className="lv-hub-empty-cell">
                      Geen recente paper orders.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <section className="lv-ao-panel">
          <header className="lv-ao-panel__head">
            <h3>Markt Snapshot</h3>
          </header>
          <ul className="lv-ao-list">
            {data.marketSnapshot.map((m) => (
              <li key={`${m.symbol}-${m.timeframe}-${m.path}`}>
                <strong>{m.symbol}</strong> · {m.timeframe} · {m.status} · prijs={m.price} · 24h={m.change}
              </li>
            ))}
            {!data.marketSnapshot.length ? <li className="lv-ao-empty">Geen marktdata-bronnen.</li> : null}
          </ul>
        </section>

        <section className="lv-ao-panel">
          <header className="lv-ao-panel__head">
            <h3>Agent Event Timeline</h3>
          </header>
          <ul className="lv-ao-list">
            {data.decisions.slice(0, 20).map((d) => (
              <li key={d.decisionId}>
                {d.asOf || UNMEASURED} · {d.agentId} · {d.stage}
              </li>
            ))}
            {!data.decisions.length ? <li className="lv-ao-empty">Geen publieke events.</li> : null}
          </ul>
        </section>

        <section className="lv-ao-panel">
          <header className="lv-ao-panel__head">
            <h3>Paper Broker &amp; Queue Health</h3>
          </header>
          <dl className="lv-ao-risk">
            {data.brokerHealth.map((b) => (
              <div key={b.id}>
                <dt>{b.label}</dt>
                <dd>{b.value}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </section>
  );
}
