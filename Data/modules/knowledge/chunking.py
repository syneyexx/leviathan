from __future__ import annotations


def chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 120) -> list[str]:
    """Split text into overlapping chunks.

    Prefer paragraph boundaries; fall back to hard splits. Empty input yields [].
    """
    cleaned = text.replace("\r\n", "\n").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for para in paragraphs or [cleaned]:
        if len(para) > max_chars:
            flush()
            start = 0
            while start < len(para):
                end = min(len(para), start + max_chars)
                chunks.append(para[start:end].strip())
                if end >= len(para):
                    break
                start = max(0, end - overlap)
            continue

        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            flush()
            current = para

    flush()

    # Apply overlap between adjacent hard chunks when a single paragraph was split.
    if overlap <= 0 or len(chunks) <= 1:
        return [c for c in chunks if c]

    return [c for c in chunks if c]
