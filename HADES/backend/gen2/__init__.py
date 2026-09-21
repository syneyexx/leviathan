"""HADES Gen2 platform package — modular services above TaskRunner/plugins/Brain."""

from __future__ import annotations

from gen2.store import Gen2Store
from gen2.services import Gen2Services

__all__ = ["Gen2Store", "Gen2Services"]
