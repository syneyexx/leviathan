"""Honest embedding provider resolution (auto → ST local / hash / null).

Never auto-downloads models when sentence-transformers is unavailable or uncached.
"""

from __future__ import annotations

from typing import Any

from Data.modules.knowledge.embeddings import (
    EmbeddingProvider,
    LocalHashEmbeddingProvider,
    NullEmbeddingProvider,
    SentenceTransformersEmbeddingProvider,
)


def _st_importable() -> tuple[bool, str | None]:
    try:
        import sentence_transformers  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"sentence-transformers unavailable: {exc}"
    return True, None


def _hf_model_locally_cached(model_name: str) -> tuple[bool, str | None]:
    """Return True only when the model snapshot is already on disk."""
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # noqa: BLE001
        return False, f"huggingface_hub unavailable for cache probe: {exc}"
    try:
        snapshot_download(repo_id=model_name, local_files_only=True)
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, f"model not in local cache: {exc}"


def _try_st_provider(
    model_name: str,
    *,
    allow_download: bool,
) -> tuple[SentenceTransformersEmbeddingProvider | None, str | None]:
    ok, err = _st_importable()
    if not ok:
        return None, err
    if not allow_download:
        cached, cache_err = _hf_model_locally_cached(model_name)
        if not cached:
            # Fallback: attempt local_files_only load without hub probe.
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore

                SentenceTransformer(model_name, local_files_only=True)
            except Exception as exc:  # noqa: BLE001
                return None, cache_err or f"local ST load failed: {exc}"
    provider = SentenceTransformersEmbeddingProvider(model_name=model_name)
    if provider.available():
        return provider, None
    status = provider.status()
    return None, str(status.get("error") or "sentence_transformers unavailable")


def resolve_embedding_provider(
    kind: str = "auto",
    model_name: str | None = None,
    hash_dimensions: int = 256,
) -> tuple[EmbeddingProvider, dict[str, Any]]:
    """Resolve an embedding provider and return truthful resolution metadata.

    ``auto`` policy:
    - Prefer sentence-transformers when model is configured OR ST is importable
      and a local model is already available (no auto-download).
    - Otherwise LocalHash (deterministic, nonsemantic).
    - Never pretends hash vectors are semantic embeddings.
    """
    configured = (kind or "null").strip().lower() or "null"
    default_model = "sentence-transformers/all-MiniLM-L6-v2"
    name = (model_name or "").strip() or None

    info: dict[str, Any] = {
        "configured": configured,
        "configured_model": name,
        "effective": None,
        "semantic": False,
        "reason": None,
        "truth": {
            "auto_never_downloads_when_unavailable": True,
            "hash_is_not_semantic": True,
            "unavailable_is_not_success": True,
        },
    }

    if configured in {"null", "none", "off"}:
        provider: EmbeddingProvider = NullEmbeddingProvider()
        info["effective"] = provider.provider_id
        info["semantic"] = False
        info["reason"] = "explicit_null"
        return provider, info

    if configured in {"hash", "local_hash", "local"}:
        provider = LocalHashEmbeddingProvider(dimensions=hash_dimensions)
        info["effective"] = provider.provider_id
        info["semantic"] = False
        info["reason"] = "explicit_hash"
        return provider, info

    if configured in {"sentence_transformers", "st", "sbert", "huggingface", "hf"}:
        st_name = name or default_model
        # Explicit ST request may download — caller opted into the provider kind.
        provider_st, err = _try_st_provider(st_name, allow_download=True)
        if provider_st is not None:
            info["effective"] = provider_st.provider_id
            info["semantic"] = True
            info["reason"] = "sentence_transformers"
            info["model_name"] = st_name
            return provider_st, info
        # Honest degrade: return the unavailable ST provider object (matches prior factory).
        degraded = SentenceTransformersEmbeddingProvider(model_name=st_name)
        info["effective"] = degraded.provider_id
        info["semantic"] = False
        info["reason"] = err or "sentence_transformers_unavailable"
        info["model_name"] = st_name
        return degraded, info

    if configured != "auto":
        raise ValueError(f"Unknown embedding provider kind: {kind!r}")

    # --- auto resolution (no download) ---
    st_ok, st_err = _st_importable()
    candidate_model = name or default_model
    try_st = bool(name) or st_ok
    if try_st and st_ok:
        provider_st, err = _try_st_provider(candidate_model, allow_download=False)
        if provider_st is not None:
            info["effective"] = provider_st.provider_id
            info["semantic"] = True
            info["reason"] = (
                "auto_sentence_transformers_configured"
                if name
                else "auto_sentence_transformers_local"
            )
            info["model_name"] = candidate_model
            return provider_st, info
        info["st_probe_error"] = err
    elif not st_ok:
        info["st_probe_error"] = st_err

    provider = LocalHashEmbeddingProvider(dimensions=hash_dimensions)
    info["effective"] = provider.provider_id
    info["semantic"] = False
    if not st_ok:
        info["reason"] = "auto_fallback_hash_st_unavailable"
    elif name:
        info["reason"] = "auto_fallback_hash_model_not_local"
    else:
        info["reason"] = "auto_fallback_hash_no_local_semantic_model"
    return provider, info


def resolve_embedding_provider_auto(
    kind: str = "auto",
    model_name: str | None = None,
    hash_dimensions: int = 256,
) -> tuple[EmbeddingProvider, dict[str, Any]]:
    """Public alias used by the intelligence substrate export surface."""
    return resolve_embedding_provider(
        kind=kind,
        model_name=model_name,
        hash_dimensions=hash_dimensions,
    )
