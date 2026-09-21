import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ban,
  BookOpenCheck,
  Bot,
  CandlestickChart,
  Database,
  Loader2,
  LockKeyhole,
  Play,
  RefreshCw,
  RotateCcw,
  Shield,
  Sparkles,
  TrendingDown,
  WalletCards,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Panel, StatusBadge, type StatusTone } from "@/components/hades/ui";
import {
  formatDate,
  hadesApi,
  MarketBar,
  PaperTradingState,
  TradingDashboard,
  TradingRun,
  TradingStrategy,
} from "@/lib/hades-api";

const emptyPaper: PaperTradingState = {
  settings: { enabled: false, kill_switch: false, updated_at: "" },
  wallets: [],
  positions: [],
  orders: [],
  events: [],
};

const emptyDashboard: TradingDashboard = {
  paper: emptyPaper,
  bot: {
    id: 1,
    enabled: false,
    strategy_id: null,
    symbol: "BTC/USDT",
    timeframe: "1h",
    position_fraction: 0.1,
    last_bar_ts: null,
    updated_at: "",
  },
  symbols: [],
  bars: [],
  strategies: [],
  runs: [],
  learnings: [],
  strategy_kinds: [],
};

function money(value: number) {
  return new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

function pct(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function runTone(status: string): StatusTone {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "queued") return "info";
  return "warning";
}

function CandleChart({ bars }: { bars: MarketBar[] }) {
  const width = 640;
  const height = 240;
  const pad = 16;
  if (bars.length < 2) {
    return (
      <div className="empty-state">
        <CandlestickChart />
        <strong>Geen marktdata</strong>
        <span>Seed synthetische data of importeer een OHLCV-CSV.</span>
      </div>
    );
  }
  const slice = bars.slice(-80);
  const highs = slice.map((bar) => bar.high);
  const lows = slice.map((bar) => bar.low);
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const span = Math.max(max - min, 1e-9);
  const step = (width - pad * 2) / slice.length;
  const y = (price: number) => pad + ((max - price) / span) * (height - pad * 2);
  const last = slice[slice.length - 1];
  const first = slice[0];
  const change = ((last.close - first.open) / first.open) * 100;

  return (
    <div>
      <div className="chart-meta">
        <strong>{last.symbol}</strong>
        <span className={change >= 0 ? "positive" : "negative"}>{change >= 0 ? "+" : ""}{change.toFixed(2)}%</span>
        <span>{money(last.close)} USDT · {slice.length} bars</span>
      </div>
      <svg className="market-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Koersgrafiek ${last.symbol}`}>
        {[0.25, 0.5, 0.75].map((ratio) => {
          const yy = pad + ratio * (height - pad * 2);
          return <line key={ratio} className="chart-grid-line" x1={pad} x2={width - pad} y1={yy} y2={yy} />;
        })}
        {slice.map((bar, index) => {
          const x = pad + index * step + step / 2;
          const up = bar.close >= bar.open;
          const bodyTop = y(Math.max(bar.open, bar.close));
          const bodyBottom = y(Math.min(bar.open, bar.close));
          const bodyHeight = Math.max(2, bodyBottom - bodyTop);
          return (
            <g key={`${bar.ts}-${index}`}>
              <line className={up ? "candle-up" : "candle-down"} x1={x} x2={x} y1={y(bar.high)} y2={y(bar.low)} />
              <rect
                className={up ? "candle-up-fill" : "candle-down-fill"}
                x={x - Math.max(1.2, step * 0.28)}
                y={bodyTop}
                width={Math.max(2.4, step * 0.56)}
                height={bodyHeight}
              />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** The original HADES paper desk. Kept intact so existing data and flows keep working. */
export function PaperDeskTab() {
  const [dashboard, setDashboard] = useState<TradingDashboard>(emptyDashboard);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [quantity, setQuantity] = useState("0.001");
  const [price, setPrice] = useState("100000");
  const [closePrices, setClosePrices] = useState<Record<string, string>>({});
  const [csvText, setCsvText] = useState("");

  const state = dashboard.paper;

  const applyDashboard = useCallback((next: TradingDashboard) => {
    setDashboard(next);
    if (next.bot.symbol) setSymbol(next.bot.symbol);
    const lastClose = next.bars[next.bars.length - 1]?.close;
    if (lastClose) setPrice(String(lastClose));
  }, []);

  const load = useCallback(async () => {
    try {
      applyDashboard(await hadesApi.tradingDashboard());
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Trading laden is mislukt.");
    } finally {
      setLoading(false);
    }
  }, [applyDashboard]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const active = dashboard.runs.some((run) => run.status === "running" || run.status === "queued");
    if (!active) return;
    const timer = window.setInterval(() => {
      void load();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [dashboard.runs, load]);

  const balance = state.wallets.find((wallet) => wallet.asset === "USDT")?.balance ?? 0;
  const openPositions = useMemo(() => state.positions.filter((position) => position.status === "open"), [state.positions]);
  const realizedPnl = useMemo(() => state.positions.reduce((sum, position) => sum + Number(position.realized_pnl || 0), 0), [state.positions]);
  const activeStrategy = useMemo(
    () => dashboard.strategies.find((item) => item.id === dashboard.bot.strategy_id) ?? dashboard.strategies[0] ?? null,
    [dashboard.strategies, dashboard.bot.strategy_id],
  );
  const activeRun = useMemo(
    () => dashboard.runs.find((run) => run.status === "running" || run.status === "queued") ?? dashboard.runs[0] ?? null,
    [dashboard.runs],
  );

  const mutatePaper = async (operation: () => Promise<PaperTradingState>) => {
    setWorking(true);
    try {
      const paper = await operation();
      setDashboard((current) => ({ ...current, paper }));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Paperactie is mislukt.");
    } finally {
      setWorking(false);
    }
  };

  const buy = async () => {
    const qty = Number(quantity);
    const px = Number(price);
    if (!symbol.trim() || !Number.isFinite(qty) || qty <= 0 || !Number.isFinite(px) || px <= 0) {
      toast.error("Vul een geldig symbool, hoeveelheid en simulatieprijs in.");
      return;
    }
    setWorking(true);
    try {
      const result = await hadesApi.paperBuy(symbol, qty, px);
      setDashboard((current) => ({ ...current, paper: result.state }));
      toast.success("PAPER-buy transactioneel uitgevoerd.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Paperorder is mislukt.");
    } finally {
      setWorking(false);
    }
  };

  const close = async (id: string, fallback: number) => {
    const px = Number(closePrices[id] || fallback);
    if (!Number.isFinite(px) || px <= 0) {
      toast.error("Vul een geldige sluitprijs in.");
      return;
    }
    setWorking(true);
    try {
      const result = await hadesApi.closePaperPosition(id, px);
      setDashboard((current) => ({ ...current, paper: result.state }));
      toast.success(`Positie gesloten. Gerealiseerde PnL: ${money(result.realized_pnl)} USDT.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Positie sluiten is mislukt.");
    } finally {
      setWorking(false);
    }
  };

  const seedMarket = async () => {
    setWorking(true);
    try {
      const result = await hadesApi.seedTradingMarket({ symbol, timeframe: dashboard.bot.timeframe || "1h", bars: 720 });
      applyDashboard(result.dashboard);
      const bars = Number(result.summary?.bars || 0);
      if (bars <= 0) {
        toast.message("Geen synthetische balken geladen.");
      } else {
        toast.success(`${bars} synthetische balken geladen voor ${symbol}.`);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Marktdata seed mislukt.");
    } finally {
      setWorking(false);
    }
  };

  const importCsv = async () => {
    if (!csvText.trim()) {
      toast.error("Plak eerst CSV met ts,open,high,low,close[,volume].");
      return;
    }
    setWorking(true);
    try {
      const result = await hadesApi.importTradingCsv({ symbol, timeframe: dashboard.bot.timeframe || "1h", csv_text: csvText });
      applyDashboard(result.dashboard);
      setCsvText("");
      const bars = Number(result.summary?.bars || 0);
      if (bars <= 0) {
        toast.message("Geen CSV-balken geïmporteerd.");
      } else {
        toast.success(`${bars} CSV-balken geïmporteerd.`);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "CSV-import mislukt.");
    } finally {
      setWorking(false);
    }
  };

  const startRun = async (kind: "discover" | "backtest" | "paper_bot") => {
    setWorking(true);
    try {
      const result = await hadesApi.createTradingRun({
        kind,
        symbol,
        timeframe: dashboard.bot.timeframe || "1h",
        strategy_id: kind === "discover" ? undefined : activeStrategy?.id,
        top_n: 5,
        window: 240,
        auto_start: true,
      });
      applyDashboard(result.dashboard);
      toast.success(
        kind === "discover"
          ? "Strategie-ontdekking gestart op historische data."
          : kind === "backtest"
            ? "Backtest gestart."
            : "Paper-bot run gestart.",
      );
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Trading-run starten mislukt.");
    } finally {
      setWorking(false);
    }
  };

  const activateStrategy = async (strategy: TradingStrategy) => {
    setWorking(true);
    try {
      const result = await hadesApi.updateTradingBot({ strategy_id: strategy.id, symbol, enabled: false });
      applyDashboard(result.dashboard);
      toast.success(`${strategy.name} geactiveerd voor de paper-bot.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Strategie activeren mislukt.");
    } finally {
      setWorking(false);
    }
  };

  const cancelRun = async (run: TradingRun) => {
    setWorking(true);
    try {
      const result = await hadesApi.cancelTradingRun(run.id);
      applyDashboard(result.dashboard);
      toast.success("Trading-run geannuleerd.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Annuleren mislukt.");
    } finally {
      setWorking(false);
    }
  };

  return (
    <>
      <div className="lab-stack" style={{ marginBottom: "0.75rem" }}>
        <Panel title="Legacy Paper desk — educatief">
          <div className="lab-inline-facts" style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
            <StatusBadge tone="warning">LEGACY / EDUCATIONAL — geen gevalideerde strategie</StatusBadge>
            <span>
              Wallet, buy/close en kill switch zijn echte PAPER-administratie. Discovery/backtest-scores hier zijn
              in-sample met same-bar fills, zonder fees/spread/slippage — geen Trading Lab-validatie.
            </span>
            <span>
              Handmatige prijs = <code>price_source=operator_input</code> (operatorinvoer, geen brokerfill).
              Serieuze research hoort in de Lab-tabs (PIT, kosten, sealed holdout).
            </span>
          </div>
        </Panel>
      </div>
      <div className="trading-status-row">
        <Panel>
          <div className="toggle-card">
            <div>
              <strong>Paper trading</strong>
              <span>Nieuwe gesimuleerde orders {state.settings.enabled ? "toegestaan" : "geblokkeerd"}.</span>
            </div>
            {loading ? <Loader2 className="spin" /> : (
              <Switch
                checked={state.settings.enabled}
                disabled={working}
                onCheckedChange={(enabled) => void mutatePaper(() => hadesApi.setPaperTrading(enabled))}
              />
            )}
          </div>
        </Panel>
        <Panel>
          <div className="wallet-card">
            <WalletCards />
            <span><small>Paper wallet</small><strong>PAPER-USDT</strong></span>
            <div><small>Vrij</small><strong>{money(balance)} USDT</strong></div>
          </div>
        </Panel>
        <Panel>
          <div className="market-status">
            <span>
              <Shield />
              <strong>Kill switch</strong>
              <small>{state.settings.kill_switch ? "Nieuwe orders geblokkeerd" : "Vrijgegeven"}</small>
            </span>
            <Button
              variant={state.settings.kill_switch ? "default" : "outline"}
              disabled={working}
              onClick={() => void mutatePaper(() => hadesApi.setTradingKillSwitch(!state.settings.kill_switch))}
            >
              {state.settings.kill_switch ? "Vrijgeven" : "Activeren"}
            </Button>
          </div>
        </Panel>
      </div>

      <div className="trading-grid">
        <Panel title="Marktdata" actions={<Database />}>
          <div className="form-stack">
            <label>
              <span>Symbool</span>
              <Input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} placeholder="BTC/USDT" />
            </label>
            <div className="button-stack">
              <Button disabled={working} onClick={() => void seedMarket()}>
                {working ? <Loader2 className="spin" /> : <Sparkles />}Synthetische historie
              </Button>
              <Button variant="outline" disabled={working} onClick={() => void importCsv()}>
                <Database />CSV importeren
              </Button>
            </div>
            <label>
              <span>OHLCV CSV</span>
              <Textarea
                value={csvText}
                onChange={(event) => setCsvText(event.target.value)}
                placeholder={"ts,open,high,low,close,volume\n2024-01-01T00:00:00+00:00,100,101,99,100.5,12"}
                rows={4}
              />
            </label>
            <div className="advice-box">
              <Ban />
              <span>
                <strong>Offline-first</strong>
                <small>Geen live beursfeed in de core. Seed of CSV voedt discovery, backtests en de paper-bot.</small>
              </span>
            </div>
            {dashboard.symbols[0] ? (
              <small className="legal-note">
                {dashboard.symbols[0].bars} balken · {dashboard.symbols[0].first_ts} → {dashboard.symbols[0].last_ts}
              </small>
            ) : null}
          </div>
        </Panel>

        <Panel title="Marktgrafiek" actions={<Button size="icon" variant="ghost" onClick={() => void load()}><RefreshCw /></Button>}>
          <CandleChart bars={dashboard.bars} />
        </Panel>

        <Panel title="Trading bot" actions={<Bot />}>
          <div className="form-stack">
            <div className="wallet-card">
              <Bot />
              <span>
                <small>Actieve strategie</small>
                <strong>{activeStrategy?.name || "Nog geen strategie"}</strong>
              </span>
            </div>
            {activeStrategy ? (
              <small className="legal-note">
                {activeStrategy.kind} · educational in-sample score {Number(activeStrategy.score).toFixed(2)} ·{" "}
                {typeof activeStrategy.metrics.total_return === "number" ? pct(Number(activeStrategy.metrics.total_return)) : "—"}
                {" · niet gevalideerd"}
              </small>
            ) : null}
            <div className="button-stack">
              <Button disabled={working || dashboard.bars.length < 50} onClick={() => void startRun("discover")}>
                <Sparkles />Ontdek (legacy)
              </Button>
              <Button variant="outline" disabled={working || !activeStrategy} onClick={() => void startRun("backtest")}>
                <CandlestickChart />Backtest (legacy)
              </Button>
              <Button variant="outline" disabled={working || !activeStrategy} onClick={() => void startRun("paper_bot")}>
                <Play />Paper-bot stap
              </Button>
            </div>
            {activeRun ? (
              <div className="runtime-health">
                <div>
                  <StatusBadge tone={runTone(activeRun.status)}>{activeRun.kind}</StatusBadge>
                  <small>{activeRun.status}</small>
                </div>
                <Progress value={activeRun.progress || 0} />
                {(activeRun.status === "running" || activeRun.status === "queued") ? (
                  <Button size="sm" variant="outline" disabled={working} onClick={() => void cancelRun(activeRun)}>
                    <X />Annuleer
                  </Button>
                ) : null}
                {activeRun.error ? <small className="negative">{activeRun.error}</small> : null}
              </div>
            ) : null}
          </div>
        </Panel>
      </div>

      <div className="trading-grid" style={{ marginTop: "0.75rem" }}>
        <Panel title="Nieuwe paperorder" actions={<CandlestickChart />}>
          <div className="form-stack">
            <label><span>Symbool</span><Input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} placeholder="BTC/USDT" /></label>
            <label><span>Hoeveelheid</span><Input type="number" min="0" step="any" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
            <label>
              <span>Simulatieprijs (USDT) — operator_input</span>
              <Input type="number" min="0" step="any" value={price} onChange={(event) => setPrice(event.target.value)} />
            </label>
            <small className="legal-note">Fill-prijs is operatorinvoer, geen brokerquote.</small>
            <Button onClick={() => void buy()} disabled={working || !state.settings.enabled || state.settings.kill_switch}>
              {working ? <Loader2 className="spin" /> : null}PAPER BUY
            </Button>
          </div>
        </Panel>

        <Panel title="Open paperposities">
          {openPositions.length === 0 ? (
            <div className="empty-state"><TrendingDown /><strong>Geen open posities</strong><span>Open handmatig of via de paper-bot.</span></div>
          ) : (
            <div className="execution-list">
              {openPositions.map((position) => (
                <span key={position.id}>
                  <div>
                    <small>{position.symbol}</small>
                    <strong>{position.quantity} @ {money(position.entry_price)}</strong>
                  </div>
                  <Input
                    aria-label={`Sluitprijs ${position.symbol}`}
                    type="number"
                    step="any"
                    value={closePrices[position.id] ?? String(position.entry_price)}
                    onChange={(event) => setClosePrices((current) => ({ ...current, [position.id]: event.target.value }))}
                  />
                  <Button size="sm" variant="outline" disabled={working} onClick={() => void close(position.id, position.entry_price)}>Sluit</Button>
                </span>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Account & invarianties">
          <div className="risk-cards">
            <div className="wallet-card"><WalletCards /><span><small>Vrij saldo</small><strong>{money(balance)} USDT</strong></span></div>
            <div className="wallet-card"><TrendingDown /><span><small>Gerealiseerde PnL</small><strong>{realizedPnl >= 0 ? "+" : ""}{money(realizedPnl)} USDT</strong></span></div>
            <div className="kill-switch">
              <LockKeyhole />
              <span><strong>Exactly-once close</strong><small>Een gesloten positie kan transactioneel niet dubbel worden gecrediteerd.</small></span>
            </div>
            <Button variant="outline" disabled={working} onClick={() => void mutatePaper(() => hadesApi.resetPaperTrading(10000))}>
              <RotateCcw />Reset PAPER-account
            </Button>
          </div>
        </Panel>
      </div>

      <div className="trading-bottom">
        <Panel title="Ontdekte strategieën (legacy in-sample)">
          {dashboard.strategies.length === 0 ? (
            <div className="empty-state"><Sparkles /><strong>Nog geen strategieën</strong><span>Start discovery op historische balken — scores zijn educatief, geen alpha-claim.</span></div>
          ) : (
            <div className="execution-list">
              {dashboard.strategies.slice(0, 12).map((strategy) => (
                <span key={strategy.id}>
                  <small>{strategy.kind} · educational</small>
                  <strong>
                    {strategy.name}
                    {" · "}
                    in-sample score {Number(strategy.score).toFixed(1)}
                    {typeof strategy.metrics.total_return === "number" ? ` · ${pct(Number(strategy.metrics.total_return))}` : ""}
                  </strong>
                  <Button size="sm" variant={dashboard.bot.strategy_id === strategy.id ? "default" : "outline"} disabled={working} onClick={() => void activateStrategy(strategy)}>
                    {dashboard.bot.strategy_id === strategy.id ? "Actief" : "Kies"}
                  </Button>
                </span>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Runs">
          {dashboard.runs.length === 0 ? (
            <div className="empty-state"><Bot /><strong>Nog geen runs</strong><span>Discovery, backtest of paper-bot verschijnen hier.</span></div>
          ) : (
            <div className="execution-list">
              {dashboard.runs.slice(0, 12).map((run) => (
                <span key={run.id}>
                  <small>{formatDate(run.created_at)}</small>
                  <strong>{run.kind} · {run.symbol} · {run.progress}%</strong>
                  <StatusBadge tone={runTone(run.status)}>{run.status}</StatusBadge>
                </span>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Paperorders">
          {state.orders.length === 0 ? (
            <div className="empty-state"><LockKeyhole /><strong>Nog geen orders</strong><span>Orders worden lokaal en append-only weergegeven.</span></div>
          ) : (
            <div className="execution-list">
              {state.orders.slice(0, 30).map((order) => (
                <span key={order.id}>
                  <small>{formatDate(order.created_at)}</small>
                  <strong>{order.symbol} · {order.side.toUpperCase()} · {order.quantity} @ {money(order.price)}</strong>
                  <StatusBadge tone="success">{order.status}</StatusBadge>
                </span>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Kennis / learnings">
          {dashboard.learnings.length === 0 ? (
            <div className="empty-state"><BookOpenCheck /><strong>Nog geen marktkennis</strong><span>Na discovery schrijft de bot leerresultaten naar Knowledge.</span></div>
          ) : (
            <div className="execution-list">
              {dashboard.learnings.slice(0, 10).map((item) => (
                <span key={item.chunk_id}>
                  <small>{item.source_type}</small>
                  <strong>{item.title}{item.heading ? ` · ${item.heading}` : ""}</strong>
                  <StatusBadge tone="info">kennis</StatusBadge>
                </span>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <div className="trading-bottom" style={{ gridTemplateColumns: "1fr" }}>
        <Panel title="Uitvoeringslog">
          {state.events.length === 0 ? (
            <div className="empty-state"><AlertTriangle /><strong>Nog geen gebeurtenissen</strong><span>Runtime-events verschijnen hier.</span></div>
          ) : (
            <div className="execution-list">
              {state.events.slice(0, 40).map((event) => (
                <span key={event.id}>
                  <small>{formatDate(event.created_at)}</small>
                  <strong>{event.message}</strong>
                  <StatusBadge tone={event.level === "warning" ? "warning" : event.level === "success" ? "success" : "neutral"}>{event.level}</StatusBadge>
                </span>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
