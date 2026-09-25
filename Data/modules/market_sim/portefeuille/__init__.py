"""Paper Portefeuille — multi-asset paper capital book inside market_sim.

Canonical paper capital for TradingCenter /trading/portefeuille.
Reuses RiskGuard, paper brokers, orchestra, and Agent Fleet.
Never enables live-money trading.
"""

from .types import (
    PaperPortfolio,
    PortfolioAllocation,
    PortfolioOrder,
    PortfolioPosition,
    PortfolioRecommendation,
    PortfolioSnapshot,
    PortfolioStatus,
    PortfolioTransaction,
    TradingDecision,
)
from .ledger import PortfolioBook
from .assets import AssetRegistry, asset_registry

__all__ = [
    "PaperPortfolio",
    "PortfolioAllocation",
    "PortfolioBook",
    "PortfolioOrder",
    "PortfolioPosition",
    "PortfolioRecommendation",
    "PortfolioSnapshot",
    "PortfolioStatus",
    "PortfolioTransaction",
    "TradingDecision",
    "AssetRegistry",
    "asset_registry",
]
