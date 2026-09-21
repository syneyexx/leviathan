from __future__ import annotations

import hashlib
import re


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path_bytes: bytes) -> str:
    return hashlib.sha256(path_bytes).hexdigest()


def estimate_tokens(text: str) -> int:
    # Cheap heuristic — not a tokenizer claim.
    words = re.findall(r"\S+", text)
    return max(1, len(words))
