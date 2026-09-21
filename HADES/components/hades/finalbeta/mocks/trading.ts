/** FINALBETA TradingCenter mock data (pixel reference). */

export type TcTone = "up" | "down" | "flat" | "warn";

export type TcKpi = {
  id: string;
  label: string;
  value: string;
  hint: string;
  tone: TcTone;
  spark: number[];
  icon: string;
};

export type TcMarketCard = {
  id: string;
  symbol: string;
  price: string;
  change: string;
  tone: "up" | "down";
  spark: number[];
};

export type TcPillTone = "green" | "blue" | "gold" | "orange" | "red" | "gray" | "cyan";

/* ─── Overzicht ─────────────────────────────────────────────── */

export const TC_OVERVIEW_KPIS: TcKpi[] = [
  { id: "markets", label: "Actieve markten", value: "12", hint: "▲ +2", tone: "up", spark: [40, 48, 45, 55, 60, 58, 70, 75], icon: "globe" },
  { id: "strategies", label: "Open strategieën", value: "7", hint: "▲ +1", tone: "up", spark: [30, 35, 40, 38, 50, 55, 60, 68], icon: "list" },
  { id: "paper", label: "Paper posities", value: "18", hint: "▲ +6", tone: "up", spark: [20, 28, 35, 42, 50, 55, 62, 78], icon: "file" },
  { id: "broker", label: "Broker posities", value: "5", hint: "− 0", tone: "flat", spark: [50, 50, 48, 52, 50, 51, 50, 50], icon: "link" },
  { id: "pnl", label: "Dagelijks P&L", value: "+€ 1.284", hint: "▲ +2,3%", tone: "up", spark: [35, 42, 40, 55, 60, 58, 72, 80], icon: "chart" },
  { id: "sharpe", label: "Sharpe simulatie", value: "1,42", hint: "▲ +0,18", tone: "up", spark: [45, 48, 52, 50, 58, 62, 68, 72], icon: "bolt" },
];

export const TC_OVERVIEW_MARKETS: TcMarketCard[] = [
  { id: "btc", symbol: "BTC/USD", price: "84.312", change: "+2,6%", tone: "up", spark: [40, 45, 42, 55, 60, 58, 70, 78] },
  { id: "eth", symbol: "ETH/USD", price: "3.128", change: "+1,9%", tone: "up", spark: [35, 40, 48, 45, 55, 60, 65, 72] },
  { id: "eur", symbol: "EUR/USD", price: "1,0864", change: "−0,3%", tone: "down", spark: [70, 68, 65, 62, 58, 55, 52, 48] },
  { id: "ndx", symbol: "NASDAQ", price: "17.521", change: "+0,8%", tone: "up", spark: [45, 48, 50, 52, 55, 58, 60, 64] },
  { id: "aapl", symbol: "AAPL", price: "198,42", change: "+0,8%", tone: "up", spark: [50, 52, 48, 55, 58, 56, 62, 66] },
  { id: "nvda", symbol: "NVDA", price: "874,16", change: "+2,1%", tone: "up", spark: [30, 38, 45, 50, 55, 62, 70, 82] },
];

export const TC_OVERVIEW_STRATEGIES = [
  { name: "TrendFollower Pro", type: "Trend", status: "Running", statusTone: "green" as TcPillTone, pnl: "+12,4%" },
  { name: "Mean Reversion Soft", type: "MR", status: "Testing", statusTone: "blue" as TcPillTone, pnl: "+4,1%" },
  { name: "Pairs BTC-ETH", type: "Pairs", status: "Running", statusTone: "green" as TcPillTone, pnl: "+6,8%" },
  { name: "Sentiment Alpha", type: "NLP", status: "Paused", statusTone: "orange" as TcPillTone, pnl: "−0,6%" },
  { name: "Breakout Scalper", type: "Scalp", status: "Running", statusTone: "green" as TcPillTone, pnl: "+3,2%" },
  { name: "Macro Overlay", type: "Macro", status: "Testing", statusTone: "blue" as TcPillTone, pnl: "+1,5%" },
];

export const TC_OVERVIEW_ALLOCATION = [
  { label: "Aandelen", count: 382, color: "#1aa4ff", pct: "38,2%" },
  { label: "Crypto", count: 246, color: "#f0b429", pct: "24,6%" },
  { label: "Cash", count: 121, color: "#39c8c4", pct: "12,1%" },
  { label: "ETF's", count: 115, color: "#8d67ff", pct: "11,5%" },
  { label: "Opties", count: 89, color: "#20e38d", pct: "8,9%" },
  { label: "Overig", count: 47, color: "#758392", pct: "4,7%" },
];

export const TC_OVERVIEW_SIGNALS = [
  { time: "14:32", market: "BTC/USD", signal: "BUY", signalTone: "green" as TcPillTone, details: "Breakout 1H", status: "Executed" },
  { time: "14:18", market: "AAPL", signal: "BUY", signalTone: "green" as TcPillTone, details: "Momentum entry", status: "Executed" },
  { time: "13:55", market: "ETH/USD", signal: "SELL", signalTone: "red" as TcPillTone, details: "Take profit 2R", status: "Executed" },
  { time: "13:40", market: "NVDA", signal: "BUY", signalTone: "green" as TcPillTone, details: "Trend continuation", status: "Executed" },
  { time: "13:12", market: "EUR/USD", signal: "SELL", signalTone: "red" as TcPillTone, details: "Mean reversion", status: "Executed" },
  { time: "12:48", market: "TSLA", signal: "BUY", signalTone: "green" as TcPillTone, details: "Gap fill setup", status: "Executed" },
];

export const TC_OVERVIEW_PERF = {
  labels: ["jan", "feb", "mrt", "apr"],
  series: {
    portfolio: [42, 48, 52, 50, 58, 62, 68, 72, 70, 78, 82, 88],
    strategies: [38, 42, 48, 45, 52, 55, 60, 64, 62, 70, 74, 80],
    btc: [30, 35, 40, 55, 48, 60, 70, 65, 75, 80, 78, 85],
  },
};

export const TC_OVERVIEW_RISK = [
  { label: "VaR (95%)", value: "€ 2.430", hint: "−12%", tone: "up" as TcTone },
  { label: "Max. drawdown", value: "−6,8%", hint: "−2,1%", tone: "up" as TcTone },
  { label: "Win rate", value: "64,3%", hint: "+3,2%", tone: "up" as TcTone },
  { label: "Profit factor", value: "1,87", hint: "+0,4", tone: "up" as TcTone },
];

export const TC_CORE_MODULES = [
  { label: "Marktdata feed", status: "Actief" },
  { label: "Strategie engine", status: "Actief" },
  { label: "Executie module", status: "Actief" },
  { label: "Risico monitor", status: "Actief" },
  { label: "Portfolio intelligence", status: "Gereed" },
];

export const TC_BROKERS = [
  { name: "Interactive Brokers", status: "Verbonden" },
  { name: "Binance", status: "Verbonden" },
  { name: "Coinbase", status: "Verbonden" },
  { name: "DeGiro", status: "Verbonden" },
];

export const TC_ACCOUNTS = [
  { name: "IBKR Live", balance: "€ 52.430" },
  { name: "Binance Live", balance: "€ 28.910" },
  { name: "Coinbase Live", balance: "€ 21.340" },
  { name: "DeGiro Live", balance: "€ 25.750" },
];

export const TC_OVERVIEW_AGENTS = [
  { name: "Market Data Agent", detail: "12 feeds · 42 ms" },
  { name: "Strategy Engine", detail: "7 running" },
  { name: "Execution Agent", detail: "Fill 98,4%" },
  { name: "Risk Monitor", detail: "VaR ok" },
  { name: "Portfolio Intelligence", detail: "Rebalance 2" },
  { name: "News & Sentiment", detail: "Pulse 0,28" },
];

export const TC_OVERVIEW_ACTIONS = [
  { id: "sim", label: "Nieuwe simulatie", icon: "chart" },
  { id: "strat", label: "Strategie starten", icon: "bolt" },
  { id: "paper", label: "Paper trade openen", icon: "file" },
  { id: "broker", label: "Broker verbinden", icon: "link" },
];

/* ─── Marktdata ─────────────────────────────────────────────── */

export const TC_MD_KPIS: TcKpi[] = [
  { id: "feeds", label: "Actieve feeds", value: "8", hint: "▲ +2", tone: "up", spark: [40, 45, 50, 48, 55, 60, 65, 72], icon: "line" },
  { id: "markets", label: "Gevolgde markten", value: "24", hint: "▲ +3", tone: "up", spark: [30, 35, 40, 48, 52, 58, 65, 70], icon: "globe" },
  { id: "latency", label: "Gem. data latency", value: "42 ms", hint: "▼ −18%", tone: "up", spark: [80, 72, 65, 58, 52, 48, 44, 40], icon: "bolt" },
  { id: "anom", label: "Data anomalieën", value: "3", hint: "▲ +1", tone: "down", spark: [20, 25, 22, 30, 28, 35, 40, 45], icon: "shield" },
  { id: "news", label: "Nieuwsbronnen", value: "12", hint: "stabiel", tone: "flat", spark: [50, 52, 50, 51, 50, 52, 50, 51], icon: "book" },
  { id: "sent", label: "Sentiment pulse", value: "0,28", hint: "▲ +0,12", tone: "up", spark: [20, 25, 30, 28, 40, 45, 55, 62], icon: "brain" },
];

export const TC_MD_WATCHLISTS = [
  { id: "fav", label: "Favorieten", count: 8 },
  { id: "eq", label: "Aandelen", count: 12 },
  { id: "crypto", label: "Crypto", count: 8 },
  { id: "idx", label: "Indices", count: 6 },
  { id: "fx", label: "Valuta", count: 10 },
  { id: "cmd", label: "Grondstoffen", count: 7 },
  { id: "etf", label: "ETF's", count: 9 },
  { id: "ai", label: "Watchlist AI", count: 14 },
];

export const TC_MD_QUOTE_CARDS: TcMarketCard[] = [
  { id: "btc", symbol: "BTC/USD", price: "84.312", change: "+2,6%", tone: "up", spark: [40, 45, 42, 55, 60, 58, 70, 78] },
  { id: "eth", symbol: "ETH/USD", price: "3.128", change: "+1,9%", tone: "up", spark: [35, 40, 48, 45, 55, 60, 65, 72] },
  { id: "aapl", symbol: "AAPL", price: "198,42", change: "+0,8%", tone: "up", spark: [50, 52, 48, 55, 58, 56, 62, 66] },
  { id: "msft", symbol: "MSFT", price: "412,36", change: "+1,4%", tone: "up", spark: [45, 48, 52, 55, 58, 60, 64, 70] },
  { id: "nvda", symbol: "NVIDIA", price: "874,16", change: "+2,1%", tone: "up", spark: [30, 38, 45, 50, 55, 62, 70, 82] },
  { id: "eur", symbol: "EUR/USD", price: "1,0864", change: "−0,3%", tone: "down", spark: [70, 68, 65, 62, 58, 55, 52, 48] },
];

export const TC_MD_ORDERBOOK = {
  price: "84.312",
  change: "+2,6%",
  asks: [
    { price: "84.340", size: 1.24, depth: 92 },
    { price: "84.330", size: 0.86, depth: 78 },
    { price: "84.325", size: 1.52, depth: 65 },
    { price: "84.320", size: 0.64, depth: 48 },
    { price: "84.318", size: 0.42, depth: 32 },
  ],
  bids: [
    { price: "84.310", size: 0.58, depth: 38 },
    { price: "84.305", size: 1.12, depth: 55 },
    { price: "84.298", size: 0.94, depth: 68 },
    { price: "84.290", size: 1.48, depth: 82 },
    { price: "84.280", size: 2.10, depth: 95 },
  ],
};

export const TC_MD_NEWS = [
  { time: "14:32", title: "Fed speelt afwachtend rond rentepad", tag: "Macro", tagTone: "blue" as TcPillTone },
  { time: "14:18", title: "Tech-earnings tillen NASDAQ hoger", tag: "Aandelen", tagTone: "green" as TcPillTone },
  { time: "13:55", title: "BTC breekt weerstand nabij 84K", tag: "Crypto", tagTone: "gold" as TcPillTone },
  { time: "13:40", title: "Olievolatiliteit door voorraadcijfers", tag: "Grondstoffen", tagTone: "orange" as TcPillTone },
  { time: "13:12", title: "EUR/USD onder druk op dollarsterkte", tag: "Markt", tagTone: "cyan" as TcPillTone },
  { time: "12:48", title: "NVIDIA supply-chain update positief", tag: "Aandelen", tagTone: "green" as TcPillTone },
];

export const TC_MD_TABLE = [
  { symbol: "BTC", name: "Bitcoin", price: "84.312", change: "+2,6%", volume: "42,1B", mcap: "1,66T", tone: "up" as const },
  { symbol: "ETH", name: "Ethereum", price: "3.128", change: "+1,9%", volume: "18,4B", mcap: "376B", tone: "up" as const },
  { symbol: "AAPL", name: "Apple", price: "198,42", change: "+0,8%", volume: "52,3M", mcap: "3,05T", tone: "up" as const },
  { symbol: "MSFT", name: "Microsoft", price: "412,36", change: "+1,4%", volume: "28,1M", mcap: "3,06T", tone: "up" as const },
  { symbol: "NVDA", name: "NVIDIA", price: "874,16", change: "+2,1%", volume: "61,8M", mcap: "2,15T", tone: "up" as const },
  { symbol: "TSLA", name: "Tesla", price: "248,70", change: "−0,9%", volume: "84,2M", mcap: "792B", tone: "down" as const },
  { symbol: "SPX", name: "S&P 500", price: "5.412", change: "+0,6%", volume: "—", mcap: "—", tone: "up" as const },
  { symbol: "EURUSD", name: "Euro / USD", price: "1,0864", change: "−0,3%", volume: "—", mcap: "—", tone: "down" as const },
  { symbol: "GOLD", name: "Goud", price: "2.348", change: "+0,4%", volume: "—", mcap: "—", tone: "up" as const },
  { symbol: "BRENT", name: "Brent", price: "86,42", change: "−1,1%", volume: "—", mcap: "—", tone: "down" as const },
];

export const TC_MD_CHART = {
  labels: ["10 apr", "11 apr", "12 apr", "13 apr", "14 apr", "15 apr", "16 apr"],
  series: [48, 52, 50, 58, 62, 70, 78, 74, 82, 88],
};

export const TC_MD_FEEDS = [
  { name: "Binance Feed", latency: "32 ms" },
  { name: "Coinbase Feed", latency: "41 ms" },
  { name: "TradFi (ICE/NYSE)", latency: "28 ms" },
  { name: "News API", latency: "120 ms" },
  { name: "Macro Data (FRED)", latency: "420 ms" },
  { name: "On-chain Data", latency: "85 ms" },
];

export const TC_MD_FEED_HEALTH = [
  { name: "Binance", status: "Online" },
  { name: "Coinbase", status: "Online" },
  { name: "NYSE (ICE)", status: "Online" },
  { name: "Nasdaq (UTP)", status: "Online" },
  { name: "Alpha Vantage", status: "Online" },
  { name: "Financial Times", status: "Online" },
];

export const TC_MD_ACTIONS = [
  { id: "feed", label: "Feed toevoegen", icon: "plus" },
  { id: "alert", label: "Alert instellen", icon: "bolt" },
  { id: "snap", label: "Snapshot", icon: "image" },
  { id: "export", label: "Export data", icon: "save" },
];

/* ─── Strategieën ───────────────────────────────────────────── */

export const TC_STRAT_KPIS: TcKpi[] = [
  { id: "active", label: "Actieve strategieën", value: "12", hint: "▲ +2", tone: "up", spark: [40, 45, 50, 55, 58, 62, 68, 72], icon: "list" },
  { id: "win", label: "Win rate (gem.)", value: "64,3%", hint: "▲ +2,8%", tone: "up", spark: [50, 52, 55, 54, 58, 60, 62, 66], icon: "target" },
  { id: "exp", label: "Gem. expectancy", value: "+0,42R", hint: "▲ +0,08", tone: "up", spark: [35, 40, 42, 45, 48, 52, 55, 60], icon: "chart" },
  { id: "rr", label: "Risk / Reward", value: "2,31", hint: "▲ +0,21", tone: "up", spark: [45, 48, 50, 52, 55, 58, 60, 64], icon: "shield" },
  { id: "sharpe", label: "Sharpe ratio", value: "1,42", hint: "▲ +0,18", tone: "up", spark: [40, 44, 48, 50, 55, 58, 62, 68], icon: "bolt" },
  { id: "live", label: "Live kandidaten", value: "3", hint: "▲ +1", tone: "up", spark: [20, 25, 28, 30, 35, 40, 45, 50], icon: "users" },
];

export const TC_STRAT_CATALOG = [
  { id: "mb", name: "Momentum Breakout", type: "Trend", market: "BTC/USD", tf: "1H", win: "67,2%", exp: "+0,58R", status: "Actief", statusTone: "green" as TcPillTone },
  { id: "mr", name: "Mean Reversion Pro", type: "MR", market: "ETH/USD", tf: "15m", win: "61,4%", exp: "+0,38R", status: "Paper", statusTone: "blue" as TcPillTone },
  { id: "pt", name: "Pairs Trading", type: "Pairs", market: "BTC-ETH", tf: "4H", win: "58,9%", exp: "+0,31R", status: "Actief", statusTone: "green" as TcPillTone },
  { id: "sa", name: "Sentiment Alpha", type: "NLP", market: "SPX", tf: "1D", win: "55,2%", exp: "+0,22R", status: "Testen", statusTone: "gold" as TcPillTone },
  { id: "bs", name: "Breakout Scalper", type: "Scalp", market: "NVDA", tf: "5m", win: "63,0%", exp: "+0,41R", status: "Paper", statusTone: "blue" as TcPillTone },
  { id: "mo", name: "Macro Overlay", type: "Macro", market: "Multi", tf: "1D", win: "52,1%", exp: "+0,18R", status: "Ontwerp", statusTone: "gray" as TcPillTone },
];

export const TC_STRAT_PERF = {
  labels: ["jan", "feb", "mrt", "apr"],
  series: {
    momentum: [40, 48, 52, 55, 60, 65, 70, 74, 78, 82, 86, 90],
    meanRev: [35, 40, 45, 48, 52, 55, 58, 62, 65, 68, 72, 75],
    pairs: [30, 35, 38, 42, 48, 50, 55, 58, 62, 66, 70, 74],
    hold: [42, 44, 46, 48, 50, 52, 54, 56, 58, 60, 62, 64],
  },
};

export const TC_STRAT_VALIDATION = [
  { label: "Win rate", value: "64,3%", hint: "+2,8%", tone: "up" as TcTone },
  { label: "Profit factor", value: "1,87", hint: "+0,4", tone: "up" as TcTone },
  { label: "Expectancy", value: "+0,42R", hint: "+0,08", tone: "up" as TcTone },
  { label: "Max. drawdown", value: "−6,8%", hint: "−2,1%", tone: "down" as TcTone },
];

export const TC_STRAT_CHECKS = [
  { label: "Out-of-sample (OOS)", status: "Geslaagd" },
  { label: "Walk-forward", status: "Geslaagd" },
  { label: "Monte Carlo", status: "Robuust" },
  { label: "Regime filter", status: "Geslaagd" },
  { label: "Overfitting score", status: "Binnen limiet" },
];

export const TC_STRAT_LOGIC = [
  { step: 1, title: "Trend Filter", detail: "EMA(20) > EMA(50)", status: "Actief" },
  { step: 2, title: "Entry Conditie", detail: "Breakout + volume", status: "Actief" },
  { step: 3, title: "Exit Conditie", detail: "ATR trail / TP 2R", status: "Actief" },
  { step: 4, title: "Risk Management", detail: "Max 2% positie", status: "Actief" },
  { step: 5, title: "Regime Filter", detail: "Vol filter AAN", status: "Actief" },
];

export const TC_STRAT_VERSIONS = [
  { ver: "v2.1", market: "BTC/USD", env: "Live", pnl: "+12,4%" },
  { ver: "v1.3", market: "ETH/USD", env: "Paper", pnl: "+4,1%" },
  { ver: "v2.0", market: "NVDA", env: "Paper", pnl: "+6,8%" },
  { ver: "v0.9", market: "SPX", env: "Test", pnl: "+1,5%" },
];

export const TC_STRAT_PARAMS = [
  { id: "emaF", label: "EMA Fast", value: 20, max: 50 },
  { id: "emaS", label: "EMA Slow", value: 50, max: 200 },
  { id: "atr", label: "ATR Periode", value: 14, max: 40 },
  { id: "vol", label: "Volume mult.", value: 1.5, max: 5, step: 0.1 },
];

export const TC_STRAT_AGENTS = [
  { name: "Strategie Engine", detail: "12 actief" },
  { name: "Backtest Engine", detail: "Idle" },
  { name: "Validatie Service", detail: "OK" },
  { name: "Risk Monitor", detail: "Actief" },
  { name: "Deployment Manager", detail: "3 live" },
  { name: "Performance Analytics", detail: "Synced" },
];

export const TC_STRAT_ACTIONS = [
  { id: "new", label: "Nieuwe strategie", icon: "plus" },
  { id: "clone", label: "Clone strategie", icon: "file" },
  { id: "val", label: "Valideren", icon: "check" },
  { id: "deploy", label: "Deploy paper", icon: "bolt" },
];

/* ─── Paper trading ─────────────────────────────────────────── */

export const TC_PAPER_KPIS: TcKpi[] = [
  { id: "equity", label: "Virtueel vermogen", value: "€ 100.000", hint: "▲ +0,8%", tone: "up", spark: [48, 50, 52, 51, 54, 56, 58, 60], icon: "database" },
  { id: "open", label: "Open paper trades", value: "7", hint: "▲ +2", tone: "up", spark: [30, 35, 40, 42, 48, 52, 55, 60], icon: "list" },
  { id: "rpnl", label: "Gerealiseerde P&L", value: "+€ 1.284", hint: "▲ +2,6%", tone: "up", spark: [35, 40, 45, 50, 55, 60, 68, 75], icon: "chart" },
  { id: "upnl", label: "Ongerealiseerde P&L", value: "+€ 432", hint: "▲ +0,9%", tone: "up", spark: [40, 42, 45, 48, 50, 52, 55, 58], icon: "line" },
  { id: "fill", label: "Fill kwaliteit", value: "98,4%", hint: "▲ +0,7%", tone: "up", spark: [90, 91, 92, 93, 94, 95, 96, 98], icon: "target" },
  { id: "sess", label: "Actieve sessies", value: "2", hint: "▲ +1", tone: "up", spark: [20, 25, 28, 30, 35, 40, 45, 50], icon: "users" },
];

export const TC_PAPER_ACCOUNT = {
  start: "€ 100.000",
  equity: "€ 101.716",
  totalPnl: "+€ 1.716 / +1,72%",
  available: "€ 89.430",
  margin: "€ 12.286",
  buyingPower: "€ 200.000",
  status: "Actief",
  type: "Paper trading",
  env: "Live feeds (gesimuleerd)",
  reset: "12 apr 2025",
  currency: "EUR",
  leverage: "1:1",
  id: "PAPER-7843",
};

export const TC_PAPER_POSITIONS = [
  { symbol: "AAPL", side: "LONG", qty: "100", entry: "192,40", last: "198,42", pnl: "+€ 602", pnlPct: "+3,1%", tone: "up" as const },
  { symbol: "NVDA", side: "LONG", qty: "20", entry: "810,00", last: "874,16", pnl: "+€ 1.283", pnlPct: "+7,9%", tone: "up" as const },
  { symbol: "EURUSD", side: "SHORT", qty: "50k", entry: "1,0890", last: "1,0864", pnl: "+€ 130", pnlPct: "+0,2%", tone: "up" as const },
  { symbol: "BTCUSD", side: "LONG", qty: "0,25", entry: "81.200", last: "84.312", pnl: "+€ 778", pnlPct: "+3,8%", tone: "up" as const },
  { symbol: "ETHUSD", side: "LONG", qty: "2", entry: "3.050", last: "3.128", pnl: "+€ 156", pnlPct: "+2,6%", tone: "up" as const },
  { symbol: "TSLA", side: "SHORT", qty: "40", entry: "255,00", last: "248,70", pnl: "+€ 252", pnlPct: "+2,5%", tone: "up" as const },
  { symbol: "MSFT", side: "LONG", qty: "30", entry: "405,00", last: "412,36", pnl: "+€ 221", pnlPct: "+1,8%", tone: "up" as const },
];

export const TC_PAPER_JOURNAL = [
  { time: "14:22", symbol: "AAPL", action: "BUY", qty: "100", price: "198,50", pnl: "+€ 42", note: "Breakout setup" },
  { time: "13:58", symbol: "NVDA", action: "BUY", qty: "10", price: "870,20", pnl: "+€ 118", note: "Trendvolgend" },
  { time: "13:10", symbol: "EURUSD", action: "SELL", qty: "50k", price: "1,0872", pnl: "+€ 65", note: "Mean reversion" },
  { time: "12:44", symbol: "BTCUSD", action: "BUY", qty: "0,1", price: "83.900", pnl: "+€ 41", note: "AI momentum" },
  { time: "11:30", symbol: "TSLA", action: "SELL", qty: "40", price: "252,10", pnl: "+€ 88", note: "Fade gap" },
];

export const TC_PAPER_PERF = {
  labels: ["jan", "feb", "mrt", "apr"],
  series: {
    account: [48, 50, 52, 51, 54, 56, 58, 60, 62, 64, 66, 68],
    realized: [45, 46, 48, 50, 52, 54, 55, 56, 58, 59, 60, 62],
    spy: [48, 49, 50, 51, 52, 52, 53, 54, 55, 55, 56, 57],
  },
};

export const TC_PAPER_EXEC = [
  { time: "14:22:08", symbol: "AAPL", side: "BUY", qty: "100", price: "198,50", venue: "NASDAQ" },
  { time: "13:58:41", symbol: "NVDA", side: "BUY", qty: "10", price: "870,20", venue: "NASDAQ" },
  { time: "13:10:15", symbol: "EURUSD", side: "SELL", qty: "50k", price: "1,0872", venue: "FOREX" },
  { time: "12:44:02", symbol: "BTCUSD", side: "BUY", qty: "0,1", price: "83.900", venue: "BINANCE" },
  { time: "11:30:55", symbol: "TSLA", side: "SELL", qty: "40", price: "252,10", venue: "NASDAQ" },
];

export const TC_PAPER_VENUES = ["NYSE", "NASDAQ", "CME", "BINANCE", "COINBASE", "FOREX"];

export const TC_PAPER_ACTIONS = [
  { id: "order", label: "Nieuwe order", icon: "plus" },
  { id: "reset", label: "Reset account", icon: "bolt" },
  { id: "import", label: "Import setup", icon: "folder" },
  { id: "sess", label: "Sessies openen", icon: "users" },
];

/* ─── Portefeuille ──────────────────────────────────────────── */

export const TC_PORT_KPIS: TcKpi[] = [
  { id: "value", label: "Totale waarde", value: "€ 128.430", hint: "▲ +2,8%", tone: "up", spark: [40, 45, 50, 55, 58, 62, 70, 78], icon: "database" },
  { id: "day", label: "Dagresultaat", value: "€ +1.284", hint: "▲ +1,01%", tone: "up", spark: [35, 40, 42, 50, 55, 60, 68, 75], icon: "chart" },
  { id: "cash", label: "Cash", value: "€ 15.920", hint: "0,0%", tone: "flat", spark: [50, 50, 50, 50, 50, 50, 50, 50], icon: "file" },
  { id: "exp", label: "Exposure", value: "84,1%", hint: "▲ +1,2%", tone: "up", spark: [70, 72, 74, 76, 78, 80, 82, 84], icon: "target" },
  { id: "open", label: "Open posities", value: "18", hint: "▲ +2", tone: "up", spark: [40, 42, 45, 48, 50, 52, 55, 58], icon: "list" },
  { id: "reb", label: "Rebalance signaal", value: "2", hint: "Actief", tone: "warn", spark: [20, 25, 30, 28, 35, 40, 45, 50], icon: "bolt" },
];

export const TC_PORT_ALLOCATION = [
  { label: "Aandelen", count: 382, color: "#1aa4ff", pct: "38,2%" },
  { label: "ETF's", count: 246, color: "#8d67ff", pct: "24,6%" },
  { label: "Crypto", count: 121, color: "#f0b429", pct: "12,1%" },
  { label: "Cash", count: 124, color: "#39c8c4", pct: "12,4%" },
  { label: "Opties", count: 89, color: "#20e38d", pct: "8,9%" },
  { label: "Obligaties", count: 38, color: "#c66965", pct: "3,8%" },
];

export const TC_PORT_POSITIONS = [
  { symbol: "AAPL", name: "Apple", qty: "120", avg: "169,20", last: "198,42", value: "€ 23.810", pnl: "+€ 3.506", pnlPct: "+17,3%", tone: "up" as const },
  { symbol: "NVDA", name: "NVIDIA", qty: "25", avg: "680,00", last: "874,16", value: "€ 21.854", pnl: "+€ 4.854", pnlPct: "+28,6%", tone: "up" as const },
  { symbol: "MSFT", name: "Microsoft", qty: "40", avg: "380,00", last: "412,36", value: "€ 16.494", pnl: "+€ 1.294", pnlPct: "+8,5%", tone: "up" as const },
  { symbol: "BTC", name: "Bitcoin", qty: "0,18", avg: "78.200", last: "84.312", value: "€ 15.176", pnl: "+€ 1.100", pnlPct: "+7,7%", tone: "up" as const },
  { symbol: "ETH", name: "Ethereum", qty: "2,4", avg: "2.980", last: "3.128", value: "€ 7.507", pnl: "+€ 355", pnlPct: "+5,0%", tone: "up" as const },
  { symbol: "QQQ", name: "Invesco QQQ", qty: "35", avg: "420,00", last: "448,20", value: "€ 15.687", pnl: "+€ 987", pnlPct: "+6,7%", tone: "up" as const },
  { symbol: "TLT", name: "iShares 20+Y", qty: "80", avg: "98,40", last: "93,60", value: "€ 7.488", pnl: "−€ 384", pnlPct: "−4,9%", tone: "down" as const },
  { symbol: "GLD", name: "SPDR Gold", qty: "40", avg: "210,00", last: "218,40", value: "€ 8.736", pnl: "+€ 336", pnlPct: "+4,0%", tone: "up" as const },
];

export const TC_PORT_SECTORS = [
  { label: "Technologie", pct: 34.8 },
  { label: "Communicatie", pct: 12.4 },
  { label: "Financieel", pct: 11.2 },
  { label: "Consumer Disc.", pct: 9.8 },
  { label: "Gezondheid", pct: 8.6 },
  { label: "Industrie", pct: 7.2 },
  { label: "Overig", pct: 16.0 },
];

export const TC_PORT_PERF = {
  labels: ["jan", "feb", "mrt", "apr"],
  series: {
    total: [40, 45, 50, 52, 58, 62, 68, 72, 75, 80, 84, 88],
    equity: [38, 42, 48, 50, 55, 60, 65, 70, 72, 76, 80, 84],
    crypto: [30, 40, 35, 50, 45, 60, 70, 65, 75, 82, 78, 90],
    etf: [42, 44, 46, 48, 50, 52, 54, 56, 58, 60, 62, 64],
  },
};

export const TC_PORT_REBALANCE = [
  { title: "Verlaag NVDA", reason: "Te hoge weging", action: "Verkopen", tone: "red" },
  { title: "Verhoog Cash", reason: "Onder minimum", action: "Kopen", tone: "green" },
  { title: "Herbalanceer Tech", reason: "Sector weging te hoog", action: "Heralloceren", tone: "gold" },
  { title: "Overweeg obligaties", reason: "Beperkte spreiding", action: "Overwegen", tone: "blue" },
  { title: "Neem winst op BTC", reason: "Sterke stijging", action: "Winst nemen", tone: "orange" },
];

export const TC_PORT_HEALTH = [
  { k: "Risico (VaR 95%)", v: "2,4%" },
  { k: "Max. drawdown", v: "−6,8%" },
  { k: "Sharpe ratio", v: "1,42" },
  { k: "Sortino ratio", v: "2,11" },
  { k: "Beta (vs. S&P500)", v: "0,87" },
];

export const TC_PORT_CONCENTRATION = [
  { k: "Hoogste positie", v: "17,0%" },
  { k: "Top 5 posities", v: "62,4%" },
  { k: "Sector concentratie", v: "34,8%" },
  { k: "Valuta risico", v: "Laag", tone: "green" as const },
];

export const TC_PORT_AGENTS = [
  { name: "Portfolio Agent", detail: "Synced" },
  { name: "Risk Manager", detail: "VaR ok" },
  { name: "Rebalance Engine", detail: "2 signalen" },
  { name: "Performance Analyst", detail: "Actief" },
  { name: "Allocatie Optimizer", detail: "Idle" },
  { name: "News & Sentiment", detail: "Pulse 0,28" },
];

export const TC_PORT_ACTIONS = [
  { id: "reb", label: "Rebalancen", icon: "bolt" },
  { id: "exp", label: "Positie exporteren", icon: "save" },
  { id: "alloc", label: "Nieuwe allocatie", icon: "settings" },
  { id: "sync", label: "Broker sync", icon: "link" },
];

/* ─── Broker trading (optional) ─────────────────────────────── */

export const TC_BROKER_KPIS: TcKpi[] = [
  { id: "conn", label: "Verbonden brokers", value: "4 / 5", hint: "▲ +1", tone: "up", spark: [40, 45, 50, 55, 60, 65, 70, 75], icon: "link" },
  { id: "live", label: "Live orders", value: "23", hint: "▲ +5", tone: "up", spark: [30, 35, 40, 45, 50, 55, 60, 70], icon: "list" },
  { id: "filled", label: "Uitgevoerde orders (vandaag)", value: "118", hint: "▲ +18", tone: "up", spark: [40, 48, 55, 60, 65, 72, 78, 85], icon: "check" },
  { id: "slip", label: "Gem. slippage (bps)", value: "0,6", hint: "▼ −0,4", tone: "up", spark: [80, 70, 65, 55, 50, 45, 40, 35], icon: "line" },
  { id: "pnl", label: "Gerealiseerde P&L (vandaag)", value: "+€ 2.430", hint: "▲ +12,8%", tone: "up", spark: [30, 40, 45, 55, 60, 70, 78, 88], icon: "chart" },
  { id: "lat", label: "Executie latency (ms)", value: "12,4", hint: "▼ −3,1", tone: "up", spark: [70, 65, 60, 55, 50, 45, 40, 35], icon: "bolt" },
];

export const TC_BROKER_CONNECTIONS = [
  { name: "Interactive Brokers", status: "Verbonden", statusTone: "green" as TcPillTone, type: "TWS", regio: "US", latency: "8 ms", updated: "14:37:20" },
  { name: "Saxo Bank", status: "Verbonden", statusTone: "green" as TcPillTone, type: "FIX", regio: "EU", latency: "14 ms", updated: "14:37:18" },
  { name: "Binance", status: "Verbonden", statusTone: "green" as TcPillTone, type: "REST", regio: "Global", latency: "22 ms", updated: "14:37:22" },
  { name: "Coinbase", status: "Verbonden", statusTone: "green" as TcPillTone, type: "REST", regio: "US", latency: "19 ms", updated: "14:37:21" },
  { name: "DeGiro", status: "Verbroken", statusTone: "red" as TcPillTone, type: "API", regio: "EU", latency: "—", updated: "13:02:11" },
];

export const TC_BROKER_BLOTTER = [
  { time: "14:36:52", symbol: "AAPL", side: "BUY", type: "LMT", qty: "100", price: "198,40", status: "Uitgevoerd", statusTone: "green" as TcPillTone },
  { time: "14:35:10", symbol: "NVDA", side: "BUY", type: "MKT", qty: "25", price: "874,10", status: "Uitgevoerd", statusTone: "green" as TcPillTone },
  { time: "14:33:44", symbol: "EURUSD", side: "SELL", type: "LMT", qty: "50k", price: "1,0865", status: "Open", statusTone: "blue" as TcPillTone },
  { time: "14:31:02", symbol: "BTCUSDT", side: "BUY", type: "LMT", qty: "0,5", price: "84.300", status: "Gedeeltelijk", statusTone: "gold" as TcPillTone },
  { time: "14:28:18", symbol: "MSFT", side: "SELL", type: "LMT", qty: "40", price: "413,00", status: "Open", statusTone: "blue" as TcPillTone },
  { time: "14:22:05", symbol: "TSLA", side: "BUY", type: "MKT", qty: "30", price: "248,70", status: "Uitgevoerd", statusTone: "green" as TcPillTone },
  { time: "14:15:41", symbol: "QQQ", side: "BUY", type: "LMT", qty: "50", price: "448,00", status: "Geannuleerd", statusTone: "gray" as TcPillTone },
  { time: "14:10:12", symbol: "ETHUSDT", side: "SELL", type: "MKT", qty: "2", price: "3.128", status: "Uitgevoerd", statusTone: "green" as TcPillTone },
];

export const TC_BROKER_BALANCES = [
  { broker: "Interactive Brokers", ccy: "EUR", saldo: "52.430", beschikbaar: "38.120", marge: 28 },
  { broker: "Saxo Bank", ccy: "EUR", saldo: "24.810", beschikbaar: "18.400", marge: 22 },
  { broker: "Binance", ccy: "USDT", saldo: "28.910", beschikbaar: "21.500", marge: 35 },
  { broker: "Coinbase", ccy: "USD", saldo: "21.340", beschikbaar: "16.800", marge: 18 },
  { broker: "DeGiro", ccy: "EUR", saldo: "25.750", beschikbaar: "0", marge: 0 },
];

export const TC_BROKER_PNL_SERIES = {
  labels: ["09:00", "11:00", "13:00", "15:00", "16:00"],
  series: {
    total: [40, 48, 55, 52, 60, 68, 72, 78, 82, 88],
    realized: [38, 42, 48, 50, 55, 60, 65, 70, 74, 80],
  },
};

export const TC_BROKER_EXEC_STATS = [
  { label: "Gem. executietijd", value: "14,2 ms", hint: "−2,1", spark: [60, 55, 50, 48, 45, 42, 40, 38] },
  { label: "Gem. slippage", value: "0,6 bps", hint: "−0,4", spark: [70, 65, 55, 50, 45, 40, 35, 32] },
  { label: "Succesratio", value: "99,2%", hint: "+0,3%", spark: [90, 92, 93, 94, 95, 96, 97, 99] },
  { label: "Reject ratio", value: "0,8%", hint: "−0,2%", spark: [40, 38, 35, 32, 30, 28, 25, 22] },
];

export const TC_BROKER_LATENCY_BARS = [
  { name: "IBKR", ms: 8 },
  { name: "Saxo", ms: 14 },
  { name: "Binance", ms: 22 },
  { name: "Coinbase", ms: 19 },
  { name: "DeGiro", ms: 0 },
];

export const TC_BROKER_GATEWAYS = [
  { name: "IBKR Gateway", detail: "TWS API · Low latency", active: true },
  { name: "Saxo Connector", detail: "FIX · EU", active: true },
  { name: "Binance Gateway", detail: "REST API · Crypto", active: true },
  { name: "Coinbase Gateway", detail: "REST API · Crypto", active: true },
  { name: "DeGiro Bridge", detail: "API · Offline", active: false },
];

export const TC_BROKER_ACTIONS = [
  { id: "connect", label: "Broker verbinden", icon: "link" },
  { id: "order", label: "Live order", icon: "bolt" },
  { id: "kill", label: "Kill switch", icon: "shield" },
  { id: "risk", label: "Risico limiet", icon: "settings" },
];
