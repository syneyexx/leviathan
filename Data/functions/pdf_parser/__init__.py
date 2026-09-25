from __future__ import annotations

from pathlib import Path
from typing import Any


def run(path: str, *, max_pages: int = 5) -> dict[str, Any]:
    """Extract text from a PDF using optional pypdf (lazy dependency).

    If pypdf is not installed, returns an honest failure payload via raise.
    The import of pypdf happens only when this function executes — not at
    FunctionRegistry construction time.
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    header = target.read_bytes()[:5]
    if header != b"%PDF-":
        raise ValueError("File does not look like a PDF (missing %PDF- header)")

    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "pdf_parser requires optional dependency 'pypdf'. "
            "Install it to enable PDF text extraction."
        ) from exc

    try:
        reader = PdfReader(str(target))
        pages = []
        for index, page in enumerate(reader.pages):
            if index >= max_pages:
                break
            pages.append({"index": index, "text": page.extract_text() or ""})
    except Exception as exc:  # noqa: BLE001 — corrupt/unsupported PDF
        raise RuntimeError(
            f"pypdf failed to parse PDF ({type(exc).__name__}): {exc}"
        ) from exc

    return {
        "path": str(target),
        "page_count": len(reader.pages),
        "pages_returned": len(pages),
        "pages": pages,
        "encrypted": bool(getattr(reader, "is_encrypted", False)),
    }
