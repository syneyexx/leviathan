import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import type {
  PaperPortfolio,
  PortfolioDashboard,
  PortfolioRecommendation,
  TradeOrchestra,
} from "../../types/api";
import { Donut, fmtMoney } from "./shared";
import "../../styles/trading-portefeuille.css";

const RANGES = ["1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"] as const;
const ALLOC_COLORS = ["#22d3ee", "#34d399", "#e8c547", "#a78bfa", "#f87171", "#60a5fa", "#fb923c", "#94a3b8"];

function num(v: string | number | null | undefined): number {
  if (v == null || v === "") return 0;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function fmtMetric(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

function relativeSync(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)} min ago`;
  return `${Math.round(sec / 3600)}h ago`;
}

function EquityChart({
  series,
  width = 720,
  height = 220,
}: {
  series: Array<{ timestamp?: string; equity?: string }>;
  width?: number;
  height?: number;
}) {
  const values = series.map((p) => num(p.equity));
  if (values.length < 2) {
    return (
      <div className="lv-portefeuille-state" style={{ minHeight: height, padding: 24 }}>
        <p className="is-muted">Insufficient equity history for chart — trade to build the curve.</p>
      </div>
    );
  }
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const pad = 12;
  const coords = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (width - pad * 2);
    const y = height - pad - ((v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width - pad},${height - pad} L${pad},${height - pad} Z`;
  const gridYs = [0.25, 0.5, 0.75].map((f) => pad + f * (height - pad * 2));
  return (
    <svg className="lv-portefeuille-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {gridYs.map((y) => (
        <line key={y} x1={pad} x2={width - pad} y1={y} y2={y} stroke="rgba(148,163,184,0.12)" strokeWidth="1" />
      ))}
      <path d={area} fill="url(#pfEquityFill)" opacity="0.9" />
      <path d={line} fill="none" stroke="#22d3ee" strokeWidth="2" strokeLinejoin="round" />
      <defs>
        <linearGradient id="pfEquityFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function CreateModal({
  open,
  orchestras,
  busy,
  onClose,
  onCreate,
}: {
  open: boolean;
  orchestras: TradeOrchestra[];
  busy: boolean;
  onClose: () => void;
  onCreate: (payload: {
    name: string;
    initialEquity: number;
    orchestraId: string | null;
    shortingEnabled: boolean;
  }) => void;
}) {
  const [name, setName] = useState("Paper Portefeuille");
  const [capital, setCapital] = useState("100000");
  const [orchestraId, setOrchestraId] = useState("");
  const [shorting, setShorting] = useState(false);
  if (!open) return null;
  return (
    <div className="lv-portefeuille-modal-backdrop" role="dialog" aria-modal="true">
      <div className="lv-portefeuille-modal">
        <h3>Create Paper Portefeuille</h3>
        <p className="is-muted" style={{ marginTop: 0, fontSize: 12 }}>
          Virtual / simulated capital only. Live broker trading remains blocked.
        </p>
        <div className="lv-portefeuille-form">
          <label>
            Name
            <input className="lv-portefeuille-input" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Initial paper capital (USD)
            <input className="lv-portefeuille-input" value={capital} onChange={(e) => setCapital(e.target.value)} />
          </label>
          <label>
            Trade Orchestra
            <select
              className="lv-portefeuille-select"
              value={orchestraId}
              onChange={(e) => setOrchestraId(e.target.value)}
            >
              <option value="">Manual-only (no orchestra)</option>
              {orchestras.map((o) => (
                <option key={o.orchestraId} value={o.orchestraId}>
                  {o.name || o.orchestraId}
                </option>
              ))}
            </select>
          </label>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 8, textTransform: "none" }}>
            <input type="checkbox" checked={shorting} onChange={(e) => setShorting(e.target.checked)} />
            Enable paper shorting
          </label>
          <div className="lv-portefeuille-actions">
            <button type="button" className="lv-portefeuille-btn" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button
              type="button"
              className="lv-portefeuille-btn is-primary"
              disabled={busy || !name.trim()}
              onClick={() =>
                onCreate({
                  name: name.trim(),
                  initialEquity: Math.max(1, Number(capital) || 100000),
                  orchestraId: orchestraId || null,
                  shortingEnabled: shorting,
                })
              }
            >
              Create
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function AnalysisModal({
  open,
  dash,
  onClose,
}: {
  open: boolean;
  dash: PortfolioDashboard | null;
  onClose: () => void;
}) {
  if (!open || !dash) return null;
  return (
    <div className="lv-portefeuille-modal-backdrop" role="dialog" aria-modal="true">
      <div className="lv-portefeuille-modal" style={{ width: "min(640px, 100%)" }}>
        <h3>Detailed analysis</h3>
        <div className="lv-portefeuille-metric-list">
          <li><span>Equity</span><strong>{fmtMoney(num(dash.kpis.total_equity))}</strong></li>
          <li><span>Cash</span><strong>{fmtMoney(num(dash.kpis.cash_balance))}</strong></li>
          <li><span>Realized PnL</span><strong>{fmtMoney(num(dash.kpis.realized_pnl))}</strong></li>
          <li><span>Unrealized PnL</span><strong>{fmtMoney(num(dash.kpis.unrealized_pnl))}</strong></li>
          <li><span>Sharpe</span><strong>{fmtMetric(dash.risk.sharpe)}</strong></li>
          <li><span>Sortino</span><strong>{fmtMetric(dash.risk.sortino)}</strong></li>
          <li><span>Max drawdown</span><strong>{fmtPct(dash.risk.max_drawdown)}</strong></li>
          <li><span>Volatility</span><strong>{fmtPct(dash.risk.volatility)}</strong></li>
          <li><span>Beta</span><strong>{fmtMetric(dash.risk.beta)}</strong></li>
          <li><span>VaR 1D 95%</span><strong>{fmtPct(dash.risk.var_1d_95)}</strong></li>
          <li><span>Health</span><strong>{dash.risk.health.score} ({dash.risk.health.label})</strong></li>
          <li><span>Leverage</span><strong>{fmtMetric(dash.exposure.leverage)}x</strong></li>
          <li><span>Gross exposure</span><strong>{fmtPct(dash.exposure.gross_exposure_pct)}</strong></li>
        </div>
        <div className="lv-portefeuille-actions">
          <button type="button" className="lv-portefeuille-btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export function PortefeuillePage() {
  const toast = useAppToast();
  const [portfolios, setPortfolios] = useState<PaperPortfolio[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [dash, setDash] = useState<PortfolioDashboard | null>(null);
  const [range, setRange] = useState<(typeof RANGES)[number]>("YTD");
  const [allocTab, setAllocTab] = useState<"asset" | "sector" | "geography">("asset");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [disabled, setDisabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [orchestras, setOrchestras] = useState<TradeOrchestra[]>([]);
  const [search, setSearch] = useState("");
  const [selectedPositions, setSelectedPositions] = useState<string[]>([]);
  const [sideFilter, setSideFilter] = useState("ALL");
  const inFlight = useRef(false);
  const hidden = useRef(false);

  const loadList = useCallback(async () => {
    try {
      const st = await api.marketSimStatus();
      if (!st.enabled) {
        setDisabled(true);
        setPortfolios([]);
        setError("Market sim is OFF (LEVIATHAN_FEATURE_MARKET_SIM).");
        return;
      }
      setDisabled(false);
      const [{ portfolios: list }, orch] = await Promise.all([
        api.listPortfolios(50),
        api.listTradeOrchestras().catch(() => ({ orchestras: [] as TradeOrchestra[] })),
      ]);
      setPortfolios(list);
      setOrchestras(orch.orchestras || []);
      setSelectedId((prev) => prev || list[0]?.portfolio_id || "");
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load Portefeuille");
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshDash = useCallback(async () => {
    if (!selectedId || inFlight.current || hidden.current) return;
    inFlight.current = true;
    try {
      const d = await api.portfolioDashboard(selectedId, range);
      setDash(d);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Dashboard refresh failed");
    } finally {
      inFlight.current = false;
    }
  }, [selectedId, range]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (!selectedId) {
      setDash(null);
      return;
    }
    void refreshDash();
  }, [selectedId, refreshDash]);

  useEffect(() => {
    const onVis = () => {
      hidden.current = document.hidden;
      if (!document.hidden) void refreshDash();
    };
    document.addEventListener("visibilitychange", onVis);
    const id = window.setInterval(() => {
      if (!document.hidden) void refreshDash();
    }, 3500);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.clearInterval(id);
    };
  }, [refreshDash]);

  const positions = useMemo(() => {
    const rows = dash?.positions || [];
    return rows.filter((p) => {
      if (sideFilter !== "ALL" && p.side !== sideFilter) return false;
      if (!search.trim()) return true;
      const q = search.trim().toLowerCase();
      return (
        p.symbol.toLowerCase().includes(q) ||
        (p.strategy_id || "").toLowerCase().includes(q) ||
        (p.display_name || "").toLowerCase().includes(q)
      );
    });
  }, [dash, search, sideFilter]);

  async function createPortfolio(payload: {
    name: string;
    initialEquity: number;
    orchestraId: string | null;
    shortingEnabled: boolean;
  }) {
    setBusy(true);
    try {
      const { portfolio } = await api.createPortfolio({
        name: payload.name,
        initialEquity: payload.initialEquity,
        orchestraId: payload.orchestraId,
        shortingEnabled: payload.shortingEnabled,
        allowManualOnly: true,
        settings: {
          allow_manual_only: true,
          fee_bps: 5,
          slippage_bps: 2,
          shorting_enabled: payload.shortingEnabled,
        },
      });
      toast(`Created ${portfolio.name}`);
      setCreateOpen(false);
      setSelectedId(portfolio.portfolio_id);
      await loadList();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function lifecycle(action: "start" | "pause" | "resume" | "stop") {
    if (!selectedId) return;
    setBusy(true);
    try {
      const fn =
        action === "start"
          ? api.startPortfolio
          : action === "pause"
            ? api.pausePortfolio
            : action === "resume"
              ? api.resumePortfolio
              : api.stopPortfolio;
      await fn(selectedId);
      toast(`Portefeuille ${action}`);
      await refreshDash();
      await loadList();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : `${action} failed`);
    } finally {
      setBusy(false);
    }
  }

  async function closeSelected() {
    if (!selectedId || !selectedPositions.length) return;
    if (!window.confirm(`Close ${selectedPositions.length} paper position(s)?`)) return;
    setBusy(true);
    try {
      await api.closeSelectedPortfolioPositions(selectedId, selectedPositions);
      toast("Close orders submitted");
      setSelectedPositions([]);
      await refreshDash();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Close failed");
    } finally {
      setBusy(false);
    }
  }

  async function closeOne(positionId: string) {
    if (!selectedId) return;
    if (!window.confirm("Close this paper position?")) return;
    setBusy(true);
    try {
      await api.closePortfolioPosition(selectedId, positionId);
      toast("Close order submitted");
      await refreshDash();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Close failed");
    } finally {
      setBusy(false);
    }
  }

  async function runRecommendation(rec: PortfolioRecommendation) {
    if (!selectedId) return;
    if (rec.type === "PAUSE_AGENT") {
      toast("Pause agent via Agent Fleet — recommendation noted");
      return;
    }
    if (!rec.estimated_orders?.length) {
      toast("No executable paper orders for this recommendation");
      return;
    }
    if (!window.confirm(`Execute paper rebalance for: ${rec.reason}?`)) return;
    setBusy(true);
    try {
      await api.portfolioRebalanceExecute(selectedId, rec.estimated_orders);
      toast("Rebalance executed (paper)");
      await refreshDash();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Rebalance failed");
    } finally {
      setBusy(false);
    }
  }

  async function executeAll() {
    if (!selectedId || !dash?.recommendations.length) return;
    if (!window.confirm("Execute all pending PAPER rebalance recommendations?")) return;
    setBusy(true);
    try {
      await api.portfolioRebalanceExecute(selectedId);
      toast("Execute All completed (paper)");
      await refreshDash();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Execute All failed");
    } finally {
      setBusy(false);
    }
  }

  async function exportReport(format: "json" | "csv") {
    if (!selectedId) return;
    try {
      const res = await api.exportPortfolio(selectedId, format);
      const content = res.content;
      const blob =
        format === "csv"
          ? new Blob([String(content)], { type: "text/csv" })
          : new Blob([JSON.stringify(content, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = String(res.filename || `portefeuille.${format}`);
      a.click();
      URL.revokeObjectURL(url);
      toast(`Exported ${format.toUpperCase()}`);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Export failed");
    }
  }

  async function saveAllocation() {
    if (!selectedId || !dash) return;
    const allocations = (dash.strategy_allocation || []).map((s) => ({
      kind: "strategy",
      target_id: s.strategy_id,
      target_allocation_pct: s.allocation_pct,
      strategy_version: s.strategy_version,
      agent_id: s.agent_id,
      active: s.status === "ACTIVE",
    }));
    setBusy(true);
    try {
      await api.savePortfolioAllocations(selectedId, allocations);
      toast("Allocations saved");
      await refreshDash();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  const kpis = dash?.kpis;
  const status = dash?.portfolio.status || portfolios.find((p) => p.portfolio_id === selectedId)?.status;

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <main className="lv-main lv-tp-main lv-portefeuille-page">
        <header className="lv-portefeuille-header">
          <div className="lv-portefeuille-brand">
            <div className="lv-portefeuille-title-row">
              <h1 className="lv-portefeuille-title">PORTEFEUILLE</h1>
              <span className="lv-portefeuille-kicker">TRADINGCENTER</span>
              <span className="lv-portefeuille-badge is-paper">PAPER / SIMULATED</span>
              {status === "RUNNING" ? <span className="lv-portefeuille-badge is-live-dot">Live marks</span> : null}
            </div>
            <p className="lv-portefeuille-quote">
              “Disciplined capital. Intelligent allocation. Compounding the future.”
            </p>
          </div>
          <div className="lv-portefeuille-toolbar">
            <select
              className="lv-portefeuille-select"
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              aria-label="Select Portefeuille"
            >
              {!portfolios.length ? <option value="">No Portefeuille</option> : null}
              {portfolios.map((p) => (
                <option key={p.portfolio_id} value={p.portfolio_id}>
                  {p.name} · {p.status}
                </option>
              ))}
            </select>
            <button type="button" className="lv-portefeuille-btn" onClick={() => setCreateOpen(true)}>
              Create
            </button>
            <button type="button" className="lv-portefeuille-btn" disabled={!selectedId || busy} onClick={() => void lifecycle("start")}>
              Start
            </button>
            <button type="button" className="lv-portefeuille-btn" disabled={!selectedId || busy} onClick={() => void lifecycle("pause")}>
              Pause
            </button>
            <button type="button" className="lv-portefeuille-btn" disabled={!selectedId || busy} onClick={() => void lifecycle("resume")}>
              Resume
            </button>
            <button type="button" className="lv-portefeuille-btn is-danger" disabled={!selectedId || busy} onClick={() => void lifecycle("stop")}>
              Stop
            </button>
          </div>
        </header>

        {disabled ? (
          <div className="lv-portefeuille-state">
            <h2>Market sim disabled</h2>
            <p>Enable LEVIATHAN_FEATURE_MARKET_SIM to use Paper Portefeuille.</p>
          </div>
        ) : null}

        {!disabled && loading ? (
          <div className="lv-portefeuille-state">
            <h2>Loading Portefeuille…</h2>
            <p>Fetching paper capital books from the control plane.</p>
          </div>
        ) : null}

        {!disabled && !loading && !portfolios.length ? (
          <div className="lv-portefeuille-empty">
            <h2>No Paper Portefeuille</h2>
            <p>
              Create a virtual capital book. Trading agents operate on this paper equity — cash, positions,
              and PnL are persisted and never real money.
            </p>
            <button type="button" className="lv-portefeuille-btn is-primary" onClick={() => setCreateOpen(true)}>
              Create Paper Portefeuille
            </button>
          </div>
        ) : null}

        {error ? <div className="lv-tp-banner is-bad">{error}</div> : null}

        {!disabled && dash && kpis ? (
          <>
            {dash.market_status?.stale ? (
              <div className="lv-tp-banner is-bad">Market marks degraded / stale — positions remain visible.</div>
            ) : null}

            <section className="lv-portefeuille-kpis" aria-label="KPI strip">
              <article className="lv-portefeuille-kpi">
                <div className="lv-portefeuille-kpi-label">Total Equity</div>
                <div className="lv-portefeuille-kpi-value">{fmtMoney(num(kpis.total_equity))}</div>
                <div className={`lv-portefeuille-kpi-sub ${kpis.daily_pnl_pct >= 0 ? "is-good" : "is-bad"}`}>
                  {fmtPct(kpis.daily_pnl_pct)}
                </div>
              </article>
              <article className="lv-portefeuille-kpi">
                <div className="lv-portefeuille-kpi-label">Daily PnL</div>
                <div className={`lv-portefeuille-kpi-value ${num(kpis.daily_pnl) >= 0 ? "is-good" : "is-bad"}`}>
                  {fmtMoney(num(kpis.daily_pnl))}
                </div>
                <div className="lv-portefeuille-kpi-sub">{fmtPct(kpis.daily_pnl_pct)}</div>
              </article>
              <article className="lv-portefeuille-kpi">
                <div className="lv-portefeuille-kpi-label">Unrealized PnL</div>
                <div className={`lv-portefeuille-kpi-value ${num(kpis.unrealized_pnl) >= 0 ? "is-good" : "is-bad"}`}>
                  {fmtMoney(num(kpis.unrealized_pnl))}
                </div>
                <div className="lv-portefeuille-kpi-sub">{fmtPct(kpis.unrealized_pnl_pct)}</div>
              </article>
              <article className="lv-portefeuille-kpi">
                <div className="lv-portefeuille-kpi-label">Realized PnL</div>
                <div className={`lv-portefeuille-kpi-value ${num(kpis.realized_pnl) >= 0 ? "is-good" : "is-bad"}`}>
                  {fmtMoney(num(kpis.realized_pnl))}
                </div>
                <div className="lv-portefeuille-kpi-sub">{fmtPct(kpis.realized_pnl_pct)}</div>
              </article>
              <article className="lv-portefeuille-kpi">
                <div className="lv-portefeuille-kpi-label">Cash Balance</div>
                <div className="lv-portefeuille-kpi-value">{fmtMoney(num(kpis.cash_balance))}</div>
                <div className="lv-portefeuille-kpi-sub is-muted">
                  avail {fmtMoney(num(kpis.available_buying_power))}
                </div>
              </article>
              <article className="lv-portefeuille-kpi">
                <div className="lv-portefeuille-kpi-label">Margin Usage</div>
                <div className="lv-portefeuille-kpi-value">
                  {kpis.margin_disabled ? "0%" : `${kpis.margin_usage_pct.toFixed(1)}%`}
                </div>
                <div className="lv-portefeuille-kpi-bar">
                  <span style={{ width: `${Math.min(100, kpis.margin_usage_pct)}%` }} />
                </div>
              </article>
              <article className="lv-portefeuille-kpi">
                <div className="lv-portefeuille-kpi-label">Win Rate</div>
                <div className="lv-portefeuille-kpi-value">
                  {kpis.win_rate == null ? "—" : `${kpis.win_rate.toFixed(1)}%`}
                </div>
                <div className="lv-portefeuille-kpi-sub is-muted">closed trades</div>
              </article>
              <article className="lv-portefeuille-kpi">
                <div className="lv-portefeuille-kpi-label">Last Sync</div>
                <div className="lv-portefeuille-kpi-value" style={{ fontSize: 13 }}>
                  {relativeSync(kpis.last_sync)}
                </div>
                <div className="lv-portefeuille-kpi-sub is-muted">{kpis.stale ? "stale" : "ok"}</div>
              </article>
            </section>

            <section className="lv-portefeuille-mid">
              <article className="lv-portefeuille-panel">
                <div className="lv-portefeuille-panel-head">
                  <div className="lv-portefeuille-panel-title">Portefeuille Overview</div>
                  <div className="lv-portefeuille-tabs">
                    {RANGES.map((r) => (
                      <button
                        key={r}
                        type="button"
                        className={`lv-portefeuille-tab${range === r ? " is-active" : ""}`}
                        onClick={() => setRange(r)}
                      >
                        {r}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="lv-portefeuille-stats">
                  <span>
                    Total Return
                    <strong className={(dash.performance_summary.total_return ?? 0) >= 0 ? "is-good" : "is-bad"}>
                      {fmtPct(dash.performance_summary.total_return)}
                    </strong>
                  </span>
                  <span>
                    Sharpe <strong>{fmtMetric(dash.performance_summary.sharpe)}</strong>
                  </span>
                  <span>
                    Max Drawdown <strong>{fmtPct(dash.performance_summary.max_drawdown)}</strong>
                  </span>
                  <span>
                    Volatility <strong>{fmtPct(dash.performance_summary.volatility)}</strong>
                  </span>
                </div>
                <EquityChart series={dash.performance_summary.series || []} />
                <div className="lv-portefeuille-legend">
                  <span>
                    <i style={{ background: "#22d3ee" }} /> Portefeuille
                  </span>
                  <span className="is-muted">
                    <i style={{ background: "#e8c547" }} /> Benchmark unavailable unless feed provides series
                  </span>
                </div>
              </article>

              <article className="lv-portefeuille-panel">
                <div className="lv-portefeuille-panel-head">
                  <div className="lv-portefeuille-panel-title">Allocation & Exposure</div>
                  <div className="lv-portefeuille-tabs">
                    {(["asset", "sector", "geography"] as const).map((t) => (
                      <button
                        key={t}
                        type="button"
                        className={`lv-portefeuille-tab${allocTab === t ? " is-active" : ""}`}
                        onClick={() => setAllocTab(t)}
                      >
                        {t === "asset" ? "Asset Class" : t === "sector" ? "Sector" : "Geography"}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="lv-portefeuille-alloc-body">
                  <Donut
                    size={130}
                    center={fmtMoney(num(dash.allocation.total_equity))}
                    slices={(allocTab === "asset"
                      ? dash.allocation.by_asset_class.map((r) => ({
                          value: r.allocation_pct,
                          color: ALLOC_COLORS[0],
                        }))
                      : allocTab === "sector"
                        ? dash.allocation.by_sector.map((r, i) => ({
                            value: r.allocation_pct,
                            color: ALLOC_COLORS[i % ALLOC_COLORS.length],
                          }))
                        : dash.allocation.by_geography.map((r, i) => ({
                            value: r.allocation_pct,
                            color: ALLOC_COLORS[i % ALLOC_COLORS.length],
                          }))
                    ).map((s, i) => ({ ...s, color: ALLOC_COLORS[i % ALLOC_COLORS.length] }))}
                  />
                  <div className="lv-portefeuille-scroll">
                    {allocTab !== "asset" &&
                    !(allocTab === "sector" ? dash.allocation.by_sector : dash.allocation.by_geography).length ? (
                      <p className="is-muted">No {allocTab} metadata available.</p>
                    ) : (
                      <table className="lv-portefeuille-table">
                        <thead>
                          <tr>
                            <th>Asset</th>
                            <th>Value</th>
                            <th>Alloc</th>
                            <th>PnL</th>
                          </tr>
                        </thead>
                        <tbody>
                          {dash.allocation.assets.map((a) => (
                            <tr key={a.symbol}>
                              <td>{a.symbol}</td>
                              <td>{fmtMoney(num(a.value))}</td>
                              <td>{a.allocation_pct.toFixed(1)}%</td>
                              <td className={num(a.pnl_24h) >= 0 ? "is-good" : "is-bad"}>
                                {fmtMoney(num(a.pnl_24h))}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                  <ul className="lv-portefeuille-exposure">
                    <li>
                      <span>Net Exposure</span>
                      <strong>{dash.exposure.net_exposure_pct.toFixed(1)}%</strong>
                    </li>
                    <li>
                      <span>Gross Exposure</span>
                      <strong>{dash.exposure.gross_exposure_pct.toFixed(1)}%</strong>
                    </li>
                    <li>
                      <span>Leverage</span>
                      <strong>{dash.exposure.leverage.toFixed(2)}x</strong>
                    </li>
                    <li>
                      <span>Crypto</span>
                      <strong>{dash.exposure.crypto_allocation_pct.toFixed(1)}%</strong>
                    </li>
                    <li>
                      <span>Equities</span>
                      <strong>{dash.exposure.equities_allocation_pct.toFixed(1)}%</strong>
                    </li>
                    <li>
                      <span>Stable/Cash</span>
                      <strong>{dash.exposure.stablecoin_cash_allocation_pct.toFixed(1)}%</strong>
                    </li>
                  </ul>
                </div>
              </article>
            </section>

            <section className="lv-portefeuille-panel">
              <div className="lv-portefeuille-panel-head">
                <div className="lv-portefeuille-panel-title">
                  Open Positions ({positions.length})
                </div>
              </div>
              <div className="lv-portefeuille-positions-tools">
                <input
                  className="lv-portefeuille-input"
                  placeholder="Search symbol / strategy"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <select
                  className="lv-portefeuille-select"
                  value={sideFilter}
                  onChange={(e) => setSideFilter(e.target.value)}
                >
                  <option value="ALL">All Sides</option>
                  <option value="LONG">Long</option>
                  <option value="SHORT">Short</option>
                </select>
                <button
                  type="button"
                  className="lv-portefeuille-btn is-danger"
                  disabled={!selectedPositions.length || busy}
                  onClick={() => void closeSelected()}
                >
                  Close Selected
                </button>
              </div>
              <div className="lv-portefeuille-scroll" style={{ maxHeight: 260 }}>
                <table className="lv-portefeuille-table">
                  <thead>
                    <tr>
                      <th />
                      <th>Symbol</th>
                      <th>Side</th>
                      <th>Qty</th>
                      <th>Entry</th>
                      <th>Mark</th>
                      <th>PnL</th>
                      <th>PnL %</th>
                      <th>Alloc</th>
                      <th>Risk</th>
                      <th>Strategy</th>
                      <th>Status</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={p.position_id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedPositions.includes(p.position_id)}
                            onChange={(e) =>
                              setSelectedPositions((prev) =>
                                e.target.checked
                                  ? [...prev, p.position_id]
                                  : prev.filter((id) => id !== p.position_id),
                              )
                            }
                          />
                        </td>
                        <td>{p.symbol}</td>
                        <td>
                          <span className={`lv-portefeuille-chip ${p.side === "LONG" ? "is-long" : "is-short"}`}>
                            {p.side}
                          </span>
                        </td>
                        <td>{p.qty}</td>
                        <td>{fmtMoney(num(p.avg_entry_price))}</td>
                        <td>{fmtMoney(num(p.mark_price))}</td>
                        <td className={num(p.unrealized_pnl) >= 0 ? "is-good" : "is-bad"}>
                          {fmtMoney(num(p.unrealized_pnl))}
                        </td>
                        <td className={num(p.pnl_pct) >= 0 ? "is-good" : "is-bad"}>{p.pnl_pct}%</td>
                        <td>{p.allocation_pct.toFixed(1)}%</td>
                        <td>
                          <span
                            className={`lv-portefeuille-chip is-risk-${String(p.risk).toLowerCase()}`}
                          >
                            {p.risk}
                          </span>
                        </td>
                        <td>{p.strategy_id || "—"}</td>
                        <td>
                          <span className="lv-portefeuille-chip is-long">{p.status}</span>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="lv-portefeuille-btn is-danger"
                            disabled={busy}
                            onClick={() => void closeOne(p.position_id)}
                          >
                            Close
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!positions.length ? (
                      <tr>
                        <td colSpan={13} className="is-muted">
                          No open positions
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="lv-portefeuille-risk-row">
              <article className="lv-portefeuille-panel">
                <div className="lv-portefeuille-panel-title">Risk & Health</div>
                <div className="lv-portefeuille-risk-grid" style={{ marginTop: 8 }}>
                  <ul className="lv-portefeuille-metric-list">
                    <li><span>Sharpe</span><strong>{fmtMetric(dash.risk.sharpe)}</strong></li>
                    <li><span>Sortino</span><strong>{fmtMetric(dash.risk.sortino)}</strong></li>
                    <li><span>Max DD</span><strong>{fmtPct(dash.risk.max_drawdown)}</strong></li>
                    <li><span>VaR 1D 95%</span><strong>{fmtPct(dash.risk.var_1d_95)}</strong></li>
                    <li><span>Beta</span><strong>{fmtMetric(dash.risk.beta)}</strong></li>
                  </ul>
                  <div className="lv-portefeuille-gauge">
                    <div className="lv-portefeuille-gauge-score">{dash.risk.health.score}</div>
                    <div className="lv-portefeuille-panel-title">{dash.risk.health.label}</div>
                    <div className="is-muted" style={{ fontSize: 11 }}>Portfolio Health</div>
                  </div>
                  <div className="lv-portefeuille-bars">
                    <div className="lv-portefeuille-bar-row">
                      <span>Exposure</span>
                      <div className="lv-portefeuille-bar-track">
                        <span style={{ width: `${Math.min(100, Math.abs(dash.risk.exposure_pct || 0))}%` }} />
                      </div>
                      <span>{(dash.risk.exposure_pct ?? 0).toFixed(1)}%</span>
                    </div>
                    <div className="lv-portefeuille-bar-row">
                      <span>Correlation</span>
                      <div className="lv-portefeuille-bar-track">
                        <span
                          style={{
                            width: `${dash.risk.correlation == null ? 0 : Math.min(100, Math.abs(dash.risk.correlation) * 100)}%`,
                          }}
                        />
                      </div>
                      <span>{fmtMetric(dash.risk.correlation)}</span>
                    </div>
                    <div className="lv-portefeuille-bar-row">
                      <span>Stress</span>
                      <div className="lv-portefeuille-bar-track">
                        <span
                          style={{
                            width:
                              dash.risk.stress_level === "HIGH"
                                ? "90%"
                                : dash.risk.stress_level === "MEDIUM"
                                  ? "55%"
                                  : "25%",
                          }}
                        />
                      </div>
                      <span>{dash.risk.stress_level}</span>
                    </div>
                    <div className="lv-portefeuille-bar-row">
                      <span>Liquidity</span>
                      <div className="lv-portefeuille-bar-track">
                        <span
                          style={{
                            width: `${dash.risk.liquidity_score == null ? 0 : Math.min(100, dash.risk.liquidity_score * 10)}%`,
                          }}
                        />
                      </div>
                      <span>
                        {dash.risk.liquidity_score == null ? "—" : `${dash.risk.liquidity_score}/10`}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="lv-portefeuille-intel">
                  <div className="lv-portefeuille-intel-title">AI Portefeuille Intelligence</div>
                  <ul>
                    {(dash.insights || []).map((i) => (
                      <li key={i.id} className={i.severity === "warn" ? "is-warn" : undefined}>
                        {i.text}
                      </li>
                    ))}
                  </ul>
                </div>
              </article>

              <article className="lv-portefeuille-panel">
                <div className="lv-portefeuille-panel-title">Rebalancing Recommendations</div>
                <div className="lv-portefeuille-scroll" style={{ maxHeight: 280, marginTop: 8 }}>
                  {(dash.recommendations || []).map((r) => (
                    <div key={r.recommendation_id} className="lv-portefeuille-rec">
                      <div className="lv-portefeuille-rec-head">
                        <strong>{r.type.replace(/_/g, " ")}</strong>
                        <span className={`lv-portefeuille-impact is-${r.impact.toLowerCase()}`}>
                          {r.impact} impact
                        </span>
                      </div>
                      <p style={{ margin: "0 0 8px", fontSize: 12 }}>{r.reason}</p>
                      <button
                        type="button"
                        className="lv-portefeuille-btn"
                        disabled={busy || !r.estimated_orders?.length}
                        onClick={() => void runRecommendation(r)}
                      >
                        {r.type.includes("HEDGE")
                          ? "Hedge"
                          : r.type.includes("ALLOC")
                            ? "Allocate"
                            : "Rebalance"}
                      </button>
                    </div>
                  ))}
                  {!dash.recommendations?.length ? (
                    <p className="is-muted">No rebalancing recommendations — book within targets.</p>
                  ) : null}
                </div>
                <div className="lv-portefeuille-actions">
                  <button type="button" className="lv-portefeuille-btn is-primary" disabled={busy} onClick={() => void executeAll()}>
                    Execute All
                  </button>
                  <button type="button" className="lv-portefeuille-btn" onClick={() => void exportReport("csv")}>
                    Export Report
                  </button>
                  <button type="button" className="lv-portefeuille-btn" disabled={busy} onClick={() => void saveAllocation()}>
                    Save Allocation
                  </button>
                  <button type="button" className="lv-portefeuille-btn" onClick={() => setAnalysisOpen(true)}>
                    View Detailed Analysis
                  </button>
                </div>
              </article>
            </section>

            <section className="lv-portefeuille-bottom">
              <article className="lv-portefeuille-panel">
                <div className="lv-portefeuille-panel-title">Recent Transactions</div>
                <div className="lv-portefeuille-scroll" style={{ maxHeight: 240, marginTop: 8 }}>
                  <table className="lv-portefeuille-table">
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Qty</th>
                        <th>Price</th>
                        <th>Fees</th>
                        <th>Total</th>
                        <th>Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(dash.recent_transactions || []).map((t) => (
                        <tr key={t.transaction_id} title={`${t.agent_id || ""} ${t.strategy_id || ""}`}>
                          <td>{(t.timestamp || "").slice(11, 19) || "—"}</td>
                          <td>{t.symbol}</td>
                          <td>
                            <span
                              className={`lv-portefeuille-chip ${
                                t.side === "BUY" || t.side === "COVER" ? "is-long" : "is-short"
                              }`}
                            >
                              {t.side}
                            </span>
                          </td>
                          <td>{t.qty}</td>
                          <td>{fmtMoney(num(t.price))}</td>
                          <td>{fmtMoney(num(t.fees))}</td>
                          <td>{fmtMoney(num(t.gross_notional || t.net_cash_effect))}</td>
                          <td>{t.result}</td>
                        </tr>
                      ))}
                      {!dash.recent_transactions?.length ? (
                        <tr>
                          <td colSpan={8} className="is-muted">
                            No transactions yet
                          </td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>

              <article className="lv-portefeuille-panel">
                <div className="lv-portefeuille-panel-title">Strategy Allocation</div>
                <div className="lv-portefeuille-scroll" style={{ maxHeight: 240, marginTop: 8 }}>
                  <table className="lv-portefeuille-table">
                    <thead>
                      <tr>
                        <th>Strategy</th>
                        <th>Alloc</th>
                        <th>Equity</th>
                        <th>PnL</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(dash.strategy_allocation || []).map((s) => (
                        <tr key={`${s.strategy_id}-${s.strategy_version ?? ""}`}>
                          <td>{s.strategy_id}</td>
                          <td>{s.allocation_pct.toFixed(1)}%</td>
                          <td>{fmtMoney(num(s.equity))}</td>
                          <td className={num(s.total_pnl) >= 0 ? "is-good" : "is-bad"}>
                            {fmtMoney(num(s.total_pnl))}
                          </td>
                          <td>{s.status}</td>
                        </tr>
                      ))}
                      {!dash.strategy_allocation?.length ? (
                        <tr>
                          <td colSpan={5} className="is-muted">
                            No strategy attribution yet
                          </td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>

              <article className="lv-portefeuille-panel">
                <div className="lv-portefeuille-panel-title">Book status</div>
                <ul className="lv-portefeuille-metric-list" style={{ marginTop: 8 }}>
                  <li><span>Status</span><strong>{dash.portfolio.status}</strong></li>
                  <li><span>Mode</span><strong>PAPER</strong></li>
                  <li><span>Broker</span><strong>{dash.portfolio.broker_mode}</strong></li>
                  <li><span>Orchestra</span><strong>{dash.portfolio.orchestra_id || "—"}</strong></li>
                  <li><span>Provider</span><strong>{dash.portfolio.provider_id}</strong></li>
                  <li><span>Shorting</span><strong>{dash.portfolio.shorting_enabled ? "ON" : "OFF"}</strong></li>
                  <li><span>Kill switch</span><strong>{dash.portfolio.kill_switch ? "ARMED" : "off"}</strong></li>
                </ul>
              </article>
            </section>
          </>
        ) : null}

        <CreateModal
          open={createOpen}
          orchestras={orchestras}
          busy={busy}
          onClose={() => setCreateOpen(false)}
          onCreate={(p) => void createPortfolio(p)}
        />
        <AnalysisModal open={analysisOpen} dash={dash} onClose={() => setAnalysisOpen(false)} />
      </main>
    </AppShell>
  );
}
