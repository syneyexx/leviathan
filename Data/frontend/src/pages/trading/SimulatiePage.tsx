import { useCallback, useEffect, useMemo, useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { ApiError, api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import type {
  MarketDataSource,
  MarketSimLiveState,
  MarketSimRun,
  MarketSimStatusResponse,
  MarketStrategy,
} from "../../types/api";
import { LineSeries, Panel, Tone, TradingHero, fmtMoney, hashShort, metricValue } from "./shared";

const SPEEDS = ["0.1x", "0.5x", "1x", "2x", "5x", "10x"] as const;
const TFS = ["1m", "5m", "15m", "1h", "4h", "1D"] as const;

export function SimulatiePage() {
  const toast = useAppToast();
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>("1x");
  const [tf, setTf] = useState<(typeof TFS)[number]>("1h");
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
      setError(err instanceof ApiError ? err.message : "Failed to load market sim status");
    }
  }, [activeRunId, sourceId, strategyId]);

  const refreshLive = useCallback(async () => {
    if (!activeRunId || !status?.enabled) return;
    try {
      setLive(await api.getMarketSimLive(activeRunId));
    } catch (err) {
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
  const selectedSource = sources.find((s) => s.source_id === sourceId);
  const progressPct =
    run && run.bar_count > 0 ? Math.min(100, Math.round((run.bar_index / run.bar_count) * 100)) : 0;
  const equityPoints = useMemo(() => {
    const pts = (live?.equity ?? []).map((p) => p.equity);
    if (pts.length >= 2) return pts;
    return run ? [run.initial_cash, run.equity] : [100_000];
  }, [live, run]);
  const drawdownPoints = useMemo(() => {
    let peak = equityPoints[0] ?? 0;
    return equityPoints.map((v) => {
      peak = Math.max(peak, v);
      return peak > 0 ? -((peak - v) / peak) * 100 : 0;
    });
  }, [equityPoints]);
  const brainTotal = (run?.brain_hits ?? 0) + (run?.brain_misses ?? 0);
  const playing = run?.status === "RUNNING" || run?.status === "QUEUED";

  async function createAndStart() {
    if (!sourceId) {
      toast("Select market data first");
      return;
    }
    setBusy(true);
    try {
      const speedNum = Number.parseFloat(speed.replace("x", "")) || 1;
      const { run: created } = await api.createMarketSimRun({
        sourceId,
        strategyId: strategyId || undefined,
        seed: 42,
        speed: speedNum,
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

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Simulation Mode"
      searchPlaceholder="Search markets, assets, strategies, or run simulations..."
      systemItems={[
        status?.enabled ? "MARKET SIM ON" : "MARKET SIM OFF",
        run?.status ? `RUN ${run.status}` : "NO RUN",
      ]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="MARKT SIMULATIE"
          kicker="REPLAY. ANALYZE. ADAPT."
          quote="“The markets always speak. Simulation lets you listen more carefully.” — LEVIATHAN"
          image={tradingHeroes.simulatie}
          objectPosition="center 32%"
        />
        {error ? (
          <Panel title="Market Sim">
            <p>{error}</p>
            <p className="lv-tp-muted">
              Sources ready: {status?.health.sources_ready ?? 0} · Root:{" "}
              {status?.health.markets_root ?? "—"}
            </p>
          </Panel>
        ) : null}

        <section className="lv-sim-config" aria-label="Simulation configuration">
          <article className="lv-sim-config-card">
            <div className="lbl">Market data</div>
            <select
              className="lv-tp-select"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              style={{ width: "100%", marginTop: 6 }}
            >
              <option value="">Select source…</option>
              {sources.map((s) => (
                <option key={s.source_id} value={s.source_id}>
                  {s.symbol} {s.timeframe} · {s.bar_count} bars · {s.status}
                </option>
              ))}
            </select>
            <p>{selectedSource ? hashShort(selectedSource.content_hash) : "Register files on Marktdata"}</p>
          </article>
          <article className="lv-sim-config-card">
            <div className="lbl">Asset / Market</div>
            <strong>{run?.symbol ?? selectedSource?.symbol ?? "—"}</strong>
            <p>
              {run?.timeframe ?? selectedSource?.timeframe ?? "—"} · paper sim only
            </p>
          </article>
          <article className="lv-sim-config-card">
            <div className="lbl">Historical window</div>
            <strong>
              {run?.start_ts?.slice(0, 10) ?? selectedSource?.start_ts?.slice(0, 10) ?? "—"} —{" "}
              {run?.end_ts?.slice(0, 10) ?? selectedSource?.end_ts?.slice(0, 10) ?? "—"}
            </strong>
            <p>
              Clock {run?.clock_ts ?? "idle"} · bar {run?.bar_index ?? 0}/{run?.bar_count ?? 0}
            </p>
          </article>
          <article className="lv-sim-config-card">
            <div className="lbl">Strategy</div>
            <select
              className="lv-tp-select"
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              style={{ width: "100%", marginTop: 6 }}
            >
              <option value="">Default MA cross</option>
              {strategies.map((s) => (
                <option key={s.strategy_id} value={s.strategy_id}>
                  {s.name} v{s.current_version}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="lv-tp-btn lv-tp-btn--accent"
              style={{ marginTop: 8 }}
              disabled={busy}
              onClick={() => void createAndStart()}
            >
              New Run
            </button>
          </article>
        </section>

        <section className="lv-sim-playback" aria-label="Playback controls">
          <div className="lv-sim-controls">
            <button type="button" disabled={busy || !activeRunId} onClick={() => void control("stop")} aria-label="Stop">
              ⏹
            </button>
            <button type="button" disabled={busy || !activeRunId} onClick={() => void control("step")} aria-label="Step">
              ⏭
            </button>
            <button
              type="button"
              className={playing ? "is-active" : ""}
              disabled={busy || !activeRunId}
              onClick={() => void control(playing ? "pause" : "start")}
              aria-label="Play/Pause"
            >
              {playing ? "⏸" : "▶"}
            </button>
            <button type="button" disabled={busy || !activeRunId} onClick={() => void control("start")} aria-label="Resume">
              ⏭⏭
            </button>
          </div>
          <div className="lv-sim-speeds">
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                className={`lv-tp-chip${speed === s ? " is-active" : ""}`}
                onClick={() => setSpeed(s)}
              >
                {s}
              </button>
            ))}
          </div>
          <div className="lv-sim-timeline">
            <div className="lv-sim-timeline-meta">
              <span>{run?.clock_ts ?? "No active clock"}</span>
              <span className="lv-tp-muted">
                Bar {run?.bar_index ?? 0}/{run?.bar_count ?? 0} · {progressPct}%
              </span>
            </div>
            <div className="lv-sim-seek" role="slider" aria-valuenow={progressPct} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${progressPct}%` }} />
            </div>
          </div>
          <select
            className="lv-tp-select"
            value={activeRunId ?? ""}
            onChange={(e) => setActiveRunId(e.target.value || null)}
          >
            <option value="">Select run…</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.symbol} · {r.status} · {r.run_id.slice(0, 8)}
              </option>
            ))}
          </select>
        </section>

        <section className="lv-sim-chart-grid">
          <Panel
            title={`${run?.symbol ?? "Market"} · Equity Replay`}
            action={
              <div className="lv-tp-tabs">
                {TFS.map((t) => (
                  <button
                    key={t}
                    type="button"
                    className={`lv-tp-chip${tf === t ? " is-active" : ""}`}
                    onClick={() => setTf(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>
            }
          >
            <div className="lv-sim-chart-head">
              <div>
                <strong>{run?.symbol ?? "—"}</strong>
                <span className="lv-tp-mono">{fmtMoney(run?.equity)}</span>
                <Tone value={(run?.equity ?? 0) - (run?.initial_cash ?? 0)}>
                  {run ? `${(((run.equity - run.initial_cash) / run.initial_cash) * 100).toFixed(2)}%` : "—"}
                </Tone>
              </div>
              <div className="lv-tp-muted">
                Causality violations: {run?.causality_violations ?? 0} · hash {hashShort(run?.data_hash)}
              </div>
            </div>
            <LineSeries series={[{ values: equityPoints, color: "#D6A957" }]} height={240} />
          </Panel>

          <Panel title="Order Book">
            <p className="lv-tp-muted">
              L2 order book UNAVAILABLE for this run — no order-book snapshots registered. Fill model uses
              conservative bar close ± slippage.
            </p>
          </Panel>

          <Panel title="Simulated Fills (Tape)">
            <div className="lv-sim-tape">
              {(live?.fills ?? [])
                .slice(-24)
                .reverse()
                .map((f) => (
                  <div key={f.fill_id} className="lv-sim-tape-row">
                    <span className="lv-tp-muted">bar {f.bar_index}</span>
                    <span className={f.side === "BUY" ? "is-good" : "is-bad"}>{f.side}</span>
                    <span>{f.price.toFixed(2)}</span>
                    <span>{f.qty.toFixed(4)}</span>
                  </div>
                ))}
              {!live?.fills?.length ? (
                <div className="lv-sim-tape-row">
                  <span className="lv-tp-muted">No fills yet — paper sim only</span>
                </div>
              ) : null}
            </div>
          </Panel>
        </section>

        <section className="lv-sim-stats">
          <Panel title="Simulated Portfolio Value">
            <div style={{ fontSize: 28, fontWeight: 700, color: "var(--lv-text-bright)" }}>
              {fmtMoney(run?.equity)}
            </div>
            <Tone value={(run?.equity ?? 0) - (run?.initial_cash ?? 0)}>
              {metricValue(run?.metrics, "total_return")}
            </Tone>
            <div className="lv-sim-metric-grid" style={{ marginTop: 10 }}>
              <div>
                <span>Initial Capital</span>
                <strong>{fmtMoney(run?.initial_cash)}</strong>
              </div>
              <div>
                <span>Unrealized P&amp;L</span>
                <strong>{fmtMoney(run?.unrealized_pnl)}</strong>
              </div>
              <div>
                <span>Realized P&amp;L</span>
                <strong>{fmtMoney(run?.realized_pnl)}</strong>
              </div>
              <div>
                <span>Cash</span>
                <strong>{fmtMoney(run?.cash)}</strong>
              </div>
            </div>
          </Panel>

          <Panel title="Strategy Performance">
            <div className="lv-sim-metric-grid">
              {[
                ["Total Return", metricValue(run?.metrics, "total_return")],
                ["Sharpe", metricValue(run?.metrics, "sharpe")],
                ["Sortino", metricValue(run?.metrics, "sortino")],
                ["Max Drawdown", metricValue(run?.metrics, "max_drawdown")],
                ["Buy & Hold", metricValue(run?.metrics, "buy_and_hold_return")],
                ["Fees Paid", metricValue(run?.metrics, "fees_paid")],
                ["Win Rate", metricValue(run?.metrics, "win_rate")],
                [
                  "Brain Hit Rate",
                  brainTotal
                    ? `${(((run?.brain_hits ?? 0) / brainTotal) * 100).toFixed(0)}%`
                    : "UNMEASURED",
                ],
              ].map(([k, v]) => (
                <div key={String(k)}>
                  <span>{k}</span>
                  <strong>{v}</strong>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Equity Curve">
            <LineSeries series={[{ values: equityPoints, color: "#22c9d6" }]} height={120} />
            <div className="lv-tp-muted" style={{ marginTop: 4 }}>
              Live equity from simulation worker
            </div>
          </Panel>

          <Panel title="Drawdown Analysis">
            <LineSeries series={[{ values: drawdownPoints, color: "#f87171" }]} height={90} />
            <div className="lv-sim-metric-grid" style={{ marginTop: 8 }}>
              <div>
                <span>Max Drawdown</span>
                <strong className="is-bad">{metricValue(run?.metrics, "max_drawdown")}</strong>
              </div>
              <div>
                <span>Position</span>
                <strong>{run ? run.position_qty.toFixed(4) : "—"}</strong>
              </div>
              <div>
                <span>Seed</span>
                <strong>{run?.seed ?? "—"}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>{run?.status ?? "—"}</strong>
              </div>
            </div>
          </Panel>
        </section>

        <section className="lv-sim-bottom">
          <Panel title="Agent Deliberation">
            <table className="lv-tp-table">
              <thead>
                <tr>
                  <th>Bar</th>
                  <th>Kind</th>
                  <th>Role</th>
                  <th>Content</th>
                  <th>Conf</th>
                </tr>
              </thead>
              <tbody>
                {(live?.messages ?? [])
                  .slice(-20)
                  .reverse()
                  .map((m) => (
                    <tr key={m.message_id}>
                      <td>{m.bar_index}</td>
                      <td>{m.kind}</td>
                      <td>{m.role}</td>
                      <td>{m.content}</td>
                      <td>{(m.confidence * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                {!live?.messages?.length ? (
                  <tr>
                    <td colSpan={5}>No deliberation yet</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </Panel>

          <Panel title="Agents on Run">
            {(run?.agents ?? []).map((w) => (
              <div key={String(w.agent_id ?? w.role)} className="lv-sim-worker">
                <strong>{String(w.agent_id ?? w.role)}</strong>
                <div>
                  <div>{String(w.label ?? w.role)}</div>
                  <div className="lv-tp-bar" style={{ marginTop: 4 }}>
                    <span style={{ width: `${progressPct}%` }} />
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <span className={`lv-tp-pill${playing ? " is-live" : ""}`}>{run?.status ?? "—"}</span>
                </div>
              </div>
            ))}
            {!run?.agents?.length ? (
              <p className="lv-tp-muted">Single-strategy mode or no run selected</p>
            ) : null}
          </Panel>

          <Panel title="Simulation Summary" className="lv-sim-summary">
            <dl>
              <dt>Initial Capital</dt>
              <dd>{fmtMoney(run?.initial_cash ?? 100_000)}</dd>
              <dt>Active workers</dt>
              <dd>{status?.active_runs ?? 0}</dd>
              <dt>Fee model</dt>
              <dd>bps + slippage (paper)</dd>
              <dt>Data hash</dt>
              <dd>{hashShort(run?.data_hash)}</dd>
              <dt>Brain hits / misses</dt>
              <dd>
                {run?.brain_hits ?? 0} / {run?.brain_misses ?? 0}
              </dd>
              <dt>Causality violations</dt>
              <dd>{run?.causality_violations ?? 0}</dd>
              <dt>Fill model</dt>
              <dd>Bar close ± slippage</dd>
              <dt>Benchmark</dt>
              <dd>Buy &amp; hold</dd>
            </dl>
          </Panel>
        </section>

        <footer className="lv-sim-foot">
          <span>Same markets. A sharper you. — LEVIATHAN</span>
          <span className={`lv-tp-pill${playing ? " is-live" : ""}`}>
            {run?.status ?? "Idle"} · paper only
          </span>
        </footer>
      </main>
    </AppShell>
  );
}
