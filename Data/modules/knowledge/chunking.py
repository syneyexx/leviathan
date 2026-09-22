from __future__ import annotations

from .types import TextSpan


def chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 120) -> list[str]:
    """Split text into overlapping chunks (legacy string-only API)."""
    return [span.text for span in chunk_text_spans(text, max_chars=max_chars, overlap=overlap)]


def chunk_text_spans(text: str, *, max_chars: int = 1200, overlap: int = 120) -> list[TextSpan]:
    """Split text into overlapping chunks with absolute character offsets.

    Prefer paragraph boundaries; fall back to hard splits. Empty input yields [].
    Offsets refer to the cleaned text (CRLF normalized, stripped ends).
    """
    cleaned = text.replace("\r\n", "\n").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [TextSpan(text=cleaned, start=0, end=len(cleaned))]

    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    # Map paragraph text back to positions in cleaned.
    search_from = 0
    para_spans: list[TextSpan] = []
    for para in paragraphs or [cleaned]:
        idx = cleaned.find(para, search_from)
        if idx < 0:
            idx = search_from
        para_spans.append(TextSpan(text=para, start=idx, end=idx + len(para)))
        search_from = idx + len(para)

    spans: list[TextSpan] = []
    current_parts: list[TextSpan] = []

    def flush() -> None:
        nonlocal current_parts
        if not current_parts:
            return
        start = current_parts[0].start
        end = current_parts[-1].end
        text_body = cleaned[start:end].strip()
        # Recompute tight bounds after strip.
        if text_body:
            # Find stripped content within [start, end].
            inner = cleaned[start:end]
            lead = len(inner) - len(inner.lstrip())
            trail = len(inner) - len(inner.rstrip())
            spans.append(TextSpan(text=text_body, start=start + lead, end=end - trail))
        current_parts = []

    for para in para_spans:
        if len(para.text) > max_chars:
            flush()
            start = para.start
            while start < para.end:
                end = min(para.end, start + max_chars)
                piece = cleaned[start:end].strip()
                if piece:
                    # Adjust for strip within window.
                    window = cleaned[start:end]
                    lead = len(window) - len(window.lstrip())
                    trail = len(window) - len(window.rstrip())
                    spans.append(TextSpan(text=piece, start=start + lead, end=end - trail))
                if end >= para.end:
                    break
                start = max(para.start, end - overlap)
            continue

        if not current_parts:
            current_parts = [para]
            continue
        candidate_start = current_parts[0].start
        candidate_end = para.end
        if candidate_end - candidate_start <= max_chars:
            current_parts.append(para)
        else:
            flush()
            current_parts = [para]

    flush()
    return [s for s in spans if s.text]
