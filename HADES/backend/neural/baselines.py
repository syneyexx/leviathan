"""Nearest-neighbor baseline for Phase 1 comparisons.

This is intentionally NOT the neural-memory experiment — it exists so retention
and interference results can be compared against a simple exact store.
"""

from __future__ import annotations

import time
from typing import Any

from neural.deps import require_torch


class NearestNeighborMemory:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._keys: list[Any] = []
        self._values: list[Any] = []

    def write(self, key: Any, value: Any) -> dict[str, Any]:
        torch = require_torch()
        k = torch.as_tensor(key, dtype=torch.float32).reshape(-1)
        v = torch.as_tensor(value, dtype=torch.float32).reshape(-1)
        if int(k.numel()) != self.dim or int(v.numel()) != self.dim:
            raise ValueError("dimension mismatch")
        self._keys.append(k.clone())
        self._values.append(v.clone())
        return {"accepted": True, "count": len(self._keys)}

    def read(self, query: Any) -> dict[str, Any]:
        torch = require_torch()
        started = time.perf_counter()
        if not self._keys:
            latency = (time.perf_counter() - started) * 1000.0
            return {"value": None, "similarity": None, "latency_ms": latency}
        q = torch.as_tensor(query, dtype=torch.float32).reshape(-1)
        qn = torch.nn.functional.normalize(q, dim=0)
        best_sim = -2.0
        best_val = None
        for key, value in zip(self._keys, self._values, strict=True):
            kn = torch.nn.functional.normalize(key, dim=0)
            sim = float((qn * kn).sum().item())
            if sim > best_sim:
                best_sim = sim
                best_val = value.clone()
        latency = (time.perf_counter() - started) * 1000.0
        return {"value": best_val, "similarity": best_sim, "latency_ms": latency}

    @property
    def size(self) -> int:
        return len(self._keys)
