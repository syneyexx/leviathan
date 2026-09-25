"""Central asset metadata registry — classification lives here, not in React."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AssetMeta:
    symbol: str
    display_name: str
    asset_class: str  # crypto | equity | stablecoin | cash | other
    base: str
    quote: str
    sector: str | None = None
    geography: str | None = None
    liquidity_category: str = "unknown"  # high | medium | low | unknown

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "displayName": self.display_name,
            "assetClass": self.asset_class,
            "base": self.base,
            "quote": self.quote,
            "sector": self.sector,
            "geography": self.geography,
            "liquidityCategory": self.liquidity_category,
        }


_DEFAULTS: dict[str, AssetMeta] = {
    "BTC": AssetMeta("BTC", "Bitcoin", "crypto", "BTC", "USD", "digital_assets", "global", "high"),
    "BTCUSDT": AssetMeta("BTCUSDT", "Bitcoin", "crypto", "BTC", "USDT", "digital_assets", "global", "high"),
    "ETH": AssetMeta("ETH", "Ethereum", "crypto", "ETH", "USD", "digital_assets", "global", "high"),
    "ETHUSDT": AssetMeta("ETHUSDT", "Ethereum", "crypto", "ETH", "USDT", "digital_assets", "global", "high"),
    "SOL": AssetMeta("SOL", "Solana", "crypto", "SOL", "USD", "digital_assets", "global", "high"),
    "SOLUSDT": AssetMeta("SOLUSDT", "Solana", "crypto", "SOL", "USDT", "digital_assets", "global", "medium"),
    "LINK": AssetMeta("LINK", "Chainlink", "crypto", "LINK", "USD", "digital_assets", "global", "medium"),
    "LINKUSDT": AssetMeta("LINKUSDT", "Chainlink", "crypto", "LINK", "USDT", "digital_assets", "global", "medium"),
    "USDT": AssetMeta("USDT", "Tether", "stablecoin", "USDT", "USD", "stablecoins", "global", "high"),
    "USDC": AssetMeta("USDC", "USD Coin", "stablecoin", "USDC", "USD", "stablecoins", "global", "high"),
    "AAPL": AssetMeta("AAPL", "Apple", "equity", "AAPL", "USD", "technology", "US", "high"),
    "TSLA": AssetMeta("TSLA", "Tesla", "equity", "TSLA", "USD", "consumer_discretionary", "US", "high"),
    "NVDA": AssetMeta("NVDA", "NVIDIA", "equity", "NVDA", "USD", "technology", "US", "high"),
    "SPY": AssetMeta("SPY", "S&P 500 ETF", "equity", "SPY", "USD", "index", "US", "high"),
    "CASH": AssetMeta("CASH", "Cash", "cash", "USD", "USD", "cash", "global", "high"),
    "USD": AssetMeta("USD", "US Dollar", "cash", "USD", "USD", "cash", "global", "high"),
}


class AssetRegistry:
    def __init__(self, extras: dict[str, AssetMeta] | None = None) -> None:
        self._assets = dict(_DEFAULTS)
        if extras:
            self._assets.update(extras)

    def get(self, symbol: str) -> AssetMeta:
        key = symbol.upper().strip()
        if key in self._assets:
            return self._assets[key]
        # Heuristics for unknown symbols
        if key.endswith("USDT") or key.endswith("USD"):
            base = key[:-4] if key.endswith("USDT") else key[:-3]
            return AssetMeta(key, base, "crypto", base or key, "USD", None, "global", "unknown")
        if key.isalpha() and len(key) <= 5:
            return AssetMeta(key, key, "equity", key, "USD", None, "US", "unknown")
        return AssetMeta(key, key, "other", key, "USD", None, None, "unknown")

    def classify(self, symbol: str) -> str:
        return self.get(symbol).asset_class

    def public_list(self) -> list[dict[str, Any]]:
        return [a.public_dict() for a in self._assets.values()]


asset_registry = AssetRegistry()
