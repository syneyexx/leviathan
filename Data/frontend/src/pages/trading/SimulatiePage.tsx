import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../../api/client";
import type {
  MarketDataSource,
  MarketSimLiveState,
  MarketSimRun,
  MarketSimStatusResponse,
  MarketStrategy,
} from "../../types/api";
import { useAppToast } from "../../state/useAppToast";
import { TradingShell, fmtMoney, hashShort, metricValue } from "./shared";

function EquitySpark({ points }: { points: number[] }) {
  if (points.length < 2) {
    return <div className="lv-tr-empty">No equity points yet</div>;
  }
  const max = Math.max(...points);
  const min = Math.min(...points);
  const path = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * 620;
      const y = 200 - ((v - min) / (max - min || 1)) * 160;
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");
  return (
    <svg className="lv-tr-chart-svg" viewBox="0 0 640 220" role="img" aria-label="Equity curve">
      {[0, 1, 2, 3, 4].map((i) => (
        <line key={i} x1="20" x2="620" y1={20 + i * 40} y2={20 + i * 40} stroke="rgba(214,169,87,0.08)" />
      ))}
      <path d={path} fill="none" stroke="#D6A957" strokeWidth="1.6" transform="translate(20,0)" />
      <text x="28" y="28" className="lv-tr-axis">
        {fmtMoney(max)}
      </text>
      <text x="28" y="188" className="lv-tr-axis">
        {fmtMoney(min)}
      </text>
    </svg>
  );
}

export function SimulatiePage() {
  const toast = useAppToast();
  const [status, setStatus] = useState<MarketSimStatusResponse | null>(null);
  const [sources, setSources] = useState<MarketDataSource[]>([]);
  const [strategies, setStrategies] = useState<MarketStrategy[]>([]);
  const [runs, setRuns] = useState<MarketSimRun[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [strategyId, setStrategyId] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [live, setLive] = useState<MarketSimLiveState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshMeta = useCallback(async () => {
    try {
      const [st, data, strat, runList] = await Promise.all([
        api.marketSimStatus(),
        api.listMarketData().catch(() => ({ sources: [] as MarketDataSource[] })),
        api.listMarketStrategies().catch(() => ({ strategies: [] as MarketStrategy[] })),
        api.listMarketSimRuns().catch(() => ({ runs: [] as MarketSimRun[] })),
      ]);
      setStatus(st);
      setSources(data.sources);
      setStrategies(strat.strategies);
      setRuns(runList.runs);
      if (!sourceId && data.sources[0]) setSourceId(data.sources[0].source_id);
      if (!strategyId && strat.strategies[0]) setStrategyId(strat.strategies[0].strategy_id);
      if (!activeRunId && runList.runs[0]) setActiveRunId(runList.runs[0].run_id);
      setError(st.enabled ? null : "Market sim disabled — set LEVIATHAN_FEATURE_MARKET_SIM=true");
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to load market sim status";
      setError(msg);
    }
  }, [activeRunId, sourceId, strategyId]);

  const refreshLive = useCallback(async () => {
    if (!activeRunId || !status?.enabled) return;
    try {
      const state = await api.getMarketSimLive(activeRunId);
      setLive(state);
    } catch (err) {
      // keep last live snapshot; surface soft error
      if (err instanceof ApiError && err.status === 404) setLive(null);
    }
  }, [activeRunId, status?.enabled]);

  useEffect(() => {
    void refreshMeta();
  }, [refreshMeta]);

  useEffect(() => {
    void refreshLive();
    if (!activeRunId) return;
    const id = window.setInterval(() => void refreshLive(), 1500);
    return () => window.clearInterval(id);
  }, [activeRunId, refreshLive]);

  const run = live?.run;
  const equityPoints = useMemo(() => (live?.equity ?? []).map((p) => p.equity), [live]);

  async function createAndStart() {
    if (!sourceId) {
      toast("Select market data first");
      return;
    }
    setBusy(true);
    try {
      const { run: created } = await api.createMarketSimRun({
        sourceId,
        strategyId: strategyId || undefined,
        seed: 42,
        deliberationEveryN: 5,
      });
      await api.startMarketSimRun(created.run_id);
      setActiveRunId(created.run_id);
      toast("Simulation started");
      await refreshMeta();
      await refreshLive();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Failed to start run");
    } finally {
      setBusy(false);
    }
  }

  async function control(action: "pause" | "step" | "stop" | "start") {
    if (!activeRunId) return;
    setBusy(true);
    try {
      if (action === "pause") await api.pauseMarketSimRun(activeRunId);
      if (action === "step") await api.stepMarketSimRun(activeRunId);
      if (action === "stop") await api.stopMarketSimRun(activeRunId);
      if (action === "start") await api.startMarketSimRun(activeRunId);
      await refreshLive();
      await refreshMeta();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Control failed");
    } finally {
      setBusy(false);
    }
  }

  const brainTotal = (run?.brain_hits ?? 0) + (run?.brain_misses ?? 0);

  return (
    <TradingShell title="Simulatie">
      {error ? (
        <article className="lv-panel lv-tr-card">
          <div className="lv-section-label">Market Sim</div>
          <p>{error}</p>
          <p className="lv-muted">
            Sources ready: {status?.health.sources_ready ?? 0} · Root configured:{" "}
            {status?.health.configured ? "yes" : "no"}
          </p>
        </article>
      ) : null}

      <section className="lv-tr-kpi-row">
        {[
          { label: "Equity", value: fmtMoney(run?.equity), delta: run?.status ?? "—" },
          { label: "Cash", value: fmtMoney(run?.cash), delta: "paper" },
          {
            label: "Position",
            value: run ? run.position_qty.toFixed(4) : "—",
            delta: run?.symbol ?? "",
          },
          {
            label: "Realized PnL",
            value: fmtMoney(run?.realized_pnl),
            delta: run && run.realized_pnl >= 0 ? "ok" : "",
          },
          {
            label: "Causality Violations",
            value: String(run?.causality_violations ?? 0),
            delta: "must be 0",
          },
          {
            label: "Brain Hit Rate",
            value: brainTotal ? `${(((run?.brain_hits ?? 0) / brainTotal) * 100).toFixed(0)}%` : "UNMEASURED",
            delta: `${run?.brain_hits ?? 0}h / ${run?.brain_misses ?? 0}m`,
          },
        ].map((item) => (
          <article key={item.label} className="lv-tr-kpi">
            <div className="lv-tr-kpi-label">{item.label}</div>
            <div className="lv-tr-kpi-value">{item.value}</div>
            <div className="lv-tr-kpi-foot">
              <span>{item.delta}</span>
            </div>
          </article>
        ))}
      </section>

      <section className="lv-tr-mid">
        <article className="lv-panel lv-tr-card lv-tr-card--chart">
          <div className="lv-tr-chart-head">
            <div>
              <strong>{run?.symbol ?? "No run"}</strong>
              <span className="lv-tr-price">{run?.clock_ts ?? "clock idle"}</span>
              <span>
                bar {run?.bar_index ?? 0}/{run?.bar_count ?? 0}
              </span>
            </div>
            <div className="lv-tr-tf">
              <button type="button" disabled={busy} onClick={() => void createAndStart()}>
                New Run
              </button>
              <button type="button" disabled={busy || !activeRunId} onClick={() => void control("start")}>
                Play
              </button>
              <button type="button" disabled={busy || !activeRunId} onClick={() => void control("pause")}>
                Pause
              </button>
              <button type="button" disabled={busy || !activeRunId} onClick={() => void control("step")}>
                Step
              </button>
              <button type="button" disabled={busy || !activeRunId} onClick={() => void control("stop")}>
                Stop
              </button>
            </div>
          </div>
          <EquitySpark points={equityPoints} />
          <div className="lv-tr-ma">
            <span>Data hash {hashShort(run?.data_hash)}</span>
            <span>Seed {run?.seed ?? "—"}</span>
            <span>Status {run?.status ?? "—"}</span>
          </div>
        </article>

        <article className="lv-panel lv-tr-card lv-tr-order">
          <div className="lv-section-label">Scenario</div>
          <label className="lv-tr-field">
            <span>Market data</span>
            <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
              <option value="">Select source…</option>
              {sources.map((s) => (
                <option key={s.source_id} value={s.source_id}>
                  {s.symbol} {s.timeframe} · {s.bar_count} bars · {s.status}
                </option>
              ))}
            </select>
          </label>
          <label className="lv-tr-field">
            <span>Strategy</span>
            <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
              <option value="">Default MA cross</option>
              {strategies.map((s) => (
                <option key={s.strategy_id} value={s.strategy_id}>
                  {s.name} v{s.current_version}
                </option>
              ))}
            </select>
          </label>
          <label className="lv-tr-field">
            <span>Active run</span>
            <select
              value={activeRunId ?? ""}
              onChange={(e) => setActiveRunId(e.target.value || null)}
            >
              <option value="">None</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.symbol} · {r.status} · {r.run_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <div className="lv-tr-est">
            <span>
              Workers active <strong>{status?.active_runs ?? 0}</strong>
            </span>
            <span>
              Sources ready <strong>{status?.health.sources_ready ?? 0}</strong>
            </span>
          </div>
        </article>

        <div className="lv-tr-rightcol">
          <article className="lv-panel lv-tr-card">
            <div className="lv-section-label">Metrics</div>
            <ul className="lv-tr-activity">
              {[
                ["Total return", metricValue(run?.metrics, "total_return")],
                ["Sharpe", metricValue(run?.metrics, "sharpe")],
                ["Max drawdown", metricValue(run?.metrics, "max_drawdown")],
                ["Buy & hold", metricValue(run?.metrics, "buy_and_hold_return")],
                ["Fees paid", metricValue(run?.metrics, "fees_paid")],
              ].map(([label, value]) => (
                <li key={label}>
                  <span className="lv-tr-dot info" />
                  <div>
                    <strong>
                      {label}: {value}
                    </strong>
                  </div>
                </li>
              ))}
            </ul>
          </article>
        </div>
      </section>

      <section className="lv-tr-tables">
        <article className="lv-panel lv-tr-card">
          <div className="lv-section-label">Fills</div>
          <div className="lv-tr-table-wrap">
            <table className="lv-tr-table">
              <thead>
                <tr>
                  <th>Bar</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Fee</th>
                  <th>Agent</th>
                </tr>
              </thead>
              <tbody>
                {(live?.fills ?? []).slice(-20).reverse().map((f) => (
                  <tr key={f.fill_id}>
                    <td>{f.bar_index}</td>
                    <td>
                      <span className={`lv-tr-side ${f.side.toLowerCase()}`}>{f.side}</span>
                    </td>
                    <td>{f.qty.toFixed(4)}</td>
                    <td>{f.price.toFixed(2)}</td>
                    <td>{f.fee.toFixed(4)}</td>
                    <td>{f.agent_id ?? "—"}</td>
                  </tr>
                ))}
                {!live?.fills?.length ? (
                  <tr>
                    <td colSpan={6}>No fills yet — paper sim only, no fabricated orders</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </article>

        <article className="lv-panel lv-tr-card">
          <div className="lv-section-label">Agent deliberation</div>
          <ul className="lv-tr-activity">
            {(live?.messages ?? [])
              .slice(-30)
              .reverse()
              .map((m) => (
                <li key={m.message_id}>
                  <span className={`lv-tr-dot ${m.kind === "veto" ? "info" : "ok"}`} />
                  <div>
                    <strong>
                      [{m.kind}] {m.role}: {m.content}
                    </strong>
                    <small>
                      bar {m.bar_index} · conf {(m.confidence * 100).toFixed(0)}%
                      {m.brain_refs?.length ? ` · brain ${m.brain_refs.length}` : ""}
                    </small>
                  </div>
                </li>
              ))}
            {!live?.messages?.length ? (
              <li>
                <span className="lv-tr-dot info" />
                <div>
                  <strong>No deliberation yet</strong>
                  <small>Messages appear when multi-agent rounds run</small>
                </div>
              </li>
            ) : null}
          </ul>
        </article>

        <article className="lv-panel lv-tr-card">
          <div className="lv-section-label">Agents on run</div>
          <ul className="lv-tr-agents">
            {(run?.agents ?? []).map((a) => (
              <li key={String(a.agent_id ?? a.role)}>
                <div>
                  <strong>{String(a.label ?? a.role)}</strong>
                  <small>{String(a.role)}</small>
                </div>
                <span>{String(a.strategy_id ?? "shared").slice(0, 8)}</span>
              </li>
            ))}
            {!run?.agents?.length ? (
              <li>
                <div>
                  <strong>Single-strategy mode</strong>
                  <small>No agent roster on this run</small>
                </div>
              </li>
            ) : null}
          </ul>
        </article>
      </section>
    </TradingShell>
  );
}
