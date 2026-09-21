from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NativeProbe:
    available: bool
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "detail": self.detail,
            "truth": {
                "native_runtime_not_implemented": True,
                "no_fabricated_accelerate_claims": True,
            },
        }


class NativeRuntimeStub:
    """C++/native runtime placeholder — Python-first until justified."""

    def probe(self) -> NativeProbe:
        return NativeProbe(
            available=False,
            detail="Native/C++ runtime is not implemented; Python remains primary",
        )
