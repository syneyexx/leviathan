"""Champion / challenger strategy portfolio (W21)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategySlot:
    strategy_id: str
    role: str  # champion | challenger | retired
    version: int = 1
    shadow: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "strategyId": self.strategy_id,
            "role": self.role,
            "version": self.version,
            "shadow": self.shadow,
            "metadata": dict(self.metadata),
        }


@dataclass
class ChampionChallengerPortfolio:
    portfolio_id: str
    champion: StrategySlot | None = None
    challengers: list[StrategySlot] = field(default_factory=list)

    def set_champion(self, strategy_id: str, *, version: int = 1) -> StrategySlot:
        slot = StrategySlot(strategy_id=strategy_id, role="champion", version=version, shadow=False)
        self.champion = slot
        return slot

    def add_challenger(self, strategy_id: str, *, version: int = 1, shadow: bool = True) -> StrategySlot:
        if self.champion and self.champion.strategy_id == strategy_id:
            raise ValueError("challenger cannot equal active champion")
        slot = StrategySlot(
            strategy_id=strategy_id, role="challenger", version=version, shadow=shadow
        )
        self.challengers.append(slot)
        return slot

    def promote_challenger(self, strategy_id: str) -> StrategySlot:
        found = next((c for c in self.challengers if c.strategy_id == strategy_id), None)
        if found is None:
            raise KeyError(strategy_id)
        if self.champion is not None:
            self.champion.role = "retired"
            self.champion.shadow = True
        found.role = "champion"
        found.shadow = False
        self.challengers = [c for c in self.challengers if c.strategy_id != strategy_id]
        self.champion = found
        return found

    def public_dict(self) -> dict[str, Any]:
        return {
            "portfolioId": self.portfolio_id,
            "champion": self.champion.public_dict() if self.champion else None,
            "challengers": [c.public_dict() for c in self.challengers],
            "truth": {
                "shadow_challenger_does_not_replace_champion_until_promote": True,
                "live_trading_blocked": True,
            },
        }
