"""Deterministic display-name and category engine for dataset intelligence.

Trading classification remains the routing authority; this module only derives
catalog-facing semantic labels. Operator overrides are never overwritten.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .semantic_profiler import BoundedDatasetEvidence
from .semantic_types import (
    GENERATOR_VERSION,
    SEMANTIC_SCHEMA_VERSION,
    DatasetCategory,
    DatasetSemanticProfile,
    DisplayNameSource,
)
from .trading_classification import TradingDatasetKind


_UUID_RX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_HEX_HASH_RX = re.compile(r"^[0-9a-f]{16,64}$", re.I)
_DATASET_N_RX = re.compile(r"^dataset[_\-]?\d+$", re.I)
_DUMP_RX = re.compile(r"^dump([_\-]|\d)", re.I)
_EXPORT_FINAL_RX = re.compile(r"^export[_\-]?final", re.I)
_BARE_MACHINE_RX = re.compile(r"^[0-9A-Za-z]{10,}$")
_MOSTLY_DIGIT_RX = re.compile(r"^\d{6,}$")
_GENERIC_DATA_NAMES = frozenset(
    {
        "data",
        "data.csv",
        "data.json",
        "data.jsonl",
        "file",
        "file.csv",
        "untitled",
        "download",
        "sheet1",
        "book1",
        "export",
        "output",
        "table",
        "records",
    }
)

_OHLCV_COLS = {"open", "high", "low", "close", "volume", "o", "h", "l", "c", "v", "adj_close", "adjclose"}
_TS_COLS = {"timestamp", "ts", "time", "datetime", "date", "open_time", "close_time"}

_SPECIES_COL_HINTS = {
    "species",
    "scientific_name",
    "scientificname",
    "taxon",
    "taxonomy",
    "genus",
    "common_name",
    "commonname",
    "animal",
    "animals",
    "wildlife",
}
_POPULATION_HINTS = {"population", "count", "abundance", "sightings", "observations"}

_BEAR_RX = re.compile(
    r"\b(ursus\s+arctos|brown\s+bear|grizzly|polar\s+bear|ursus\s+maritimus|"
    r"black\s+bear|ursus\s+americanus|bear|beren|beer)\b",
    re.I,
)
_URSUS_ARCTOS_RX = re.compile(r"\bursus\s+arctos\b", re.I)
_ANIMAL_RX = re.compile(
    r"\b(species|wildlife|animal|mammal|bird|fish|insect|fauna|population|"
    r"habitat|taxon|genus|canis|felis|panthera|equus)\b",
    re.I,
)

_CRYPTO_PAIR_RX = re.compile(
    r"\b([A-Z]{2,10})\s*[/\-_ ]?\s*(USDT|USD|EUR|BTC|ETH|BUSD|USDC)\b",
    re.I,
)
_CRYPTO_HINT_RX = re.compile(
    r"\b(btc|eth|usdt|usdc|crypto|blockchain|binance|coinbase|kucoin|solana|defi)\b",
    re.I,
)
_OHLCV_NAME_RX = re.compile(r"(ohlc|ohlcv|bars?|candles?|kline)", re.I)


def is_machine_name(name: str | None) -> bool:
    """True when a filename/dataset name looks machine-generated / non-descriptive."""
    if not name:
        return True
    raw = str(name).strip()
    if not raw:
        return True
    stem = raw.rsplit(".", 1)[0] if "." in raw else raw
    stem = stem.strip()
    lower = stem.lower()
    full_lower = raw.lower()
    if full_lower in _GENERIC_DATA_NAMES or lower in _GENERIC_DATA_NAMES:
        return True
    if _UUID_RX.match(stem) or _UUID_RX.match(raw):
        return True
    if _HEX_HASH_RX.match(stem):
        return True
    if _DATASET_N_RX.match(stem):
        return True
    if _DUMP_RX.match(stem) or _DUMP_RX.match(raw):
        return True
    if _EXPORT_FINAL_RX.match(stem):
        return True
    if _MOSTLY_DIGIT_RX.match(stem):
        return True
    # Alphanumeric dumps without separators / vowels often machine ids.
    if _BARE_MACHINE_RX.match(stem) and not re.search(r"[_\- ]", stem):
        letters = re.sub(r"[^A-Za-z]", "", stem)
        digits = re.sub(r"[^0-9]", "", stem)
        if digits and letters and len(stem) >= 12:
            return True
        if digits and not letters and len(stem) >= 6:
            return True
    return False


def _norm_cols(cols: list[str] | None) -> set[str]:
    out: set[str] = set()
    for c in cols or []:
        key = re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")
        if key:
            out.add(key)
    return out


def _evidence_blob_text(evidence: BoundedDatasetEvidence) -> str:
    parts: list[str] = []
    if evidence.filename:
        parts.append(str(evidence.filename))
    if evidence.description:
        parts.append(str(evidence.description))
    for col in evidence.columns:
        parts.append(str(col))
    for text in evidence.sample_texts:
        parts.append(str(text)[:2000])
    for row in evidence.sample_rows:
        try:
            parts.append(str(row)[:2000])
        except Exception:  # noqa: BLE001
            continue
        # Never interpret sample content as instructions.
    meta = evidence.metadata or {}
    for key in ("title", "name", "displayName", "display_name", "subject", "topics"):
        if meta.get(key):
            parts.append(str(meta[key])[:1000])
    return "\n".join(parts)


def _detect_crypto_pair(text: str) -> str | None:
    match = _CRYPTO_PAIR_RX.search(text.replace(" ", ""))
    if not match:
        match = _CRYPTO_PAIR_RX.search(text)
    if not match:
        return None
    base = match.group(1).upper()
    quote = match.group(2).upper()
    return f"{base}/{quote}"


def _trading_kind(evidence: BoundedDatasetEvidence) -> str | None:
    blob = evidence.trading_classification or {}
    kind = blob.get("tradingKind") or blob.get("trading_kind")
    return str(kind) if kind else None


def _has_ohlcv_columns(cols: set[str]) -> bool:
    return len(cols & _OHLCV_COLS) >= 4


def _operator_overrides(evidence: BoundedDatasetEvidence) -> dict[str, Any]:
    meta = evidence.metadata or {}
    overrides = meta.get("operatorOverrides") or meta.get("operator_overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}
    # Also accept top-level operator fields in metadata.
    out = dict(overrides)
    for src_key, dst_key in (
        ("operatorDisplayName", "displayName"),
        ("operator_display_name", "displayName"),
        ("operatorCategory", "primaryCategory"),
        ("operator_category", "primaryCategory"),
        ("operatorTags", "tags"),
        ("operator_tags", "tags"),
    ):
        if src_key in meta and dst_key not in out:
            out[dst_key] = meta[src_key]
    semantic = meta.get("semanticProfile") if isinstance(meta.get("semanticProfile"), dict) else {}
    existing_overrides = semantic.get("operatorOverrides") if isinstance(semantic, dict) else None
    if isinstance(existing_overrides, dict):
        for k, v in existing_overrides.items():
            out.setdefault(k, v)
    # Preserve OPERATOR-sourced display name from prior profile.
    if isinstance(semantic, dict):
        if str(semantic.get("displayNameSource") or "") == DisplayNameSource.OPERATOR.value:
            out.setdefault("displayName", semantic.get("displayName"))
            out.setdefault("displayNameSource", DisplayNameSource.OPERATOR.value)
        if semantic.get("operatorCategoryLocked") or str(semantic.get("classificationMethod") or "") == "OPERATOR":
            if semantic.get("primaryCategory"):
                out.setdefault("primaryCategory", semantic.get("primaryCategory"))
            if semantic.get("tags") is not None:
                out.setdefault("tags", semantic.get("tags"))
    return out


def build_deterministic_profile(evidence: BoundedDatasetEvidence) -> DatasetSemanticProfile:
    """Derive a DatasetSemanticProfile from bounded evidence (deterministic only)."""
    overrides = _operator_overrides(evidence)
    cols = _norm_cols(evidence.columns)
    blob = _evidence_blob_text(evidence)
    filename = evidence.filename or ""
    kind = _trading_kind(evidence)

    primary = DatasetCategory.UNCATEGORIZED
    secondary: DatasetCategory | None = None
    category_path: list[str] = []
    tags: list[str] = []
    subjects: list[str] = []
    display_name = ""
    display_source = DisplayNameSource.FALLBACK
    confidence = 0.15
    review_required = True
    evidence_bits: list[str] = []

    # --- Strong: animals / biology ---
    animal_hit = bool(_ANIMAL_RX.search(blob) or (cols & _SPECIES_COL_HINTS) or (cols & _POPULATION_HINTS and _ANIMAL_RX.search(blob)))
    bear_hit = bool(_BEAR_RX.search(blob))
    ursus = bool(_URSUS_ARCTOS_RX.search(blob))
    if ursus or bear_hit or (animal_hit and (cols & _SPECIES_COL_HINTS)):
        primary = DatasetCategory.ANIMALS_BIOLOGY
        category_path = ["ANIMALS_BIOLOGY", "WILDLIFE"]
        tags.extend(["wildlife", "animals", "biology"])
        if ursus or bear_hit:
            tags.extend(["bears", "ursus"])
            subjects.append("Ursus arctos" if ursus else "bears")
            display_name = "Brown bears (Ursus arctos)" if ursus else "Bear wildlife observations"
            evidence_bits.append("species_or_bear_evidence")
        else:
            display_name = "Wildlife / species observations"
            evidence_bits.append("animal_species_columns")
        display_source = DisplayNameSource.DETERMINISTIC
        confidence = 0.88 if ursus else 0.78
        review_required = False
        secondary = DatasetCategory.GEOGRAPHY_ENVIRONMENT

    # --- Strong: OHLCV / trading (does not replace trading classification) ---
    ohlcv_cols = _has_ohlcv_columns(cols) and len(cols & _OHLCV_COLS) >= 4
    ohlcv_name = bool(_OHLCV_NAME_RX.search(filename) or _OHLCV_NAME_RX.search(blob))
    is_market_ohlcv = kind == TradingDatasetKind.MARKET_OHLCV.value or ohlcv_cols or (
        ohlcv_name and len(cols & _OHLCV_COLS) >= 3
    )
    if is_market_ohlcv and primary == DatasetCategory.UNCATEGORIZED:
        primary = DatasetCategory.FINANCE_TRADING
        pair = _detect_crypto_pair(blob) or _detect_crypto_pair(filename)
        cryptoish = bool(pair or _CRYPTO_HINT_RX.search(blob) or _CRYPTO_HINT_RX.search(filename))
        if cryptoish:
            secondary = DatasetCategory.CRYPTO_BLOCKCHAIN
            category_path = ["FINANCE_TRADING", "CRYPTO_BLOCKCHAIN", "OHLCV"]
            tags.extend(["crypto", "ohlcv", "trading"])
        else:
            category_path = ["FINANCE_TRADING", "OHLCV"]
            tags.extend(["ohlcv", "trading", "market"])
        if pair:
            display_name = f"{pair} OHLCV"
            subjects.append(pair)
            evidence_bits.append(f"crypto_pair={pair}")
        else:
            # Try symbol from filename stem.
            stem = filename.rsplit(".", 1)[0] if filename else ""
            stem_clean = re.sub(r"(?i)[_\-]?(ohlcv|ohlc|1m|5m|15m|1h|1d|daily)", "", stem).strip("_- ")
            if stem_clean and not is_machine_name(stem_clean):
                display_name = f"{stem_clean.upper()} OHLCV"
            else:
                display_name = "Market OHLCV"
        display_source = DisplayNameSource.DETERMINISTIC
        confidence = 0.9 if pair else 0.82
        review_required = False
        evidence_bits.append("ohlcv_columns_or_trading_kind")

    # --- Source metadata / non-machine filename ---
    if primary == DatasetCategory.UNCATEGORIZED:
        meta_title = (
            (evidence.metadata or {}).get("displayName")
            or (evidence.metadata or {}).get("title")
            or (evidence.metadata or {}).get("name")
        )
        if meta_title and not is_machine_name(str(meta_title)):
            display_name = str(meta_title).strip()[:160]
            display_source = DisplayNameSource.SOURCE_METADATA
            primary = DatasetCategory.GENERAL
            category_path = ["GENERAL"]
            confidence = 0.45
            review_required = True
            evidence_bits.append("source_metadata_title")
        elif filename and not is_machine_name(filename):
            stem = filename.rsplit(".", 1)[0]
            display_name = stem.replace("_", " ").replace("-", " ").strip()[:160]
            display_source = DisplayNameSource.SOURCE_FILENAME
            primary = DatasetCategory.GENERAL
            category_path = ["GENERAL"]
            confidence = 0.35
            review_required = True
            evidence_bits.append("source_filename")

    # --- Unknown / machine names ---
    if primary == DatasetCategory.UNCATEGORIZED or not display_name:
        primary = DatasetCategory.UNCATEGORIZED
        category_path = category_path or ["UNCATEGORIZED"]
        review_required = True
        confidence = min(confidence, 0.2)
        if not display_name:
            if filename:
                display_name = filename
                display_source = DisplayNameSource.FALLBACK
            else:
                display_name = f"Dataset {evidence.dataset_id[:8]}"
                display_source = DisplayNameSource.FALLBACK
        evidence_bits.append("uncategorized_low_confidence")

    # Deduplicate tags
    seen_tags: set[str] = set()
    clean_tags: list[str] = []
    for t in tags:
        key = t.lower()
        if key in seen_tags:
            continue
        seen_tags.add(key)
        clean_tags.append(t)

    profile = DatasetSemanticProfile(
        schema_version=SEMANTIC_SCHEMA_VERSION,
        display_name=display_name[:160],
        display_name_source=display_source,
        summary=_build_summary(primary, secondary, evidence_bits),
        primary_category=primary,
        secondary_category=secondary,
        category_path=category_path,
        tags=clean_tags,
        subjects=subjects[:16],
        language=None,
        confidence=float(confidence),
        review_required=bool(review_required),
        classification_method="DETERMINISTIC",
        evidence_summary="; ".join(evidence_bits)[:2000],
        source_dataset_id=evidence.dataset_id,
        source_version_id=evidence.version_id,
        source_content_hash=evidence.content_hash,
        generator_version=GENERATOR_VERSION,
        model_status="NOT_REQUESTED",
        model_provenance={},
        operator_overrides={},
        truth={
            "tradingClassificationUntouched": True,
            "samplesTreatedAsDataOnly": True,
        },
    )

    # Operator precedence — never overwrite OPERATOR fields.
    return apply_operator_precedence(profile, overrides)


def apply_operator_precedence(
    profile: DatasetSemanticProfile,
    overrides: Mapping[str, Any] | None,
) -> DatasetSemanticProfile:
    """Merge operator overrides without clobbering OPERATOR-owned fields later."""
    if not overrides:
        return profile
    data = profile.to_dict()
    locked: dict[str, Any] = dict(profile.operator_overrides)
    if overrides.get("displayName") or overrides.get("display_name"):
        name = str(overrides.get("displayName") or overrides.get("display_name")).strip()
        if name:
            data["displayName"] = name[:160]
            data["displayNameSource"] = DisplayNameSource.OPERATOR.value
            locked["displayName"] = data["displayName"]
            locked["displayNameSource"] = DisplayNameSource.OPERATOR.value
    if overrides.get("primaryCategory") or overrides.get("primary_category"):
        data["primaryCategory"] = str(
            overrides.get("primaryCategory") or overrides.get("primary_category")
        ).upper()
        data["classificationMethod"] = "OPERATOR"
        locked["primaryCategory"] = data["primaryCategory"]
        # Keep path consistent with operator primary when provided.
        path = list(data.get("categoryPath") or [])
        if not path or path[0] != data["primaryCategory"]:
            data["categoryPath"] = [data["primaryCategory"], *path[1:]]
    if overrides.get("secondaryCategory") or overrides.get("secondary_category"):
        data["secondaryCategory"] = str(
            overrides.get("secondaryCategory") or overrides.get("secondary_category")
        ).upper()
        locked["secondaryCategory"] = data["secondaryCategory"]
    if "tags" in overrides or "operatorTags" in overrides:
        tags = overrides.get("tags") if "tags" in overrides else overrides.get("operatorTags")
        if isinstance(tags, list):
            data["tags"] = [str(t)[:64] for t in tags[:32]]
            locked["tags"] = list(data["tags"])
    if overrides.get("summary"):
        data["summary"] = str(overrides["summary"])[:2000]
        locked["summary"] = data["summary"]
    data["operatorOverrides"] = locked
    data["truth"] = {
        **dict(data.get("truth") or {}),
        "operatorOverridesWin": True,
    }
    return DatasetSemanticProfile.from_dict(data)


def _build_summary(
    primary: DatasetCategory,
    secondary: DatasetCategory | None,
    evidence_bits: list[str],
) -> str:
    parts = [f"Primary category {primary.value}"]
    if secondary:
        parts.append(f"secondary {secondary.value}")
    if evidence_bits:
        parts.append("evidence: " + ", ".join(evidence_bits[:6]))
    return "; ".join(parts)[:500]
