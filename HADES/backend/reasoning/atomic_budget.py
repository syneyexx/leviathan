"""Atomic shared execution budgets for concurrent workers."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any


class BudgetExhausted(RuntimeError):
    """Raised when a reservation cannot be satisfied atomically."""


@dataclass
class SharedBudgetPool:
    """Process-local atomic ceilings shared across Chat/Work/Research workers.

    Any ``max_*`` field may be ``None`` to mean unlimited (no HADES-owned ceiling).
    """

    max_active_tasks: int | None = 4
    max_model_calls: int | None = 200
    max_tool_calls: int | None = 200
    max_specialist_steps: int | None = 100
    max_plugin_processes: int | None = 8
    max_subtasks: int | None = 64
    max_runtime_seconds: int | None = 3600

    active_tasks: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    specialist_steps: int = 0
    plugin_processes: int = 0
    subtasks: int = 0
    leased_model_calls: int = 0
    leased_tool_calls: int = 0

    _thread_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _async_lock: asyncio.Lock | None = field(default=None, repr=False)

    def configure(self, values: dict[str, Any]) -> None:
        with self._thread_lock:
            for key in (
                "max_active_tasks",
                "max_model_calls",
                "max_tool_calls",
                "max_specialist_steps",
                "max_plugin_processes",
                "max_subtasks",
                "max_runtime_seconds",
            ):
                if key not in values:
                    continue
                raw = values[key]
                # None = unlimited (no HADES-owned ceiling).
                if raw is None:
                    setattr(self, key, None)
                else:
                    setattr(self, key, max(0, int(raw)))

    def snapshot(self) -> dict[str, Any]:
        with self._thread_lock:
            return {
                "max_active_tasks": self.max_active_tasks,
                "max_model_calls": self.max_model_calls,
                "max_tool_calls": self.max_tool_calls,
                "max_specialist_steps": self.max_specialist_steps,
                "max_plugin_processes": self.max_plugin_processes,
                "max_subtasks": self.max_subtasks,
                "max_runtime_seconds": self.max_runtime_seconds,
                "active_tasks": self.active_tasks,
                "model_calls": self.model_calls,
                "tool_calls": self.tool_calls,
                "leased_model_calls": self.leased_model_calls,
                "leased_tool_calls": self.leased_tool_calls,
                "specialist_steps": self.specialist_steps,
                "plugin_processes": self.plugin_processes,
                "subtasks": self.subtasks,
            }

    def _try_reserve(self, kind: str, amount: int = 1) -> bool:
        mapping = {
            "task": ("active_tasks", "max_active_tasks"),
            "model": ("model_calls", "max_model_calls"),
            "tool": ("tool_calls", "max_tool_calls"),
            "specialist": ("specialist_steps", "max_specialist_steps"),
            "plugin": ("plugin_processes", "max_plugin_processes"),
            "subtask": ("subtasks", "max_subtasks"),
        }
        if kind not in mapping:
            raise KeyError(kind)
        current_attr, max_attr = mapping[kind]
        current = getattr(self, current_attr)
        ceiling = getattr(self, max_attr)
        if ceiling is not None and current + amount > int(ceiling):
            return False
        setattr(self, current_attr, current + amount)
        return True

    def reserve(self, kind: str, amount: int = 1) -> None:
        """Atomically reserve budget or raise BudgetExhausted.

        Two concurrent workers cannot both consume the same remaining unit.
        """
        with self._thread_lock:
            if not self._try_reserve(kind, amount):
                raise BudgetExhausted(f"budget exhausted for {kind}")

    def release(self, kind: str, amount: int = 1) -> None:
        mapping = {
            "task": "active_tasks",
            "plugin": "plugin_processes",
        }
        # model/tool/specialist/subtask are consumed counters (not released),
        # except task/plugin process slots which are concurrency leases.
        attr = mapping.get(kind)
        if not attr:
            return
        with self._thread_lock:
            setattr(self, attr, max(0, getattr(self, attr) - amount))

    def try_reserve(self, kind: str, amount: int = 1) -> bool:
        with self._thread_lock:
            return self._try_reserve(kind, amount)

    def _lease_fields(self, kind: str) -> tuple[str, str, str]:
        mapping = {
            "model": ("model_calls", "max_model_calls", "leased_model_calls"),
            "tool": ("tool_calls", "max_tool_calls", "leased_tool_calls"),
        }
        if kind not in mapping:
            raise KeyError(kind)
        return mapping[kind]

    def lease(self, kind: str, amount: int = 1) -> None:
        """Hold capacity without consuming it. Unused leases must be released."""
        with self._thread_lock:
            current_attr, max_attr, leased_attr = self._lease_fields(kind)
            current = getattr(self, current_attr)
            leased = getattr(self, leased_attr)
            ceiling = getattr(self, max_attr)
            if ceiling is not None and current + leased + amount > int(ceiling):
                raise BudgetExhausted(f"budget exhausted for {kind}")
            setattr(self, leased_attr, leased + amount)

    def commit_lease(self, kind: str, amount: int = 1) -> None:
        with self._thread_lock:
            current_attr, _max_attr, leased_attr = self._lease_fields(kind)
            leased = getattr(self, leased_attr)
            take = min(amount, leased)
            setattr(self, leased_attr, max(0, leased - take))
            setattr(self, current_attr, getattr(self, current_attr) + take)
            leftover = amount - take
            if leftover:
                setattr(self, current_attr, getattr(self, current_attr) + leftover)

    def release_lease(self, kind: str, amount: int = 1) -> None:
        with self._thread_lock:
            _current_attr, _max_attr, leased_attr = self._lease_fields(kind)
            setattr(self, leased_attr, max(0, getattr(self, leased_attr) - amount))


shared_budget_pool = SharedBudgetPool()
