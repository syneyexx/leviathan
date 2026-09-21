"""Retrieval comparison harness — lexical vs symbol/impact (Phase D4).

Embeddings remain optional; this measures what is available without inventing scores.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def compare_retrieval_methods(
    root: Path,
    *,
    query: str,
    symbol: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    query_clean = (query or "").strip()
    symbol_clean = (symbol or "").strip() or None

    lexical_hits: list[dict[str, Any]] = []
    try:
        from coding_agent import explore_repository

        hits = explore_repository(root, query_clean or symbol_clean or "code")
        lexical_hits = [h.to_dict() if hasattr(h, "to_dict") else dict(h) for h in hits[:limit]]
    except Exception as exc:
        lexical_hits = [{"error": str(exc)}]

    symbol_hits: list[dict[str, Any]] = []
    try:
        from lsp_light import find_references

        refs = find_references(root, symbol_clean or query_clean or "", limit=limit)
        symbol_hits = list((refs.get("references") if isinstance(refs, dict) else refs) or [])[:limit]
        if isinstance(refs, dict) and refs.get("definitions"):
            symbol_hits = list(refs.get("definitions") or [])[:limit] + symbol_hits
    except Exception:
        try:
            from project_map import find_change_impact

            impact_tmp = find_change_impact(root, symbol=symbol_clean or query_clean, limit=limit)
            symbol_hits = list(impact_tmp.get("references") or impact_tmp.get("callers") or [])[:limit]
        except Exception as exc:
            symbol_hits = [{"error": str(exc)}]

    impact: dict[str, Any] = {}
    try:
        from project_map import find_change_impact

        impact = find_change_impact(root, symbol=symbol_clean or query_clean, limit=limit)
    except Exception as exc:
        impact = {"error": str(exc)}

    lex_paths = {str(h.get("path") or h.get("file") or "") for h in lexical_hits if isinstance(h, dict)}
    sym_paths = {
        str(h.get("path") or h.get("file") or h.get("uri") or "")
        for h in symbol_hits
        if isinstance(h, dict)
    }
    lex_paths.discard("")
    sym_paths.discard("")
    overlap = lex_paths & sym_paths
    only_lex = lex_paths - sym_paths
    only_sym = sym_paths - lex_paths

    return {
        "query": query_clean,
        "symbol": symbol_clean,
        "methods": {
            "lexical_explore": {"count": len(lexical_hits), "hits": lexical_hits[:limit]},
            "symbol_or_impact": {"count": len(symbol_hits), "hits": symbol_hits[:limit]},
            "change_impact": impact,
        },
        "comparison": {
            "overlap_paths": sorted(overlap),
            "only_lexical": sorted(only_lex)[:40],
            "only_symbol": sorted(only_sym)[:40],
            "overlap_count": len(overlap),
            "lexical_count": len(lex_paths),
            "symbol_count": len(sym_paths),
        },
        "embeddings": {
            "used": False,
            "note": "Embeddings optional; not required for this comparison harness.",
        },
        "measurement_method": "lexical_vs_symbol_fixture",
    }
