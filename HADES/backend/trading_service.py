from __future__ import annotations

import asyncio
import csv
import io
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from platform_db import PlatformDatabase, new_id, utc_now


_UNSET = object()


def _setting(name: str, fallback: Any) -> Any:
    try:
        from control.service import resolve_setting

        return resolve_setting(name, default=fallback)
    except Exception:
        return fallback


def _as_bool(value: Any) -> bool:
    return bool(int(value)) if value is not None else False


def _sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 0:
        return out
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        if index >= window - 1:
            out[index] = total / window
    return out


def _std(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 1:
        return out
    for index in range(window - 1, len(values)):
        chunk = values[index - window + 1 : index + 1]
        mean = sum(chunk) / window
        variance = sum((item - mean) ** 2 for item in chunk) / (window - 1)
        out[index] = math.sqrt(max(0.0, variance))
    return out


@dataclass(frozen=True)
class Bar:
    symbol: str
    timeframe: str
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str = "synthetic"


class PaperTradingService:
    """Strict PAPER-only spot simulator. No network, broker API or real-money execution paths exist here."""

    def __init__(self, db: PlatformDatabase) -> None:
        self.db = db

    def state(self) -> dict[str, Any]:
        with self.db.connection() as db:
            settings = dict(db.execute("SELECT * FROM paper_trading_settings WHERE id=1").fetchone())
            wallets = [dict(row) for row in db.execute("SELECT * FROM paper_wallets ORDER BY asset").fetchall()]
            positions = [dict(row) for row in db.execute("SELECT * FROM paper_positions ORDER BY opened_at DESC").fetchall()]
            orders = [dict(row) for row in db.execute("SELECT * FROM paper_orders ORDER BY created_at DESC LIMIT 200").fetchall()]
            events = [dict(row) for row in db.execute("SELECT * FROM trading_events ORDER BY id DESC LIMIT 200").fetchall()]
        settings["enabled"] = bool(settings["enabled"])
        settings["kill_switch"] = bool(settings["kill_switch"])
        return {"settings": settings, "wallets": wallets, "positions": positions, "orders": orders, "events": events}

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        now = utc_now()
        with self.db.connection() as db:
            db.execute("UPDATE paper_trading_settings SET enabled=?,updated_at=? WHERE id=1", (int(enabled), now))
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES(?,?,?)",
                ("info", f"Paper trading {'ingeschakeld' if enabled else 'uitgeschakeld'}.", now),
            )
        return self.state()

    def set_kill_switch(self, armed: bool) -> dict[str, Any]:
        now = utc_now()
        with self.db.connection() as db:
            db.execute("UPDATE paper_trading_settings SET kill_switch=?,updated_at=? WHERE id=1", (int(armed), now))
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES(?,?,?)",
                ("warning" if armed else "info", f"Kill switch {'geactiveerd' if armed else 'vrijgegeven'}.", now),
            )
        return self.state()

    def reset(self, balance: float = 10_000.0) -> dict[str, Any]:
        if balance <= 0:
            raise ValueError("Startsaldo moet groter zijn dan nul.")
        now = utc_now()
        with self.db.connection() as db:
            db.execute("DELETE FROM paper_orders")
            db.execute("DELETE FROM paper_positions")
            db.execute("DELETE FROM trading_events")
            db.execute("DELETE FROM paper_wallets")
            db.execute("INSERT INTO paper_wallets(asset,balance,reserved,updated_at) VALUES('USDT',?,0,?)", (balance, now))
            db.execute("UPDATE paper_trading_settings SET enabled=0,kill_switch=0,updated_at=? WHERE id=1", (now,))
            db.execute("INSERT INTO trading_events(level,message,created_at) VALUES('info',?,?)", (f"Paper account gereset naar {balance:.2f} USDT.", now))
        return self.state()

    def buy(self, symbol: str, quantity: float, price: float) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if not symbol or quantity <= 0 or price <= 0:
            raise ValueError("Symbool, hoeveelheid en prijs moeten geldig zijn.")
        now = utc_now()
        notional = quantity * price
        position_id = new_id("pos")
        order_id = new_id("order")
        with self.db.connection() as db:
            settings = db.execute("SELECT enabled,kill_switch FROM paper_trading_settings WHERE id=1").fetchone()
            if not settings or not settings["enabled"]:
                raise RuntimeError("Paper trading staat uit.")
            if settings["kill_switch"]:
                raise RuntimeError("Kill switch is actief; nieuwe paperorders zijn geblokkeerd.")
            wallet = db.execute("SELECT balance FROM paper_wallets WHERE asset='USDT'").fetchone()
            if not wallet or float(wallet["balance"]) + 1e-9 < notional:
                raise RuntimeError("Onvoldoende PAPER-USDT saldo.")
            db.execute("UPDATE paper_wallets SET balance=balance-?,updated_at=? WHERE asset='USDT'", (notional, now))
            db.execute(
                """INSERT INTO paper_positions(id,symbol,side,quantity,entry_price,cost_basis,status,realized_pnl,opened_at)
                   VALUES(?,?,?,?,?,?, 'open',0,?)""",
                (position_id, symbol, "long", quantity, price, notional, now),
            )
            db.execute(
                """INSERT INTO paper_orders(id,symbol,side,quantity,price,notional,status,position_id,created_at)
                   VALUES(?,?,?,?,?,?,'filled',?,?)""",
                (order_id, symbol, "buy", quantity, price, notional, position_id, now),
            )
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES('success',?,?)",
                (
                    f"PAPER BUY {quantity:g} {symbol} @ {price:.8f} uitgevoerd "
                    f"(price_source=operator_input).",
                    now,
                ),
            )
        return {
            "order_id": order_id,
            "position_id": position_id,
            "price_source": "operator_input",
            "simulation_layer": "legacy_paper_desk",
            "state": self.state(),
        }

    def close(self, position_id: str, price: float) -> dict[str, Any]:
        if price <= 0:
            raise ValueError("Sluitprijs moet groter zijn dan nul.")
        now = utc_now()
        order_id = new_id("order")
        with self.db.connection() as db:
            settings = db.execute("SELECT enabled FROM paper_trading_settings WHERE id=1").fetchone()
            if not settings or not settings["enabled"]:
                raise RuntimeError("Paper trading staat uit.")
            position = db.execute("SELECT * FROM paper_positions WHERE id=?", (position_id,)).fetchone()
            if not position:
                raise KeyError(position_id)
            if position["status"] != "open":
                raise RuntimeError("Positie is al gesloten.")
            quantity = float(position["quantity"])
            proceeds = quantity * price
            pnl = proceeds - float(position["cost_basis"])
            db.execute("UPDATE paper_wallets SET balance=balance+?,updated_at=? WHERE asset='USDT'", (proceeds, now))
            cursor = db.execute(
                """UPDATE paper_positions SET status='closed',realized_pnl=?,closed_at=?
                   WHERE id=? AND status='open'""",
                (pnl, now, position_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Positie kon niet atomair worden gesloten.")
            db.execute(
                """INSERT INTO paper_orders(id,symbol,side,quantity,price,notional,status,position_id,created_at)
                   VALUES(?,?,?,?,?,?,'filled',?,?)""",
                (order_id, position["symbol"], "sell", quantity, price, proceeds, position_id, now),
            )
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES('success',?,?)",
                (
                    f"PAPER CLOSE {quantity:g} {position['symbol']} @ {price:.8f}; "
                    f"PnL {pnl:+.2f} USDT (price_source=operator_input).",
                    now,
                ),
            )
        return {
            "order_id": order_id,
            "realized_pnl": pnl,
            "price_source": "operator_input",
            "simulation_layer": "legacy_paper_desk",
            "state": self.state(),
        }


class TradingBotService:
    """Offline PAPER trading bot: market bars, deterministic strategies, discovery, knowledge retention."""

    STRATEGY_KINDS = ("sma_crossover", "momentum", "mean_reversion")

    def __init__(self, db: PlatformDatabase, paper: PaperTradingService, knowledge: Any | None = None) -> None:
        self.db = db
        self.paper = paper
        self.knowledge = knowledge

    # --- Market data -----------------------------------------------------------------

    def list_symbols(self) -> list[dict[str, Any]]:
        with self.db.connection() as db:
            # last_close must be the close of the newest bar, not the highest close in the
            # series: MAX(close) silently reported an all-time high as the current price.
            rows = db.execute(
                """SELECT b.symbol, b.timeframe, COUNT(*) AS bars,
                          MIN(b.ts) AS first_ts, MAX(b.ts) AS last_ts,
                          (SELECT l.close FROM market_bars l
                            WHERE l.symbol=b.symbol AND l.timeframe=b.timeframe
                            ORDER BY l.ts DESC LIMIT 1) AS last_close
                   FROM market_bars b GROUP BY b.symbol, b.timeframe ORDER BY b.symbol, b.timeframe"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_bars(self, symbol: str, timeframe: str = "1h", limit: Any = _UNSET) -> list[dict[str, Any]]:
        """Return OHLCV bars.

        - omitted ``limit`` → Control Plane ``trading.default_bars`` (None = Unlimited)
        - explicit ``limit=None`` → Unlimited (no SQL LIMIT)
        - explicit int → that many rows
        """
        symbol = symbol.strip().upper()
        if limit is _UNSET:
            limit = _setting("trading.default_bars", 500)
        with self.db.connection() as db:
            if limit is None:
                rows = db.execute(
                    """SELECT symbol, timeframe, ts, open, high, low, close, volume, source
                       FROM market_bars WHERE symbol=? AND timeframe=?
                       ORDER BY ts DESC""",
                    (symbol, timeframe),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT symbol, timeframe, ts, open, high, low, close, volume, source
                       FROM market_bars WHERE symbol=? AND timeframe=?
                       ORDER BY ts DESC LIMIT ?""",
                    (symbol, timeframe, max(1, int(limit))),
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def clear_bars(self, symbol: str, timeframe: str = "1h") -> int:
        symbol = symbol.strip().upper()
        with self.db.connection() as db:
            cursor = db.execute("DELETE FROM market_bars WHERE symbol=? AND timeframe=?", (symbol, timeframe))
            deleted = cursor.rowcount
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES('info',?,?)",
                (f"Marktbalken verwijderd voor {symbol} {timeframe}: {deleted}.", utc_now()),
            )
        return deleted

    def seed_synthetic(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        bars: int | None = None,
        start_price: float = 100_000.0,
        seed: int = 42,
        replace: bool = True,
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if bars is None:
            resolved = _setting("trading.seed_bars", 720)
            bars = 720 if resolved is None else int(resolved)
        if bars < 50:
            raise ValueError("Minimaal 50 balken vereist voor strategie-analyse.")
        if start_price <= 0:
            raise ValueError("Startprijs moet groter zijn dan nul.")
        rng = random.Random(seed)
        generated: list[Bar] = []
        price = start_price
        # Hourly-ish synthetic series with drift + mean reversion + occasional jumps.
        end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=bars - 1)
        for index in range(bars):
            ts = (start + timedelta(hours=index)).isoformat(timespec="seconds")
            shock = rng.gauss(0.00015, 0.008)
            reversion = (start_price - price) / start_price * 0.01
            jump = rng.choice([0.0, 0.0, 0.0, 0.0, rng.gauss(0, 0.02)])
            next_close = max(1.0, price * (1.0 + shock + reversion + jump))
            high = max(price, next_close) * (1.0 + abs(rng.gauss(0, 0.002)))
            low = min(price, next_close) * (1.0 - abs(rng.gauss(0, 0.002)))
            volume = abs(rng.gauss(50, 12)) * (1.0 + abs(jump) * 20)
            generated.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=ts,
                    open=round(price, 8),
                    high=round(high, 8),
                    low=round(low, 8),
                    close=round(next_close, 8),
                    volume=round(volume, 4),
                    source="synthetic",
                )
            )
            price = next_close
        return self._upsert_bars(generated, replace=replace)

    def import_csv(self, csv_text: str, symbol: str, timeframe: str = "1h", replace: bool = True) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        text = (csv_text or "").strip()
        if not text:
            raise ValueError("CSV-inhoud is leeg.")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV heeft geen header.")
        fields = {name.strip().lower(): name for name in reader.fieldnames if name}
        required = ("open", "high", "low", "close")
        for key in required:
            if key not in fields:
                raise ValueError(f"CSV mist kolom '{key}'.")
        ts_key = next((fields[key] for key in ("ts", "timestamp", "time", "datetime", "date") if key in fields), None)
        if not ts_key:
            raise ValueError("CSV mist een tijdsstempelkolom (ts/timestamp/time/datetime/date).")
        volume_key = fields.get("volume")
        bars: list[Bar] = []
        seen_timestamps: set[str] = set()
        for row in reader:
            try:
                open_px = float(row[fields["open"]])
                high_px = float(row[fields["high"]])
                low_px = float(row[fields["low"]])
                close_px = float(row[fields["close"]])
                volume = float(row[volume_key]) if volume_key and row.get(volume_key) not in (None, "") else 0.0
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Ongeldige OHLCV-rij: {row}") from exc
            if not all(math.isfinite(value) for value in (open_px, high_px, low_px, close_px, volume)):
                raise ValueError(f"Niet-eindige waarde (NaN/inf) in rij: {row}")
            if min(open_px, high_px, low_px, close_px) <= 0:
                raise ValueError("OHLCV-waarden moeten groter zijn dan nul.")
            if volume < 0:
                raise ValueError("Volume mag niet negatief zijn.")
            # Zonder deze controle glipt een omgekeerde high/low erdoor en verzint de
            # backtest fills op prijzen die nooit verhandeld zijn.
            if high_px < max(open_px, close_px) or low_px > min(open_px, close_px) or high_px < low_px:
                raise ValueError(f"Inconsistente OHLC-rij (high/low sluiten open/close niet in): {row}")
            ts_raw = str(row[ts_key]).strip()
            if not ts_raw:
                raise ValueError("Lege tijdsstempel in CSV.")
            if ts_raw in seen_timestamps:
                raise ValueError(f"Dubbele tijdsstempel in CSV: {ts_raw}")
            seen_timestamps.add(ts_raw)
            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=ts_raw,
                    open=open_px,
                    high=high_px,
                    low=low_px,
                    close=close_px,
                    volume=volume,
                    source="csv",
                )
            )
        if len(bars) < 50:
            raise ValueError("Minimaal 50 geldige balken vereist.")
        bars.sort(key=lambda item: item.ts)
        return self._upsert_bars(bars, replace=replace)

    def _upsert_bars(self, bars: list[Bar], *, replace: bool) -> dict[str, Any]:
        if not bars:
            raise ValueError("Geen balken om op te slaan.")
        symbol = bars[0].symbol
        timeframe = bars[0].timeframe
        now = utc_now()
        with self.db.connection() as db:
            if replace:
                db.execute("DELETE FROM market_bars WHERE symbol=? AND timeframe=?", (symbol, timeframe))
            db.executemany(
                """INSERT OR REPLACE INTO market_bars(symbol,timeframe,ts,open,high,low,close,volume,source)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                [
                    (bar.symbol, bar.timeframe, bar.ts, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.source)
                    for bar in bars
                ],
            )
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES('success',?,?)",
                (f"{len(bars)} marktbalken geladen voor {symbol} {timeframe} ({bars[0].source}).", now),
            )
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": len(bars),
            "first_ts": bars[0].ts,
            "last_ts": bars[-1].ts,
            "last_close": bars[-1].close,
            "source": bars[0].source,
        }

    # --- Strategies ------------------------------------------------------------------

    def list_strategies(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connection() as db:
            rows = db.execute(
                """SELECT * FROM trading_strategies ORDER BY score DESC, updated_at DESC LIMIT ?""",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._strategy_row(row) for row in rows]

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        with self.db.connection() as db:
            row = db.execute("SELECT * FROM trading_strategies WHERE id=?", (strategy_id,)).fetchone()
        return self._strategy_row(row) if row else None

    def _strategy_row(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["params"] = json.loads(item.pop("params_json") or "{}")
        item["metrics"] = json.loads(item.pop("metrics_json") or "{}")
        return item

    def list_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.db.connection() as db:
            rows = db.execute(
                "SELECT * FROM trading_strategy_runs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [self._run_row(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.db.connection() as db:
            row = db.execute("SELECT * FROM trading_strategy_runs WHERE id=?", (run_id,)).fetchone()
        return self._run_row(row) if row else None

    def _run_row(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json") or "{}")
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

    def bot_settings(self) -> dict[str, Any]:
        with self.db.connection() as db:
            row = db.execute("SELECT * FROM trading_bot_settings WHERE id=1").fetchone()
        settings = dict(row)
        settings["enabled"] = _as_bool(settings["enabled"])
        return settings

    def set_bot_settings(
        self,
        *,
        enabled: bool | None = None,
        strategy_id: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        position_fraction: float | None = None,
        clear_strategy: bool = False,
    ) -> dict[str, Any]:
        current = self.bot_settings()
        now = utc_now()
        next_enabled = current["enabled"] if enabled is None else bool(enabled)
        next_strategy = None if clear_strategy else (strategy_id if strategy_id is not None else current.get("strategy_id"))
        next_symbol = (symbol or current["symbol"]).strip().upper()
        next_timeframe = timeframe or current["timeframe"]
        next_fraction = current["position_fraction"] if position_fraction is None else float(position_fraction)
        if not 0.01 <= next_fraction <= 1.0:
            raise ValueError("position_fraction moet tussen 0.01 en 1.0 liggen.")
        if next_strategy:
            strategy = self.get_strategy(next_strategy)
            if not strategy:
                raise KeyError(next_strategy)
        with self.db.connection() as db:
            db.execute(
                """UPDATE trading_bot_settings
                   SET enabled=?, strategy_id=?, symbol=?, timeframe=?, position_fraction=?, updated_at=?
                   WHERE id=1""",
                (int(next_enabled), next_strategy, next_symbol, next_timeframe, next_fraction, now),
            )
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES(?,?,?)",
                (
                    "info",
                    f"Trading bot {'aan' if next_enabled else 'uit'}; strategie={next_strategy or 'geen'}; {next_symbol} {next_timeframe}.",
                    now,
                ),
            )
        return self.bot_settings()

    def create_run(self, *, kind: str, symbol: str, timeframe: str = "1h", strategy_id: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
        if kind not in {"discover", "backtest", "paper_bot"}:
            raise ValueError("Onbekende run-soort.")
        symbol = symbol.strip().upper()
        bars = self.get_bars(
            symbol,
            timeframe,
            limit=_setting("trading.discover_bars", 5000),
        )
        if len(bars) < 50:
            raise RuntimeError("Onvoldoende marktdata. Seed synthetische data of importeer CSV eerst.")
        run_id = new_id("trun")
        now = utc_now()
        with self.db.connection() as db:
            db.execute(
                """INSERT INTO trading_strategy_runs(
                       id,kind,status,progress,symbol,timeframe,strategy_id,config_json,result_json,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    kind,
                    "queued",
                    0,
                    symbol,
                    timeframe,
                    strategy_id,
                    json.dumps(config or {}, ensure_ascii=False),
                    "{}",
                    now,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES('info',?,?)",
                (f"Trading-run {kind} gepland voor {symbol} ({run_id}).", now),
            )
        return self.get_run(run_id) or {"id": run_id}

    def update_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"status", "progress", "result_json", "error", "knowledge_source_id", "started_at", "finished_at", "strategy_id"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            run = self.get_run(run_id)
            if not run:
                raise KeyError(run_id)
            return run
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in updates)
        with self.db.connection() as db:
            db.execute(f"UPDATE trading_strategy_runs SET {assignments} WHERE id=?", (*updates.values(), run_id))
        run = self.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        return run

    def signals_for(self, kind: str, closes: list[float], params: dict[str, Any]) -> list[int]:
        """Return position target per bar: 1=long, 0=flat."""
        if kind == "sma_crossover":
            fast = int(params.get("fast", 10))
            slow = int(params.get("slow", 30))
            if fast < 2 or slow <= fast:
                raise ValueError("sma_crossover vereist 2 <= fast < slow.")
            fast_sma = _sma(closes, fast)
            slow_sma = _sma(closes, slow)
            signals = [0] * len(closes)
            position = 0
            for index in range(len(closes)):
                if fast_sma[index] is None or slow_sma[index] is None:
                    signals[index] = 0
                    continue
                if fast_sma[index] > slow_sma[index]:
                    position = 1
                elif fast_sma[index] < slow_sma[index]:
                    position = 0
                signals[index] = position
            return signals
        if kind == "momentum":
            lookback = int(params.get("lookback", 20))
            threshold = float(params.get("threshold", 0.01))
            if lookback < 2:
                raise ValueError("momentum lookback moet >= 2 zijn.")
            signals = [0] * len(closes)
            position = 0
            for index in range(len(closes)):
                if index < lookback:
                    signals[index] = 0
                    continue
                change = (closes[index] / closes[index - lookback]) - 1.0
                if change >= threshold:
                    position = 1
                elif change <= -threshold:
                    position = 0
                signals[index] = position
            return signals
        if kind == "mean_reversion":
            window = int(params.get("window", 20))
            z_entry = float(params.get("z_entry", 1.5))
            if window < 5:
                raise ValueError("mean_reversion window moet >= 5 zijn.")
            means = _sma(closes, window)
            stds = _std(closes, window)
            signals = [0] * len(closes)
            position = 0
            for index in range(len(closes)):
                mean = means[index]
                std = stds[index]
                if mean is None or std is None or std <= 1e-12:
                    signals[index] = 0
                    continue
                z = (closes[index] - mean) / std
                if z <= -z_entry:
                    position = 1
                elif z >= 0:
                    position = 0
                signals[index] = position
            return signals
        raise ValueError(f"Onbekende strategie: {kind}")

    def backtest(
        self,
        bars: list[dict[str, Any]],
        *,
        kind: str,
        params: dict[str, Any],
        starting_balance: float = 10_000.0,
        position_fraction: float = 0.95,
    ) -> dict[str, Any]:
        if len(bars) < 50:
            raise ValueError("Te weinig balken voor backtest.")
        closes = [float(bar["close"]) for bar in bars]
        signals = self.signals_for(kind, closes, params)
        cash = float(starting_balance)
        qty = 0.0
        entry = 0.0
        trades = 0
        wins = 0
        equity_curve: list[float] = []
        peak = starting_balance
        max_drawdown = 0.0
        realized = 0.0
        for index, bar in enumerate(bars):
            price = float(bar["close"])
            target = signals[index]
            if target == 1 and qty <= 0 and cash > 0:
                notional = cash * position_fraction
                if notional > 0 and price > 0:
                    qty = notional / price
                    entry = price
                    cash -= notional
                    trades += 1
            elif target == 0 and qty > 0:
                proceeds = qty * price
                pnl = proceeds - (qty * entry)
                realized += pnl
                if pnl > 0:
                    wins += 1
                cash += proceeds
                qty = 0.0
                entry = 0.0
            equity = cash + qty * price
            equity_curve.append(equity)
            peak = max(peak, equity)
            drawdown = (peak - equity) / peak if peak > 0 else 0.0
            max_drawdown = max(max_drawdown, drawdown)
        if qty > 0:
            price = closes[-1]
            proceeds = qty * price
            pnl = proceeds - (qty * entry)
            realized += pnl
            if pnl > 0:
                wins += 1
            cash += proceeds
            qty = 0.0
            equity_curve[-1] = cash
        final_equity = cash
        total_return = (final_equity / starting_balance) - 1.0 if starting_balance else 0.0
        # Simple Sharpe proxy on bar equity returns.
        returns: list[float] = []
        for index in range(1, len(equity_curve)):
            prev = equity_curve[index - 1]
            if prev > 0:
                returns.append((equity_curve[index] / prev) - 1.0)
        if len(returns) >= 2:
            mean_r = sum(returns) / len(returns)
            var = sum((item - mean_r) ** 2 for item in returns) / (len(returns) - 1)
            std_r = math.sqrt(max(0.0, var))
            sharpe = (mean_r / std_r) * math.sqrt(24 * 365) if std_r > 1e-12 else 0.0
        else:
            sharpe = 0.0
        win_rate = (wins / trades) if trades else 0.0
        # Score favors return with drawdown/sharpe discipline.
        score = (total_return * 100.0) + (sharpe * 5.0) - (max_drawdown * 80.0) + (win_rate * 10.0)
        return {
            "kind": kind,
            "params": params,
            "starting_balance": starting_balance,
            "final_equity": round(final_equity, 4),
            "total_return": round(total_return, 6),
            "realized_pnl": round(realized, 4),
            "trades": trades,
            "wins": wins,
            "win_rate": round(win_rate, 4),
            "max_drawdown": round(max_drawdown, 6),
            "sharpe": round(sharpe, 4),
            "score": round(score, 4),
            "bars": len(bars),
            "equity_start": starting_balance,
            "equity_end": round(final_equity, 4),
            # Honesty: this path is the legacy educational desk, not Trading Lab.
            "simulation_layer": "legacy_paper_desk",
            "research_class": "educational_in_sample",
            "validated_strategy": False,
            "limitations": [
                "same_bar_signal_same_bar_fill_lookahead",
                "no_fees_spread_slippage_or_partials",
                "discovery_and_score_share_the_same_bars",
                "sharpe_annualisation_hardcoded_sqrt_24_365",
                "not_a_chronological_event_driven_path",
            ],
            "disclaimer": (
                "Legacy educational backtest/discovery metrics. "
                "Not a validated strategy. Use Trading Lab for point-in-time research."
            ),
        }

    def discovery_grid(self) -> list[tuple[str, dict[str, Any]]]:
        combos: list[tuple[str, dict[str, Any]]] = []
        for fast, slow in ((5, 20), (8, 21), (10, 30), (12, 48), (20, 50)):
            combos.append(("sma_crossover", {"fast": fast, "slow": slow}))
        for lookback, threshold in ((10, 0.01), (20, 0.015), (30, 0.02), (48, 0.03)):
            combos.append(("momentum", {"lookback": lookback, "threshold": threshold}))
        for window, z_entry in ((15, 1.2), (20, 1.5), (30, 1.8), (40, 2.0)):
            combos.append(("mean_reversion", {"window": window, "z_entry": z_entry}))
        return combos

    def discover_strategies(self, bars: list[dict[str, Any]], *, top_n: int = 5) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for kind, params in self.discovery_grid():
            metrics = self.backtest(bars, kind=kind, params=params)
            scored.append(metrics)
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[: max(1, top_n)]

    def persist_discovered(self, discoveries: list[dict[str, Any]], *, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        now = utc_now()
        saved_ids: list[str] = []
        with self.db.connection() as db:
            for rank, item in enumerate(discoveries, start=1):
                strategy_id = new_id("strat")
                name = f"{item['kind']} #{rank} · {symbol}"
                notes = (
                    f"[legacy/educational/in-sample] Ontdekt op {symbol} {timeframe}. "
                    f"Return {item['total_return']*100:.2f}%, Sharpe {item['sharpe']:.2f}, "
                    f"max DD {item['max_drawdown']*100:.2f}%, trades {item['trades']}. "
                    f"Geen gevalideerde strategie — zie Trading Lab voor PIT-research."
                )
                status = "active" if rank == 1 else "candidate"
                db.execute(
                    """INSERT INTO trading_strategies(
                           id,name,kind,params_json,status,score,metrics_json,notes,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        strategy_id,
                        name,
                        item["kind"],
                        json.dumps(item["params"], ensure_ascii=False),
                        status,
                        float(item["score"]),
                        json.dumps(item, ensure_ascii=False),
                        notes,
                        now,
                        now,
                    ),
                )
                saved_ids.append(strategy_id)
        return [self.get_strategy(strategy_id) for strategy_id in saved_ids if self.get_strategy(strategy_id)]

    def ingest_learning(self, *, title: str, text: str, uri: str, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self.knowledge:
            return None
        return self.knowledge.ingest_text(
            title=title,
            text=text,
            source_type="trading_strategy",
            uri=uri,
            metadata=metadata or {},
        )

    def learning_matches(self, query: str = "trading strategy", limit: int = 8) -> list[dict[str, Any]]:
        if not self.knowledge:
            return []
        return self.db.search_knowledge(query, limit=limit)

    def execute_paper_bot_step(self, strategy: dict[str, Any], bars: list[dict[str, Any]], *, position_fraction: float) -> dict[str, Any]:
        """Apply latest signal on paper account using the newest bar price."""
        if len(bars) < 50:
            raise RuntimeError("Onvoldoende balken voor botstap.")
        closes = [float(bar["close"]) for bar in bars]
        signals = self.signals_for(strategy["kind"], closes, strategy["params"])
        target = signals[-1]
        price = closes[-1]
        symbol = str(bars[0]["symbol"]).upper()
        state = self.paper.state()
        if not state["settings"]["enabled"]:
            # Do not silently re-enable paper trading — matches specialist honesty.
            raise RuntimeError("paper_trading_disabled")
        if state["settings"]["kill_switch"]:
            raise RuntimeError("Kill switch blokkeert de paper-bot.")
        open_positions = [pos for pos in state["positions"] if pos["status"] == "open" and pos["symbol"] == symbol]
        actions: list[str] = []
        if target == 1 and not open_positions:
            balance = next((float(wallet["balance"]) for wallet in state["wallets"] if wallet["asset"] == "USDT"), 0.0)
            notional = balance * position_fraction
            if notional <= 0 or price <= 0:
                raise RuntimeError("Geen vrij PAPER-saldo voor bot-aankoop.")
            quantity = notional / price
            result = self.paper.buy(symbol, quantity, price)
            actions.append(f"BUY {quantity:.8f} @ {price}")
            state = result["state"]
        elif target == 0 and open_positions:
            for position in open_positions:
                result = self.paper.close(position["id"], price)
                actions.append(f"CLOSE {position['id']} @ {price} PnL={result['realized_pnl']:+.2f}")
                state = result["state"]
        else:
            actions.append("HOLD")
        with self.db.connection() as db:
            db.execute(
                "UPDATE trading_bot_settings SET last_bar_ts=?, updated_at=? WHERE id=1",
                (bars[-1]["ts"], utc_now()),
            )
        return {"actions": actions, "signal": target, "price": price, "state": state, "bar_ts": bars[-1]["ts"]}

    def dashboard(self) -> dict[str, Any]:
        paper = self.paper.state()
        symbols = self.list_symbols()
        selected_symbol = self.bot_settings().get("symbol") or (symbols[0]["symbol"] if symbols else "BTC/USDT")
        selected_timeframe = self.bot_settings().get("timeframe") or (symbols[0]["timeframe"] if symbols else "1h")
        bars = (
            self.get_bars(
                selected_symbol,
                selected_timeframe,
                limit=_setting("trading.dashboard_bars", 180),
            )
            if symbols
            else []
        )
        strategies = self.list_strategies(30)
        runs = self.list_runs(20)
        learnings = []
        try:
            learnings = self.db.search_knowledge("trading strategy paper", limit=8)
        except Exception:
            learnings = []
        return {
            "paper": paper,
            "bot": self.bot_settings(),
            "symbols": symbols,
            "bars": bars,
            "strategies": strategies,
            "runs": runs,
            "learnings": learnings,
            "strategy_kinds": list(self.STRATEGY_KINDS),
        }


class TradingJobRunner:
    """Async runner for discover/backtest/paper_bot jobs. Deterministic; optional knowledge write."""

    def __init__(self, bot: TradingBotService) -> None:
        self.bot = bot
        self.jobs: dict[str, asyncio.Task[None]] = {}

    def schedule(self, run_id: str) -> None:
        existing = self.jobs.get(run_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self._run(run_id), name=f"hades-trading-{run_id}")
        self.jobs[run_id] = task
        task.add_done_callback(lambda _: self.jobs.pop(run_id, None))

    def cancel(self, run_id: str) -> bool:
        job = self.jobs.get(run_id)
        if not job or job.done():
            return False
        job.cancel()
        return True

    async def shutdown(self) -> None:
        jobs = [job for job in self.jobs.values() if not job.done()]
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    async def _run(self, run_id: str) -> None:
        run = self.bot.get_run(run_id)
        if not run or run["status"] not in {"queued", "failed", "cancelled"}:
            return
        try:
            self.bot.update_run(run_id, status="running", progress=5, started_at=utc_now(), error=None)
            bars = await asyncio.to_thread(self.bot.get_bars, run["symbol"], run["timeframe"], 5000)
            if len(bars) < 50:
                raise RuntimeError("Onvoldoende marktdata voor deze run.")
            if run["kind"] == "discover":
                await self._discover(run_id, run, bars)
            elif run["kind"] == "backtest":
                await self._backtest(run_id, run, bars)
            elif run["kind"] == "paper_bot":
                await self._paper_bot(run_id, run, bars)
            else:
                raise ValueError(f"Onbekende run-soort: {run['kind']}")
        except asyncio.CancelledError:
            self.bot.update_run(run_id, status="cancelled", progress=0, finished_at=utc_now(), error="Handmatig geannuleerd.")
            raise
        except Exception as exc:
            self.bot.update_run(run_id, status="failed", progress=0, finished_at=utc_now(), error=str(exc))
            with self.bot.db.connection() as db:
                db.execute(
                    "INSERT INTO trading_events(level,message,created_at) VALUES('warning',?,?)",
                    (f"Trading-run mislukt ({run_id}): {exc}", utc_now()),
                )

    async def _discover(self, run_id: str, run: dict[str, Any], bars: list[dict[str, Any]]) -> None:
        self.bot.update_run(run_id, progress=20)
        top_n = int((run.get("config") or {}).get("top_n", 5))
        discoveries = await asyncio.to_thread(self.bot.discover_strategies, bars, top_n=top_n)
        self.bot.update_run(run_id, progress=70)
        saved = await asyncio.to_thread(self.bot.persist_discovered, discoveries, symbol=run["symbol"], timeframe=run["timeframe"])
        learning_text = self._learning_document(run, discoveries, saved)
        knowledge = await asyncio.to_thread(
            self.bot.ingest_learning,
            title=f"Trading strategie-ontdekking · {run['symbol']}",
            text=learning_text,
            uri=f"trading://strategy-run/{run_id}",
            metadata={"run_id": run_id, "symbol": run["symbol"], "timeframe": run["timeframe"], "kind": "discover"},
        )

        if knowledge is not None and not _knowledge_payload_verified(knowledge):
            with self.bot.db.connection() as db:
                db.execute(
                    "INSERT INTO trading_events(level,message,created_at) VALUES('warning',?,?)",
                    ("Knowledge-ingest niet geverifieerd; knowledge_source_id niet gezet.", utc_now()),
                )
            knowledge = None
        if knowledge and saved:
            with self.bot.db.connection() as db:
                for strategy in saved:
                    db.execute(
                        "UPDATE trading_strategies SET knowledge_source_id=?, updated_at=? WHERE id=?",
                        (knowledge["id"], utc_now(), strategy["id"]),
                    )
        best_id = saved[0]["id"] if saved else None
        if best_id:
            self.bot.set_bot_settings(strategy_id=best_id, symbol=run["symbol"], timeframe=run["timeframe"], enabled=False)
        result = {"discoveries": discoveries, "strategies": saved, "knowledge_source_id": knowledge["id"] if knowledge else None}
        self.bot.update_run(
            run_id,
            status="completed",
            progress=100,
            result_json=json.dumps(result, ensure_ascii=False),
            knowledge_source_id=knowledge["id"] if knowledge else None,
            strategy_id=best_id,
            finished_at=utc_now(),
        )
        with self.bot.db.connection() as db:
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES('success',?,?)",
                (f"Strategie-ontdekking voltooid: {len(saved)} kandidaten, beste score {discoveries[0]['score'] if discoveries else 0}.", utc_now()),
            )

    async def _backtest(self, run_id: str, run: dict[str, Any], bars: list[dict[str, Any]]) -> None:
        strategy_id = run.get("strategy_id")
        strategy = self.bot.get_strategy(strategy_id) if strategy_id else None
        if not strategy:
            raise RuntimeError("Backtest vereist een bestaande strategie.")
        self.bot.update_run(run_id, progress=30)
        metrics = await asyncio.to_thread(self.bot.backtest, bars, kind=strategy["kind"], params=strategy["params"])
        self.bot.update_run(run_id, progress=80)
        learning = (
            f"# Backtest {strategy['name']}\n\n"
            f"- Symbol: {run['symbol']} ({run['timeframe']})\n"
            f"- Kind: {strategy['kind']}\n"
            f"- Params: {json.dumps(strategy['params'])}\n"
            f"- Return: {metrics['total_return']*100:.2f}%\n"
            f"- Sharpe: {metrics['sharpe']:.3f}\n"
            f"- Max drawdown: {metrics['max_drawdown']*100:.2f}%\n"
            f"- Trades: {metrics['trades']} (win rate {metrics['win_rate']*100:.1f}%)\n"
            f"- Score: {metrics['score']:.2f}\n"
        )
        knowledge = await asyncio.to_thread(
            self.bot.ingest_learning,
            title=f"Backtest · {strategy['name']}",
            text=learning,
            uri=f"trading://backtest/{run_id}",
            metadata={"run_id": run_id, "strategy_id": strategy_id, "kind": "backtest"},
        )

        if knowledge is not None and not _knowledge_payload_verified(knowledge):
            with self.bot.db.connection() as db:
                db.execute(
                    "INSERT INTO trading_events(level,message,created_at) VALUES('warning',?,?)",
                    ("Knowledge-ingest niet geverifieerd; knowledge_source_id niet gezet.", utc_now()),
                )
            knowledge = None
        with self.bot.db.connection() as db:
            db.execute(
                "UPDATE trading_strategies SET metrics_json=?, score=?, knowledge_source_id=COALESCE(?, knowledge_source_id), updated_at=? WHERE id=?",
                (json.dumps(metrics, ensure_ascii=False), float(metrics["score"]), knowledge["id"] if knowledge else None, utc_now(), strategy_id),
            )
        self.bot.update_run(
            run_id,
            status="completed",
            progress=100,
            result_json=json.dumps({"metrics": metrics, "knowledge_source_id": knowledge["id"] if knowledge else None}, ensure_ascii=False),
            knowledge_source_id=knowledge["id"] if knowledge else None,
            finished_at=utc_now(),
        )

    async def _paper_bot(self, run_id: str, run: dict[str, Any], bars: list[dict[str, Any]]) -> None:
        settings = self.bot.bot_settings()
        strategy_id = run.get("strategy_id") or settings.get("strategy_id")
        strategy = self.bot.get_strategy(strategy_id) if strategy_id else None
        if not strategy:
            raise RuntimeError("Paper-bot vereist een actieve strategie. Voer eerst discovery uit.")
        config = run.get("config") or {}
        window = int(config.get("window", min(240, len(bars))))
        window = max(50, min(window, len(bars)))
        slice_bars = bars[-window:]
        self.bot.update_run(run_id, progress=25)
        fraction = float(settings.get("position_fraction") or 0.1)
        metrics = await asyncio.to_thread(
            self.bot.backtest,
            slice_bars,
            kind=strategy["kind"],
            params=strategy["params"],
            position_fraction=max(0.05, min(1.0, fraction * 4)),
        )
        self.bot.update_run(run_id, progress=70)
        self.bot.set_bot_settings(enabled=True, strategy_id=strategy["id"], symbol=run["symbol"], timeframe=run["timeframe"])
        step = await asyncio.to_thread(
            self.bot.execute_paper_bot_step,
            strategy,
            slice_bars,
            position_fraction=fraction,
        )
        self.bot.set_bot_settings(enabled=False)
        result = {
            "metrics": metrics,
            "live_step": {"actions": step["actions"], "signal": step["signal"], "price": step["price"], "bar_ts": step["bar_ts"]},
            "strategy_id": strategy["id"],
            "window": window,
        }
        learning = (
            f"# Paper-bot run {run['symbol']}\n\n"
            f"Strategie `{strategy['name']}` ({strategy['kind']}) geëvalueerd op {window} balken.\n"
            f"- Gesimuleerde return: {metrics['total_return']*100:.2f}%\n"
            f"- Sharpe: {metrics['sharpe']:.3f}\n"
            f"- Max drawdown: {metrics['max_drawdown']*100:.2f}%\n"
            f"- Live paper-stap: {', '.join(step['actions'])} @ {step['price']}\n"
            f"- Params: {json.dumps(strategy['params'])}\n"
        )
        knowledge = await asyncio.to_thread(
            self.bot.ingest_learning,
            title=f"Paper-bot ervaring · {strategy['name']}",
            text=learning,
            uri=f"trading://paper-bot/{run_id}",
            metadata={"run_id": run_id, "strategy_id": strategy["id"], "kind": "paper_bot"},
        )

        if knowledge is not None and not _knowledge_payload_verified(knowledge):
            with self.bot.db.connection() as db:
                db.execute(
                    "INSERT INTO trading_events(level,message,created_at) VALUES('warning',?,?)",
                    ("Knowledge-ingest niet geverifieerd; knowledge_source_id niet gezet.", utc_now()),
                )
            knowledge = None
        self.bot.update_run(
            run_id,
            status="completed",
            progress=100,
            result_json=json.dumps({**result, "knowledge_source_id": knowledge["id"] if knowledge else None}, ensure_ascii=False),
            knowledge_source_id=knowledge["id"] if knowledge else None,
            strategy_id=strategy["id"],
            finished_at=utc_now(),
        )
        with self.bot.db.connection() as db:
            db.execute(
                "INSERT INTO trading_events(level,message,created_at) VALUES('success',?,?)",
                (
                    f"Paper-bot run voltooid ({strategy['name']}): sim return {metrics['total_return']*100:.2f}%, live={step['actions']}.",
                    utc_now(),
                ),
            )

    def _learning_document(self, run: dict[str, Any], discoveries: list[dict[str, Any]], saved: list[dict[str, Any]]) -> str:
        lines = [
            f"# Trading strategie-ontdekking · {run['symbol']} ({run['timeframe']})",
            "",
            "HADES heeft lokaal en deterministisch historische PAPER-marktbalken geëvalueerd.",
            "Dit document is bruikbare marktkennis voor toekomstige PAPER-beslissingen.",
            "",
            "## Topstrategieën",
        ]
        for index, item in enumerate(discoveries):
            strategy_id = saved[index]["id"] if index < len(saved) else "?"
            lines.extend(
                [
                    f"### {index + 1}. {item['kind']} (`{strategy_id}`)",
                    f"- Params: `{json.dumps(item['params'])}`",
                    f"- Score: {item['score']:.2f}",
                    f"- Return: {item['total_return']*100:.2f}%",
                    f"- Sharpe: {item['sharpe']:.3f}",
                    f"- Max drawdown: {item['max_drawdown']*100:.2f}%",
                    f"- Trades: {item['trades']} · win rate {item['win_rate']*100:.1f}%",
                    "",
                ]
            )
        lines.extend(
            [
                "## Gebruik",
                "- Activeer de beste kandidaat als paper-bot strategie.",
                "- Herhaal discovery wanneer nieuwe marktdata is geïmporteerd.",
                "- Real-money execution bestaat niet in de HADES-core (PAPER-only).",
            ]
        )
        return "\n".join(lines)


def _knowledge_payload_verified(payload: Any) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    status = str(payload.get("status") or "")
    if status in {"verification_failed", "error", "failed"}:
        return False
    persistence = payload.get("persistence")
    if isinstance(persistence, dict) and persistence.get("verification_passed") is False:
        return False
    return True

