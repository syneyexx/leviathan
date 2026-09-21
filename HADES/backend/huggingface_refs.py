"""Strict Hugging Face dataset reference normalization.

HADES persists and passes canonical ``owner/dataset`` identifiers internally.
The UI/API may also accept a normal Hugging Face dataset page URL; arbitrary
remote URLs are deliberately rejected instead of becoming download targets.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit


HF_DATASET_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}/[A-Za-z0-9._-]{1,128}")
_ALLOWED_HOSTS = frozenset({"huggingface.co", "www.huggingface.co"})


def normalize_huggingface_dataset_ref(value: str) -> str:
    """Return a canonical ``owner/dataset`` id from an id or dataset page URL.

    Accepted URL shape (query/fragment/trailing slash are harmless):
    ``https://huggingface.co/datasets/<owner>/<dataset>``.

    Deeper paths such as ``/tree/...`` are rejected on purpose. Config and split
    are selected through HADES' typed Dataset Viewer flow, not inferred from a URL.
    """
    raw = str(value or "").strip()
    if HF_DATASET_ID_RE.fullmatch(raw):
        return raw

    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Ongeldige Hugging Face dataset-URL.") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(
            "Gebruik een dataset-ID ('organisatie/dataset') of een https://huggingface.co/datasets/... URL."
        )
    if (parsed.hostname or "").lower() not in _ALLOWED_HOSTS:
        raise ValueError("Alleen huggingface.co dataset-URL's worden geaccepteerd.")
    if parsed.username or parsed.password:
        raise ValueError("Hugging Face dataset-URL mag geen gebruikersnaam of wachtwoord bevatten.")
    if port not in {None, 80, 443}:
        raise ValueError("Hugging Face dataset-URL gebruikt een niet-ondersteunde poort.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 3 or parts[0] != "datasets":
        raise ValueError(
            "Gebruik de datasetpagina zelf: https://huggingface.co/datasets/organisatie/dataset."
        )

    dataset_id = f"{parts[1]}/{parts[2]}"
    if not HF_DATASET_ID_RE.fullmatch(dataset_id):
        raise ValueError("Hugging Face dataset-ID moet de vorm 'organisatie/dataset' hebben.")
    return dataset_id
