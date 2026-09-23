"""Resource budget envelope for runs/jobs/agents (U010)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResourceBudgetEnvelope:
    """One resource-budget envelope covering wall time, tokens, tools, and hardware."""

    wall_time_seconds: float | None = None
    tokens: int | None = None
    tool_calls: int | None = None
    cpu_percent: float | None = None
    ram_mb: float | None = None
    gpu_count: int | None = None
    vram_mb: float | None = None
    disk_mb: float | None = None
    monetary_cost: float | None = None
    consumed: dict[str, float] = field(default_factory=dict)

    def remaining(self, key: str) -> float | None:
        ceiling = getattr(self, key, None)
        if ceiling is None:
            return None
        used = float(self.consumed.get(key, 0.0))
        return float(ceiling) - used

    def consume(self, key: str, amount: float) -> None:
        if amount < 0:
            raise ValueError("consume amount must be >= 0")
        self.consumed[key] = float(self.consumed.get(key, 0.0)) + float(amount)

    def exhausted(self) -> list[str]:
        out: list[str] = []
        for key in (
            "wall_time_seconds",
            "tokens",
            "tool_calls",
            "cpu_percent",
            "ram_mb",
            "gpu_count",
            "vram_mb",
            "disk_mb",
            "monetary_cost",
        ):
            rem = self.remaining(key)
            if rem is not None and rem <= 0:
                out.append(key)
        return out

    def public_dict(self) -> dict[str, Any]:
        return {
            "ceilings": {
                "wall_time_seconds": self.wall_time_seconds,
                "tokens": self.tokens,
                "tool_calls": self.tool_calls,
                "cpu_percent": self.cpu_percent,
                "ram_mb": self.ram_mb,
                "gpu_count": self.gpu_count,
                "vram_mb": self.vram_mb,
                "disk_mb": self.disk_mb,
                "monetary_cost": self.monetary_cost,
            },
            "consumed": dict(self.consumed),
            "exhausted": self.exhausted(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ResourceBudgetEnvelope:
        raw = data or {}
        ceilings = raw.get("ceilings", raw)
        env = cls(
            wall_time_seconds=ceilings.get("wall_time_seconds"),
            tokens=ceilings.get("tokens"),
            tool_calls=ceilings.get("tool_calls"),
            cpu_percent=ceilings.get("cpu_percent"),
            ram_mb=ceilings.get("ram_mb"),
            gpu_count=ceilings.get("gpu_count"),
            vram_mb=ceilings.get("vram_mb"),
            disk_mb=ceilings.get("disk_mb"),
            monetary_cost=ceilings.get("monetary_cost"),
        )
        env.consumed = {str(k): float(v) for k, v in dict(raw.get("consumed") or {}).items()}
        return env
