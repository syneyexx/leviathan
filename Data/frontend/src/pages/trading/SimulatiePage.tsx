import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { MarketSimLiveState, MarketSimRun, MarketSimStatusResponse } from "../../types/api";
import { media } from "../../assets/media";
import { AppShell } from "../../layouts/AppShell";
import { fmtMoney, metricValue } from "./shared";
import "../../styles/trading-simulation-reference.css";

function Icon({ type }: { type: string }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (type === "agents") return <svg viewBox="0 0 24 24" {...common}><circle cx="9" cy="8" r="3"/><path d="M3.5 19c.6-3.2 2.4-5 5.5-5s4.9 1.8 5.5 5"/><circle cx="17.5" cy="9" r="2.2"/><path d="M15.5 14.5c2.9-.7 4.6.8 5 3.5"/></svg>;
  if (type === "capital" || type === "data") return <svg viewBox="0 0 24 24" {...common}><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>;
  if (type === "positions") return <svg viewBox="0 0 24 24" {...common}><path d="M4 19V9M10 19V5M16 19v-7M3 18l5-5 4 2 7-8"/><path d="M16 7h3v3"/></svg>;
  if (type === "win") return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="m12 12 6-6"/></svg>;
  if (type === "time") return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/></svg>;
  if (type === "sync") return <svg viewBox="0 0 24 24" {...common}><path d="M20 8a8 8 0 0 0-13.5-2L4 8"/><path d="M4 4v4h4M4 16a8 8 0 0 0 13.5 2L20 16"/><path d="M20 20v-4h-4"/></svg>;
  return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="12" r="8"/></svg>;
}

function Panel({ title, children, className = "", action }: { title: string; children: ReactNode; className?: string; action?: ReactNode }) {
  return <section className={`ts-panel ${className}`}><header className="ts-panel-head"><span>{title}</span>{action}</header><div className="ts-panel-body">{children}</div></section>;
}

function EquityChart({ equity }: { equity: Array<{ equity: number; ts: string }> }) {
  const chart = useMemo(() => {
    if (!equity.length) return null;
    const values = equity.map((p) => p.equity);
    const min = Math.min(...values) * 0.995;
    const max = Math.max(...values) * 1.005;
    const w = 1000;
    const h = 282;
    const step = w / Math.max(values.length - 1, 1);
    const y = (v: number) => ((max - v) / (max - min || 1)) * h;
    const path = values.map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
    return { path, min, max };
  }, [equity]);
  if (!chart) {
    return <div className="ts-muted">No equity curve yet — start a run.</div>;
  }
  return (
    <svg viewBox="0 0 1000 282" className="ts-chart" preserveAspectRatio="none">
      <path d={chart.path} fill="none" stroke="var(--lv-gold, #c9a227)" strokeWidth="2.5" />
    </svg>
  );
}

export function SimulatiePage() {
  const [status, setStatus] = useState<MarketSimStatusResponse | null>(null);
  const [runs, setRuns] = useState<MarketSimRun[]>([]);
  const [live, setLive] = useState<MarketSimLiveState | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sources, setSources] = useState<Array<{ source_id: string; symbol: string; timeframe: string; status: string }>>([]);
  const [strategies, setStrategies] = useState<Array<{ strategy_id: string; name: string }>>([]);
  const [sourceId, setSourceId] = useState("");
  const [strategyId, setStrategyId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consoleTab, setConsoleTab] = useState<"messages" | "fills" | "wallets">("messages");

  const refreshMeta = useCallback(async () => {
    try {
      const [st, runList, data, strat] = await Promise.all([
        api.marketSimStatus(),
        api.listMarketSimRuns(20),
        api.listMarketData(50).catch(() => ({ sources: [] })),
        api.listMarketStrategies(50).catch(() => ({ strategies: [] })),
      ]);
      setStatus(st);
      setRuns(runList.runs);
      setSources(data.sources);
      setStrategies(strat.strategies);
      if (!selectedId && runList.runs[0]) setSelectedId(runList.runs[0].run_id);
      if (!sourceId && data.sources[0]) setSourceId(data.sources[0].source_id);
      if (!strategyId && strat.strategies[0]) setStrategyId(strat.strategies[0].strategy_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedId, sourceId, strategyId]);

  useEffect(() => {
    void refreshMeta();
  }, [refreshMeta]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const state = await api.getMarketSimLive(selectedId);
        if (!cancelled) setLive(state);
      } catch {
        /* ignore poll errors */
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
    wallets?: Array<Record<string, unknown>>;
  } | undefined)?.wallets ?? [];
  const fillAssumptions = ((run?.metadata as Record<string, unknown> | undefined)?.fill_assumptions as string[]) ?? [];

  const onCreate = async () => {
    if (!sourceId) {
      setError("Select a market data source first (Marktdata).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { run: created } = await api.createMarketSimRun({
        sourceId,
        strategyId: strategyId || undefined,
        seed: 42,
        deliberationEveryN: 3,
        gameMode: "individual_competition",
        metadata: { multi_agent: true, commit_reveal: true, multi_wallet: true },
        agents: [
          { agent_id: "agent-alpha", role: "market_analyst", parameters: { fast_ma: 8, slow_ma: 21 }, initial_cash: 50000 },
          { agent_id: "agent-beta", role: "strategy_researcher", entry_rules: { kind: "mean_reversion" }, exit_rules: { kind: "mean_reversion" }, initial_cash: 50000 },
          { agent_id: "agent-risk", role: "risk_agent", authority: { may_order: false, may_veto: true } },
          { agent_id: "agent-orch", role: "trading_orchestrator", authority: { manages_task: true } },
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

  const enabled = status?.enabled ?? false;
  const kpis = [
    ["agents", String((run?.agents as unknown[] | undefined)?.length ?? 0), "Agents in run"],
    ["capital", run ? fmtMoney(run.equity) : "—", "Marked equity"],
    ["positions", run ? String(run.position_qty) : "—", "Net position qty"],
    ["win", metricValue(run?.metrics as Record<string, unknown> | undefined, "win_rate"), "Win rate"],
    ["data", run?.symbol ?? "—", "Symbol"],
    ["time", run?.clock_ts ?? "—", "Causal clock"],
    ["sync", run?.status ?? (enabled ? "idle" : "flag off"), "Run status"],
  ] as const;

  return (
    <AppShell layout="wide" pageClass="lv-app--trading lv-app--trading-sim-ref">
      <div className="ts-hero" style={{ backgroundImage: `url(${media.architectureBg})` }}>
        <div className="ts-hero-copy">
          <p className="ts-kicker">LEVIATHAN · TRADING CENTER</p>
          <h1>Market simulation</h1>
          <p>
            Causal multi-agent research desk. Next-bar fills, commit-then-reveal, per-agent wallets.
            Not live money. OHLCV ≠ order book.
          </p>
        </div>
      </div>

      {!enabled && (
        <div className="ts-banner">Feature flag OFF — set LEVIATHAN_FEATURE_MARKET_SIM=true</div>
      )}
      {error && <div className="ts-banner is-bad">{error}</div>}

      <div className="ts-kpi-row">
        {kpis.map(([type, value, label]) => (
          <div className="ts-kpi" key={type}>
            <Icon type={type} />
            <div>
              <strong>{value}</strong>
              <span>{label}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="ts-toolbar">
        <label>
          Source
          <select value={sourceId} onChange={(e) => setSourceId(e.target.value)} disabled={!enabled}>
            <option value="">—</option>
            {sources.map((s) => (
              <option key={s.source_id} value={s.source_id}>
                {s.symbol} {s.timeframe} ({s.status})
              </option>
            ))}
          </select>
        </label>
        <label>
          Strategy
          <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)} disabled={!enabled}>
            <option value="">—</option>
            {strategies.map((s) => (
              <option key={s.strategy_id} value={s.strategy_id}>{s.name}</option>
            ))}
          </select>
        </label>
        <button type="button" disabled={!enabled || busy} onClick={() => void onCreate()}>New multi-agent run</button>
        <button type="button" disabled={!selectedId || busy} onClick={() => selectedId && void act(() => api.startMarketSimRun(selectedId))}>Start</button>
        <button type="button" disabled={!selectedId || busy} onClick={() => selectedId && void act(() => api.pauseMarketSimRun(selectedId))}>Pause</button>
        <button type="button" disabled={!selectedId || busy} onClick={() => selectedId && void act(() => api.stepMarketSimRun(selectedId))}>Step</button>
        <button type="button" disabled={!selectedId || busy} onClick={() => selectedId && void act(() => api.stopMarketSimRun(selectedId))}>Stop</button>
        <Link className="ts-link" to="/agents">Agents fleet</Link>
        <Link className="ts-link" to="/trading/marktdata">Marktdata</Link>
      </div>

      <div className="ts-grid">
        <Panel title="Equity (paper sim)" className="ts-span-2">
          <EquityChart equity={(live?.equity ?? []).map((p) => ({ equity: Number(p.equity), ts: String(p.ts) }))} />
          {fillAssumptions.length > 0 && (
            <ul className="ts-assumptions">
              {fillAssumptions.map((a) => <li key={a}>{a}</li>)}
            </ul>
          )}
        </Panel>

        <Panel title="Runs">
          <ul className="ts-list">
            {runs.map((r) => (
              <li key={r.run_id}>
                <button type="button" className={r.run_id === selectedId ? "is-active" : ""} onClick={() => setSelectedId(r.run_id)}>
                  <strong>{r.symbol}</strong> · {r.status}
                  <span>{r.run_id.slice(0, 8)} · bar {r.bar_index}/{r.bar_count}</span>
                </button>
              </li>
            ))}
            {!runs.length && <li className="ts-muted">No runs yet</li>}
          </ul>
        </Panel>

        <Panel
          title="Agent activity"
          action={
            <div className="ts-tabs">
              {(["messages", "fills", "wallets"] as const).map((t) => (
                <button key={t} type="button" className={consoleTab === t ? "is-active" : ""} onClick={() => setConsoleTab(t)}>{t}</button>
              ))}
            </div>
          }
        >
          {consoleTab === "messages" && (
            <ul className="ts-log">
              {(live?.messages ?? []).slice(-40).reverse().map((m) => (
                <li key={m.message_id}>
                  <span>{m.ts}</span> <strong>{m.agent_id}</strong> [{m.kind}] {m.content}
                </li>
              ))}
              {!live?.messages?.length && <li className="ts-muted">No deliberation / commit messages</li>}
            </ul>
          )}
          {consoleTab === "fills" && (
            <ul className="ts-log">
              {(live?.fills ?? []).slice(-40).reverse().map((f) => (
                <li key={f.fill_id}>
                  <span>{f.ts}</span> {f.agent_id} {f.side} {f.qty} @ {f.price} ({f.status})
                </li>
              ))}
              {!live?.fills?.length && <li className="ts-muted">No fills yet (decisions fill next bar open)</li>}
            </ul>
          )}
          {consoleTab === "wallets" && (
            <ul className="ts-log">
              {wallets.map((w) => (
                <li key={String(w.wallet_id)}>
                  <strong>{String(w.owner_id)}</strong> ({String(w.owner_kind)}) cash={String(w.cash)} pos={String(w.position_qty)} equity={String(w.equity)}
                </li>
              ))}
              {!wallets.length && <li className="ts-muted">Wallets appear on multi-agent competition runs</li>}
            </ul>
          )}
        </Panel>
      </div>

      <p className="ts-footnote">
        Worker: {String(status?.worker?.worker_mode ?? "—")} · causality violations: {run?.causality_violations ?? 0} ·
        paper only · live trading blocked
      </p>
    </AppShell>
  );
}
