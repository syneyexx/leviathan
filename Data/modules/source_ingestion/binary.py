"""Binary vs text classification — never Latin-1 dump binary garbage into Brain."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import BinaryIO


def _sample_bytes(source: Path | bytes | BinaryIO, *, sample_size: int = 8192) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source[:sample_size])
    if isinstance(source, Path):
        with open(source, "rb") as handle:
            return handle.read(sample_size)
    pos = None
    try:
        pos = source.tell()
    except Exception:  # noqa: BLE001
        pos = None
    try:
        data = source.read(sample_size)
        return data if isinstance(data, (bytes, bytearray)) else b""
    finally:
        if pos is not None:
            try:
                source.seek(pos)
            except Exception:  # noqa: BLE001
                pass


def classify_bytes(sample: bytes) -> dict[str, object]:
    """Return classification details for a byte sample."""
    if not sample:
        return {
            "is_binary": False,
            "is_text": True,
            "reason": "empty",
            "nul_ratio": 0.0,
            "high_bit_ratio": 0.0,
            "entropy": 0.0,
        }

    nul = sample.count(b"\x00")
    nul_ratio = nul / len(sample)
    if nul > 0:
        return {
            "is_binary": True,
            "is_text": False,
            "reason": "nul_bytes",
            "nul_ratio": nul_ratio,
            "high_bit_ratio": sum(1 for b in sample if b > 127) / len(sample),
            "entropy": _byte_entropy(sample),
        }

    # UTF-8 decode ratio
    try:
        sample.decode("utf-8")
        utf8_ok = True
    except UnicodeDecodeError:
        utf8_ok = False

    high = sum(1 for b in sample if b > 127)
    high_ratio = high / len(sample)
    entropy = _byte_entropy(sample)

    # Control chars excluding common whitespace
    controls = sum(1 for b in sample if b < 32 and b not in (9, 10, 13))
    control_ratio = controls / len(sample)

    if not utf8_ok and high_ratio > 0.30:
        return {
            "is_binary": True,
            "is_text": False,
            "reason": "invalid_utf8_high_entropy",
            "nul_ratio": nul_ratio,
            "high_bit_ratio": high_ratio,
            "entropy": entropy,
        }
    if control_ratio > 0.05 and not utf8_ok:
        return {
            "is_binary": True,
            "is_text": False,
            "reason": "control_chars",
            "nul_ratio": nul_ratio,
            "high_bit_ratio": high_ratio,
            "entropy": entropy,
        }
    if entropy > 7.5 and high_ratio > 0.4:
        return {
            "is_binary": True,
            "is_text": False,
            "reason": "high_entropy",
            "nul_ratio": nul_ratio,
            "high_bit_ratio": high_ratio,
            "entropy": entropy,
        }

    return {
        "is_binary": False,
        "is_text": True,
        "reason": "utf8_text" if utf8_ok else "latinish_text",
        "nul_ratio": nul_ratio,
        "high_bit_ratio": high_ratio,
        "entropy": entropy,
        "utf8_ok": utf8_ok,
    }


def is_binary(source: Path | bytes | BinaryIO, *, sample_size: int = 8192) -> bool:
    sample = _sample_bytes(source, sample_size=sample_size)
    return bool(classify_bytes(sample)["is_binary"])


def _byte_entropy(sample: bytes) -> float:
    if not sample:
        return 0.0
    counts = Counter(sample)
    length = len(sample)
    import math

    entropy = 0.0
    for count in counts.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy
