import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type {
  MarketDataSource,
  MarketSimLiveState,
  MarketSimRun,
  MarketSimStatusResponse,
  MarketStrategy,
} from "../../types/api";
import { tradingHeroes } from "../../assets/tradingAssets";
import { AppShell } from "../../layouts/AppShell";
import { fmtMoney, metricValue } from "./shared";
import "../../styles/trading-simulation-reference.css";

type ConsoleTab = "activity" | "messages" | "fills" | "wallets" | "decisions";
type AgentWallet = {
  wallet_id?: string;
  owner_id?: string;
  owner_kind?: string;
  cash?: number;
  position_qty?: number;
  equity?: number;
};

function StatusBadge({
  label,
  ok,
  warn,
}: {
  label: string;
  ok?: boolean;
  warn?: boolean;
}) {
  const tone = ok ? "is-ok" : warn ? "is-warn" : "is-off";
  return (
    <span className={`ts-badge ${tone}`}>
      <i />
      {label}
    </span>
  );
}

function DeskPanel({
  title,
  children,
  className = "",
  action,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <section className={`ts-panel ${className}`}>
      <header className="ts-panel-head">
        <span>{title}</span>
        {action}
      </header>
      <div className="ts-panel-body">{children}</div>
    </section>
  );
}

function EquityChart({
  equity,
  fills,
}: {
  equity: Array<{ equity: number; ts: string; bar_index?: number }>;
  fills: Array<{ bar_index: number; side: string }>;
}) {
  const chart = useMemo(() => {
    if (!equity.length) return null;
    const values = equity.map((p) => p.equity);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = (max - min) * 0.04 || Math.abs(max) * 0.01 || 1;
    const lo = min - pad;
    const hi = max + pad;
    const w = 1000;
    const h = 220;
    const step = w / Math.max(values.length - 1, 1);
    const y = (v: number) => ((hi - v) / (hi - lo || 1)) * h;
    const path = values.map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
    const area = `${path} L${w},${h} L0,${h} Z`;
    const barIndexToX = new Map(equity.map((p, i) => [p.bar_index ?? i, i * step]));
    const markers = fills
      .map((f) => {
        const x = barIndexToX.get(f.bar_index);
        if (x == null) return null;
        const idx = equity.findIndex((p) => (p.bar_index ?? -1) === f.bar_index);
        const eq = idx >= 0 ? equity[idx].equity : values[Math.min(values.length - 1, Math.round(x / step))];
        return { x, y: y(eq), side: f.side.toLowerCase() };
      })
      .filter(Boolean) as Array<{ x: number; y: number; side: string }>;
    return { path, area, min: lo, max: hi, markers, last: values[values.length - 1] };
  }, [equity, fills]);

  if (!chart) {
    return (
      <div className="ts-chart-empty">
        <strong>No equity curve yet</strong>
        <span>Create a multi-agent run and start the simulation to stream paper equity.</span>
      </div>
    );
  }

  return (
    <div className="ts-chart-live">
      <svg viewBox="0 0 1000 220" className="ts-chart" preserveAspectRatio="none">
        {[0.25, 0.5, 0.75].map((t) => (
          <line key={t} x1="0" x2="1000" y1={220 * t} y2={220 * t} className="ts-grid-line" />
        ))}
        <path d={chart.area} fill="rgba(33,174,247,0.08)" />
        <path d={chart.path} fill="none" stroke="#21aef7" strokeWidth="2" />
        {chart.markers.map((m, i) => (
          <circle
            key={`${m.x}-${i}`}
            cx={m.x}
            cy={m.y}
            r="4"
            fill={m.side.startsWith("b") || m.side === "buy" ? "#00e5b0" : "#ff535e"}
          />
        ))}
      </svg>
      <div className="ts-price-axis">
        <span>{fmtMoney(chart.max)}</span>
        <span className="current">{fmtMoney(chart.last)}</span>
        <span>{fmtMoney(chart.min)}</span>
      </div>
    </div>
  );
}

function ProgressBar({ index, total }: { index: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((index / total) * 100)) : 0;
  return (
    <div className="ts-progress-bar" title={`${index}/${total}`}>
      <i style={{ width: `${pct}%` }} />
      <span>
        {index}/{total || "—"} · {pct}%
      </span>
    </div>
  );
}

export function SimulatiePage() {
  const [status, setStatus] = useState<MarketSimStatusResponse | null>(null);
  const [runs, setRuns] = useState<MarketSimRun[]>([]);
  const [live, setLive] = useState<MarketSimLiveState | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sources, setSources] = useState<MarketDataSource[]>([]);
  const [strategies, setStrategies] = useState<MarketStrategy[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [strategyId, setStrategyId] = useState("");
  const [seed, setSeed] = useState(42);
  const [speed, setSpeed] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consoleTab, setConsoleTab] = useState<ConsoleTab>("activity");
  const selectedIdRef = useRef<string | null>(null);
  const sourceIdRef = useRef("");
  const strategyIdRef = useRef("");
  const pollInFlight = useRef(false);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);
  useEffect(() => {
    sourceIdRef.current = sourceId;
  }, [sourceId]);
  useEffect(() => {
    strategyIdRef.current = strategyId;
  }, [strategyId]);

  const refreshMeta = useCallback(async () => {
    try {
      const [st, runList, data, strat] = await Promise.all([
        api.marketSimStatus(),
        api.listMarketSimRuns(30).catch(() => ({ runs: [] as MarketSimRun[] })),
        api.listMarketData(50).catch(() => ({ sources: [] as MarketDataSource[] })),
        api.listMarketStrategies(50).catch(() => ({ strategies: [] as MarketStrategy[] })),
      ]);
      setStatus(st);
      setRuns(runList.runs);
      setSources(data.sources);
      setStrategies(strat.strategies);
      if (!selectedIdRef.current && runList.runs[0]) setSelectedId(runList.runs[0].run_id);
      if (!sourceIdRef.current && data.sources[0]) setSourceId(data.sources[0].source_id);
      if (!strategyIdRef.current && strat.strategies[0]) setStrategyId(strat.strategies[0].strategy_id);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refreshMeta();
    const id = window.setInterval(() => void refreshMeta(), 8000);
    return () => window.clearInterval(id);
  }, [refreshMeta]);

  useEffect(() => {
    if (!selectedId) {
      setLive(null);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      if (pollInFlight.current) return;
      pollInFlight.current = true;
      try {
        const state = await api.getMarketSimLive(selectedId);
        if (!cancelled) setLive(state);
      } catch {
        /* ignore transient poll errors */
      } finally {
        pollInFlight.current = false;
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [selectedId]);

  const run = live?.run ?? runs.find((r) => r.run_id === selectedId) ?? null;
  const wallets = ((run?.metadata as Record<string, unknown> | undefined)?.wallets as {
    wallets?: AgentWallet[];
  } | undefined)?.wallets ?? [];
  const fillAssumptions = ((run?.metadata as Record<string, unknown> | undefined)?.fill_assumptions as string[]) ?? [];
  const agents = (run?.agents as Array<Record<string, unknown>> | undefined) ?? [];
  const enabled = status?.enabled ?? false;
  const sourcesReady = sources.filter((s) => s.status === "READY").length;
  const selectedSource = sources.find((s) => s.source_id === sourceId) ?? null;
  const selectedStrategy = strategies.find((s) => s.strategy_id === strategyId) ?? null;
  const metrics = (run?.metrics ?? {}) as Record<string, unknown>;
  const messages = live?.messages ?? [];
  const fills = live?.fills ?? [];
  const equity = (live?.equity ?? []).map((p) => ({
    equity: Number(p.equity),
    ts: String(p.ts),
    bar_index: Number(p.bar_index),
  }));
  const decisions = messages.filter((m) => m.kind === "decision" || m.kind === "proposal");
  const lastMessagesByAgent = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of messages) {
      map.set(m.agent_id, m.content);
    }
    return map;
  }, [messages]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refreshMeta();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onSeedAndScan = async () => {
    await act(async () => {
      await api.scanMarketData();
      const ready = await api.listMarketData(50);
      setSources(ready.sources);
      if (ready.sources[0]) setSourceId(ready.sources[0].source_id);
    });
  };

  const onCreate = async () => {
    if (!sourceId) {
      setError("Select a READY market data source first — or seed fixtures via Scan / seed.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { run: created } = await api.createMarketSimRun({
        sourceId,
        strategyId: strategyId || undefined,
        seed,
        speed,
        deliberationEveryN: 3,
        gameMode: "individual_competition",
        metadata: { multi_agent: true, commit_reveal: true, multi_wallet: true },
        agents: [
          {
            agent_id: "agent-alpha",
            role: "market_analyst",
            label: "Alpha (trend)",
            parameters: { fast_ma: 8, slow_ma: 21, lookback: 30 },
            initial_cash: 50000,
            authority: { may_order: true },
          },
          {
            agent_id: "agent-beta",
            role: "strategy_researcher",
            label: "Beta (mean-reversion)",
            parameters: { lookback: 20, entry_z: -1.2, exit_z: 0.2 },
            entry_rules: { kind: "mean_reversion", entry_z: -1.2 },
            exit_rules: { kind: "mean_reversion", exit_z: 0.2 },
            initial_cash: 50000,
            authority: { may_order: true },
          },
          {
            agent_id: "agent-risk",
            role: "risk_agent",
            label: "Risk Officer",
            authority: { may_order: false, may_veto: true, veto_is_binding: true },
            initial_cash: 0,
          },
          {
            agent_id: "agent-orch",
            role: "trading_orchestrator",
            label: "Orchestrator",
            authority: { manages_task: true, may_order: false },
            initial_cash: 0,
          },
        ],
      });
      setSelectedId(created.run_id);
      await api.startMarketSimRun(created.run_id);
      await refreshMeta();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onDemo = async (family: "crypto_spot" | "equity") => {
    await act(async () => {
      const result = await api.runMarketDemo({ family, barsLimit: 80 });
      const runId = String((result.run as { run_id?: string } | undefined)?.run_id ?? "");
      if (runId) setSelectedId(runId);
    });
  };

  const agentRows = agents.length
    ? agents
    : wallets.map((w) => ({
        agent_id: w.owner_id,
        role: w.owner_kind ?? "agent",
        label: w.owner_id,
      }));

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Market Sim Mode"
      searchPlaceholder="Search runs, strategies, sources, agents..."
      systemItems={["PAPER ONLY", "CAUSAL FILLS", "MULTI-AGENT"]}
      layout="wide"
      pageClass="lv-app--trading lv-app--trading-sim-ref"
    >
      <main className="lv-main ts-main">
        <section className="ts-hero ts-hero-live">
          <img src={tradingHeroes.simulatie} alt="" />
          <div className="ts-hero-overlay" />
          <div className="ts-hero-copy">
            <p className="ts-kicker">LEVIATHAN · TRADING CENTER</p>
            <h1>MARKET SIMULATION</h1>
            <p className="ts-hero-kicker">BACKTEST. SIMULATE. OBSERVE.</p>
            <p>
              Causal multi-agent research desk — next-bar fills, commit-then-reveal, per-agent wallets.
              Paper only. OHLCV ≠ order book.
            </p>
          </div>
          <div className="ts-hero-badges">
            <StatusBadge label={enabled ? "Market sim ON" : "Market sim OFF"} ok={enabled} warn={!enabled} />
            <StatusBadge
              label={`${status?.active_runs ?? 0} agents/runs active`}
              ok={(status?.active_runs ?? 0) > 0}
            />
            <StatusBadge
              label={sourcesReady ? `${sourcesReady} source ready` : "No source ready"}
              ok={sourcesReady > 0}
              warn={sourcesReady === 0}
            />
            <StatusBadge
              label={selectedStrategy ? `Strategy: ${selectedStrategy.name}` : "No strategy"}
              ok={!!selectedStrategy}
            />
            <StatusBadge label={run?.status ? `Run ${run.status}` : "Idle"} ok={!!run} />
            <StatusBadge label="Paper only · no live money" ok />
          </div>
        </section>

        {!enabled && (
          <div className="ts-banner is-bad">
            Feature flag OFF — set LEVIATHAN_FEATURE_MARKET_SIM=true (default is ON for local/dev).
          </div>
        )}
        {error && <div className="ts-banner is-bad">{error}</div>}

        <div className="ts-controls ts-controls-live">
          <label>
            Source
            <select value={sourceId} onChange={(e) => setSourceId(e.target.value)} disabled={!enabled}>
              <option value="">—</option>
              {sources.map((s) => (
                <option key={s.source_id} value={s.source_id}>
                  {s.symbol} {s.timeframe} · {s.status} · {s.bar_count} bars
                </option>
              ))}
            </select>
          </label>
          <label>
            Strategy
            <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)} disabled={!enabled}>
              <option value="">— default MA cross —</option>
              {strategies.map((s) => (
                <option key={s.strategy_id} value={s.strategy_id}>
                  {s.name} · v{s.current_version}
                </option>
              ))}
            </select>
          </label>
          <label>
            Seed
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value) || 42)}
              disabled={!enabled || busy}
            />
          </label>
          <div className="ts-speed-row" aria-label="Simulation speed">
            {[1, 2, 5].map((s) => (
              <button
                key={s}
                type="button"
                className={speed === s ? "is-active" : ""}
                disabled={!enabled}
                onClick={() => setSpeed(s)}
              >
                {s}x
              </button>
            ))}
          </div>
          <div className="ts-control-divider" />
          <button type="button" disabled={!enabled || busy} onClick={() => void onSeedAndScan()}>
            Scan / seed data
          </button>
          <button type="button" className="ts-run-btn" disabled={!enabled || busy} onClick={() => void onCreate()}>
            New multi-agent run
          </button>
          <button
            type="button"
            disabled={!selectedId || busy}
            onClick={() => selectedId && void act(() => api.startMarketSimRun(selectedId))}
          >
            Start
          </button>
          <button
            type="button"
            disabled={!selectedId || busy}
            onClick={() => selectedId && void act(() => api.pauseMarketSimRun(selectedId))}
          >
            Pause
          </button>
          <button
            type="button"
            disabled={!selectedId || busy}
            onClick={() => selectedId && void act(() => api.stepMarketSimRun(selectedId))}
          >
            Step
          </button>
          <button
            type="button"
            disabled={!selectedId || busy}
            onClick={() => selectedId && void act(() => api.stopMarketSimRun(selectedId))}
          >
            Stop
          </button>
          <button type="button" disabled={!enabled || busy} onClick={() => void onDemo("crypto_spot")}>
            Demo BTC
          </button>
          <Link className="ts-link" to="/trading/strategieen">
            Strategies
          </Link>
          <Link className="ts-link" to="/trading/marktdata">
            Marktdata
          </Link>
        </div>

        <div className="ts-top-grid ts-top-grid-live">
          <DeskPanel
            title="Equity & progression"
            className="ts-chart-panel"
            action={
              <span className="ts-panel-meta">
                {run?.symbol ?? selectedSource?.symbol ?? "—"} · {run?.timeframe ?? selectedSource?.timeframe ?? "—"}
              </span>
            }
          >
            <div className="ts-chart-toolbar">
              <strong>{run?.symbol ?? "—"}</strong>
              <span className="ohlc">
                Equity <b>{run ? fmtMoney(run.equity) : "—"}</b>
              </span>
              <span className={Number(run?.realized_pnl ?? 0) >= 0 ? "gain" : "bad"}>
                Realized {run ? fmtMoney(run.realized_pnl) : "—"}
              </span>
              <span className="ts-chart-spacer" />
              <ProgressBar index={run?.bar_index ?? 0} total={run?.bar_count ?? 0} />
            </div>
            <EquityChart equity={equity} fills={fills} />
            {fillAssumptions.length > 0 && (
              <ul className="ts-assumptions">
                {fillAssumptions.slice(0, 4).map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            )}
          </DeskPanel>

          <DeskPanel title="Portfolio (paper)">
            <div className="ts-portfolio-top">
              <div>
                <span>Marked equity</span>
                <strong>{run ? fmtMoney(run.equity) : "—"}</strong>
                <b>{metricValue(metrics, "total_return")}</b>
              </div>
              <div>
                <span>Cash</span>
                <strong>{run ? fmtMoney(run.cash) : "—"}</strong>
                <b className="muted">pos {run?.position_qty ?? "—"}</b>
              </div>
            </div>
            <div className="ts-stat-strip">
              <div>
                <span>Win rate</span>
                <b>{metricValue(metrics, "win_rate")}</b>
              </div>
              <div>
                <span>Max DD</span>
                <b className="bad">{metricValue(metrics, "max_drawdown")}</b>
              </div>
              <div>
                <span>Sharpe</span>
                <b>{metricValue(metrics, "sharpe")}</b>
              </div>
            </div>
            <div className="ts-stat-strip">
              <div>
                <span>Fees</span>
                <b>{metricValue(metrics, "fees_paid")}</b>
              </div>
              <div>
                <span>Turnover</span>
                <b>{metricValue(metrics, "turnover")}</b>
              </div>
              <div>
                <span>Trades</span>
                <b>{fills.length || "—"}</b>
              </div>
            </div>
            <div className="ts-mini-equity">
              <EquityChart equity={equity.slice(-60)} fills={[]} />
            </div>
          </DeskPanel>

          <DeskPanel title="Run control">
            <div className="ts-run-meta">
              <div>
                <span>Selected run</span>
                <b>{selectedId ? selectedId.slice(0, 8) : "—"}</b>
              </div>
              <div>
                <span>Status</span>
                <b>{run?.status ?? "idle"}</b>
              </div>
              <div>
                <span>Causal clock</span>
                <b>{run?.clock_ts ?? "—"}</b>
              </div>
              <div>
                <span>Seed / speed</span>
                <b>
                  {run?.seed ?? seed} · {run?.speed ?? speed}x
                </b>
              </div>
              <div>
                <span>Causality violations</span>
                <b className={run && run.causality_violations > 0 ? "bad" : "good"}>
                  {run?.causality_violations ?? 0}
                </b>
              </div>
              <div>
                <span>Brain hits / misses</span>
                <b>
                  {run?.brain_hits ?? 0} / {run?.brain_misses ?? 0}
                </b>
              </div>
              <div>
                <span>Worker</span>
                <b>{String(status?.worker?.worker_mode ?? "—")}</b>
              </div>
              <div>
                <span>Source</span>
                <b>
                  {selectedSource
                    ? `${selectedSource.symbol} (${selectedSource.status})`
                    : run?.source_id?.slice(0, 8) ?? "—"}
                </b>
              </div>
            </div>
            <p className="ts-muted ts-pad">
              Agents trade autonomously on historical OHLCV with next-bar-open fills. Not live money.
            </p>
          </DeskPanel>
        </div>

        <div className="ts-mid-grid ts-mid-grid-live">
          <DeskPanel
            title="Strategy"
            action={
              <Link className="ts-link" to="/trading/strategieen">
                Open builder
              </Link>
            }
          >
            {selectedStrategy || run?.strategy_id ? (
              <div className="ts-strategy-card">
                <strong>{selectedStrategy?.name ?? "Attached strategy"}</strong>
                <span>
                  {selectedStrategy
                    ? `v${selectedStrategy.current_version} · ${selectedStrategy.status}`
                    : `id ${run?.strategy_id?.slice(0, 8)} · v${run?.strategy_version ?? "—"}`}
                </span>
                <p>{selectedStrategy?.description || "Sandboxed DSL — ma_cross / mean_reversion."}</p>
                <div className="ts-tag-row">
                  {(selectedStrategy?.tags ?? ["paper"]).map((t) => (
                    <em key={t}>{t}</em>
                  ))}
                </div>
              </div>
            ) : (
              <div className="ts-muted ts-pad">No strategy selected — run will use default MA cross parameters.</div>
            )}
          </DeskPanel>

          <DeskPanel title="Agents">
            <div className="ts-agent-head">
              <span />
              <span>Agent</span>
              <span>Role</span>
              <span>Last action</span>
              <span>Pos</span>
              <span>Eq</span>
            </div>
            <div className="ts-agent-scroll">
              {agentRows.map((a) => {
                const id = String(a.agent_id ?? a.label ?? "agent");
                const role = String(a.role ?? "—");
                const wallet = wallets.find((w) => w.owner_id === id);
                return (
                  <div className="ts-agent-row" key={id}>
                    <span className={`agent-icon ${role.includes("risk") ? "risk" : role.includes("orch") ? "exec" : "strategy"}`}>
                      ●
                    </span>
                    <b>{String(a.label ?? id)}</b>
                    <span>{role}</span>
                    <span title={lastMessagesByAgent.get(id)}>{(lastMessagesByAgent.get(id) ?? "—").slice(0, 42)}</span>
                    <span>{wallet?.position_qty ?? "—"}</span>
                    <span>{wallet?.equity != null ? fmtMoney(Number(wallet.equity)) : "—"}</span>
                  </div>
                );
              })}
              {!agentRows.length && <div className="ts-muted ts-pad">Agents appear when a multi-agent run is created.</div>}
            </div>
          </DeskPanel>

          <DeskPanel title="Observability">
            <div className="ts-tabs ts-tabs-bar">
              {(["activity", "messages", "fills", "wallets", "decisions"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  className={consoleTab === t ? "is-active" : ""}
                  onClick={() => setConsoleTab(t)}
                >
                  {t}
                </button>
              ))}
            </div>
            <ul className="ts-log">
              {consoleTab === "activity" &&
                [...messages, ...fills.map((f) => ({
                  message_id: f.fill_id,
                  ts: f.ts,
                  agent_id: f.agent_id ?? "fill",
                  kind: "fill",
                  content: `${f.side} ${f.qty} @ ${f.price} (${f.status})`,
                }))]
                  .sort((a, b) => String(b.ts).localeCompare(String(a.ts)))
                  .slice(0, 60)
                  .map((m) => (
                    <li key={String(m.message_id)}>
                      <span>{String(m.ts).slice(11, 19)}</span> <strong>{m.agent_id}</strong> [{m.kind}] {m.content}
                    </li>
                  ))}
              {consoleTab === "messages" &&
                [...messages].reverse().slice(0, 60).map((m) => (
                  <li key={m.message_id}>
                    <span>{m.ts.slice(11, 19)}</span> <strong>{m.agent_id}</strong> [{m.kind}] {m.content}
                  </li>
                ))}
              {consoleTab === "fills" &&
                [...fills].reverse().slice(0, 60).map((f) => (
                  <li key={f.fill_id}>
                    <span>{f.ts.slice(11, 19)}</span> {f.agent_id} {f.side} {f.qty} @ {f.price} · fee {f.fee}
                  </li>
                ))}
              {consoleTab === "wallets" &&
                wallets.map((w) => (
                  <li key={String(w.wallet_id ?? w.owner_id)}>
                    <strong>{String(w.owner_id)}</strong> ({String(w.owner_kind)}) cash={fmtMoney(Number(w.cash))} pos=
                    {String(w.position_qty)} equity={fmtMoney(Number(w.equity))}
                  </li>
                ))}
              {consoleTab === "decisions" &&
                [...decisions].reverse().slice(0, 60).map((m) => (
                  <li key={m.message_id}>
                    <span>{m.ts.slice(11, 19)}</span> <strong>{m.agent_id}</strong> [{m.kind}] conf=
                    {m.confidence.toFixed(2)} — {m.content}
                  </li>
                ))}
              {consoleTab === "activity" && !messages.length && !fills.length && (
                <li className="ts-muted">No agent activity yet — start a run.</li>
              )}
              {consoleTab === "messages" && !messages.length && (
                <li className="ts-muted">No deliberation / commit messages yet.</li>
              )}
              {consoleTab === "fills" && !fills.length && (
                <li className="ts-muted">No fills yet (decisions fill next bar open).</li>
              )}
              {consoleTab === "wallets" && !wallets.length && (
                <li className="ts-muted">Wallets appear on multi-agent competition runs.</li>
              )}
              {consoleTab === "decisions" && !decisions.length && (
                <li className="ts-muted">No proposals/decisions recorded yet.</li>
              )}
            </ul>
          </DeskPanel>

          <DeskPanel title="Market data">
            <ul className="ts-list">
              {sources.slice(0, 8).map((s) => (
                <li key={s.source_id}>
                  <button
                    type="button"
                    className={s.source_id === sourceId ? "is-active" : ""}
                    onClick={() => setSourceId(s.source_id)}
                  >
                    <strong>
                      {s.symbol} · {s.timeframe}
                    </strong>
                    <span>
                      {s.status} · {s.bar_count} bars · {s.start_ts?.slice(0, 10)} → {s.end_ts?.slice(0, 10)}
                    </span>
                  </button>
                </li>
              ))}
              {!sources.length && (
                <li className="ts-muted">
                  No sources indexed. Click <em>Scan / seed data</em> to load built-in BTC/AAPL fixtures.
                </li>
              )}
            </ul>
          </DeskPanel>
        </div>

        <div className="ts-bottom-grid ts-bottom-grid-live">
          <DeskPanel title="Run history">
            <ul className="ts-list">
              {runs.map((r) => (
                <li key={r.run_id}>
                  <button
                    type="button"
                    className={r.run_id === selectedId ? "is-active" : ""}
                    onClick={() => setSelectedId(r.run_id)}
                  >
                    <strong>
                      {r.symbol} · {r.status}
                    </strong>
                    <span>
                      {r.run_id.slice(0, 8)} · bar {r.bar_index}/{r.bar_count} · eq {fmtMoney(r.equity)} ·{" "}
                      {r.created_at?.slice(0, 19)}
                    </span>
                  </button>
                </li>
              ))}
              {!runs.length && <li className="ts-muted">No runs yet — create a multi-agent run above.</li>}
            </ul>
          </DeskPanel>

          <DeskPanel title="Positions / fills">
            <div className="ts-positions">
              <table>
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Price</th>
                    <th>Bar</th>
                  </tr>
                </thead>
                <tbody>
                  {[...fills].reverse().slice(0, 12).map((f) => (
                    <tr key={f.fill_id}>
                      <td>{f.agent_id ?? "—"}</td>
                      <td>
                        <span className={`side ${f.side.toLowerCase().includes("sell") ? "short" : "long"}`}>
                          {f.side}
                        </span>
                      </td>
                      <td>{f.qty}</td>
                      <td>{f.price}</td>
                      <td>{f.bar_index}</td>
                    </tr>
                  ))}
                  {!fills.length && (
                    <tr>
                      <td colSpan={5} className="ts-muted">
                        Open fills stream here after agents decide.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </DeskPanel>

          <DeskPanel title="Health">
            <div className="ts-run-meta">
              <div>
                <span>Markets root</span>
                <b>{status?.health?.markets_root ? "configured" : "—"}</b>
              </div>
              <div>
                <span>Sources indexed</span>
                <b>{status?.health?.sources_indexed ?? 0}</b>
              </div>
              <div>
                <span>Sources ready</span>
                <b>{status?.health?.sources_ready ?? 0}</b>
              </div>
              <div>
                <span>Active runs</span>
                <b>{status?.active_runs ?? 0}</b>
              </div>
              <div>
                <span>Live trading</span>
                <b className="bad">BLOCKED</b>
              </div>
            </div>
          </DeskPanel>
        </div>

        <p className="ts-footnote">
          Worker: {String(status?.worker?.worker_mode ?? "—")} · slices {String(status?.worker?.slices ?? 0)} ·
          paper only · live trading blocked · KPIs show UNMEASURED when not computed
        </p>
      </main>
    </AppShell>
  );
}
