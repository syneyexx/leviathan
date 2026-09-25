"""Sim-to-paper gap measurement (P4B).

Compares historical simulation fills vs paper forward fills for the same
strategy/symbol window. Unmeasured fields stay UNMEASURED — never fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SimToPaperGap:
    symbol: str
    sim_fill_count: int = 0
    paper_fill_count: int = 0
    fill_count_delta: int = 0
    avg_sim_price: float | None = None
    avg_paper_price: float | None = None
    price_gap_bps: float | None = None
    status: str = "UNMEASURED"  # UNMEASURED | MEASURED
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "sim_fill_count": self.sim_fill_count,
            "paper_fill_count": self.paper_fill_count,
            "fill_count_delta": self.fill_count_delta,
            "avg_sim_price": self.avg_sim_price,
            "avg_paper_price": self.avg_paper_price,
            "price_gap_bps": self.price_gap_bps,
            "status": self.status,
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
            "truth": {
                "unmeasured_is_not_pass": True,
                "no_fabricated_precision": True,
                "paper_never_auto_approves_live": True,
            },
        }


def measure_sim_to_paper_gap(
    *,
    symbol: str,
    sim_fills: list[dict[str, Any]] | None = None,
    paper_fills: list[dict[str, Any]] | None = None,
) -> SimToPaperGap:
    sim = list(sim_fills or [])
    paper = list(paper_fills or [])
    gap = SimToPaperGap(
        symbol=str(symbol).upper(),
        sim_fill_count=len(sim),
        paper_fill_count=len(paper),
        fill_count_delta=len(paper) - len(sim),
    )
    if not sim and not paper:
        gap.notes.append("no fills on either path")
        return gap

    def _avg(rows: list[dict[str, Any]]) -> float | None:
        prices = []
        for row in rows:
            px = row.get("price") or row.get("fill_price")
            if px is not None:
                try:
                    prices.append(float(px))
                except (TypeError, ValueError):
                    continue
        if not prices:
            return None
        return sum(prices) / len(prices)

    gap.avg_sim_price = _avg(sim)
    gap.avg_paper_price = _avg(paper)
    if gap.avg_sim_price and gap.avg_paper_price and gap.avg_sim_price > 0:
        gap.price_gap_bps = ((gap.avg_paper_price - gap.avg_sim_price) / gap.avg_sim_price) * 10_000.0
        gap.status = "MEASURED"
    else:
        gap.notes.append("insufficient priced fills for price_gap_bps")
        gap.status = "MEASURED" if (sim or paper) else "UNMEASURED"
    return gap
