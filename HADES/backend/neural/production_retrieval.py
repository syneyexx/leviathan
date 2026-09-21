"""Production Exact + Neural dual retrieval wiring (Neural V2).

Builds retrieve callables for ``assemble_chat_context_messages`` from live
settings / encoder / memory banks. Exact Brain stays evidence-grade; Neural
candidates are always ``neural_association`` / ``trusted=False``.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from neural.dual_retrieval import RetrievalCandidate
from neural.domain_memory import DomainMemoryRegistry, route_domains
from neural.encoder import (
    EncoderBackend,
    EncoderNotReady,
    NeuralTextEncoder,
    build_encoder,
)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    na = sum(float(x) * float(x) for x in a) ** 0.5
    nb = sum(float(y) * float(y) for y in b) ** 0.5
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(dot / (na * nb))


def make_exact_retrieve_fn(
    exact_items: Sequence[Mapping[str, Any]] | None = None,
    *,
    retrieve_fn: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
) -> Callable[[str], list[RetrievalCandidate]]:
    """Wrap Exact Brain / knowledge hits as evidence-grade candidates."""

    def _retrieve(query: str) -> list[RetrievalCandidate]:
        raw: Sequence[Mapping[str, Any]]
        if retrieve_fn is not None:
            raw = retrieve_fn(query)
        else:
            raw = list(exact_items or [])
        out: list[RetrievalCandidate] = []
        for index, item in enumerate(raw):
            content = str(item.get("content") or item.get("text") or "").strip()
            if not content:
                continue
            out.append(
                RetrievalCandidate(
                    candidate_id=str(item.get("id") or item.get("candidate_id") or f"exact-{index}"),
                    candidate_type="exact",
                    content=content,
                    score=float(item.get("score") or item.get("relevance") or 0.5),
                    confidence=float(item.get("confidence") or item.get("score") or 0.5),
                    domain=str(item.get("domain") or "general"),
                    provenance_status="exact_source",
                    source_ref=str(item.get("provenance") or item.get("source_ref") or item.get("uri") or ""),
                    metadata={k: v for k, v in item.items() if k not in {"content", "text"}},
                )
            )
        return out

    return _retrieve


def make_neural_retrieve_fn(
    *,
    encoder: NeuralTextEncoder,
    associations: Sequence[Mapping[str, Any]] | None = None,
    memory: Any | None = None,
    domain_registry: DomainMemoryRegistry | None = None,
    allow_trading: bool = False,
    checkpoint_id: str | None = None,
    max_results: int = 4,
) -> Callable[[str], list[RetrievalCandidate]]:
    """Score stored neural associations against an encoded query.

    ``associations`` is the preferred production path when vectors are already
    stored as text key/value pairs with optional precomputed vectors. When a
    live ``NeuralMemory`` is provided, parametric ``read`` scores are used.
    """

    def _retrieve(query: str) -> list[RetrievalCandidate]:
        if not encoder.ready:
            raise EncoderNotReady("neural retrieve requires a ready encoder", detail=encoder.status())

        route = None
        if domain_registry is not None:
            route = domain_registry.select_for_task(query, allow_trading=allow_trading)
        else:
            route = route_domains(query, allow_trading=allow_trading)

        query_vec = None
        # Prefer list path when available to avoid forcing torch for pure scoring.
        if hasattr(encoder, "encode_text_list"):
            query_vec = list(encoder.encode_text_list(query))  # type: ignore[attr-defined]
        else:
            encoded = encoder.encode_text(query)
            if hasattr(encoded, "tolist") and not hasattr(encoded, "detach"):
                query_vec = [float(x) for x in encoded.tolist()]
            elif hasattr(encoded, "detach"):
                # Torch tensor *or* FrozenEmbeddingVector (detach/cpu no-ops).
                detached = encoded.detach()
                if hasattr(detached, "cpu"):
                    detached = detached.cpu()
                if hasattr(detached, "tolist"):
                    query_vec = [float(x) for x in detached.tolist()]
                else:
                    query_vec = [float(x) for x in detached]
            else:
                query_vec = [float(x) for x in encoded]

        scored: list[RetrievalCandidate] = []

        if memory is not None and query_vec is not None:
            from neural.contracts import NeuralMode

            previous = memory.mode
            try:
                if previous is NeuralMode.OFF:
                    memory.set_mode(NeuralMode.READ)
                key = encoder.encode_text(query) if not hasattr(encoder, "encode_text_list") else None
                if key is None:
                    from neural.encoder import vector_to_tensor

                    key = vector_to_tensor(query_vec, device=getattr(memory, "device", "cpu"))
                result = memory.read(key)
                if result.value is not None:
                    # Cosine against identity is not meaningful; surface diagnostics
                    # and fall through to association bank when present.
                    score = float(result.diagnostics.get("score") or 0.0)
                    if associations is None and score > 0:
                        scored.append(
                            RetrievalCandidate(
                                candidate_id="neural-memory-read",
                                candidate_type="neural",
                                content=str(result.diagnostics.get("summary") or "neural memory association"),
                                score=score,
                                confidence=score,
                                domain=route.primary.value,
                                checkpoint_id=checkpoint_id,
                                provenance_status="neural_association",
                                metadata={"route": route.to_dict(), "trusted": False},
                            )
                        )
            finally:
                if previous is NeuralMode.OFF:
                    memory.set_mode(NeuralMode.OFF)

        for index, item in enumerate(associations or []):
            content = str(item.get("content") or item.get("value_text") or item.get("value") or "").strip()
            key_text = str(item.get("key_text") or item.get("key") or "").strip()
            if not content:
                continue
            domain = str(item.get("domain") or route.primary.value)
            if route is not None and domain not in {d.value for d in route.domains}:
                # Domain routing selects banks; do not leak trading without opt-in.
                continue
            item_vec = item.get("vector") or item.get("key_vector")
            if item_vec is None and key_text:
                if hasattr(encoder, "encode_text_list"):
                    item_vec = encoder.encode_text_list(key_text)  # type: ignore[attr-defined]
                else:
                    enc = encoder.encode_text(key_text)
                    item_vec = enc.detach().cpu().tolist() if hasattr(enc, "detach") else list(enc)
            score = _cosine(query_vec or [], list(item_vec or []))
            if score <= 0.0:
                continue
            scored.append(
                RetrievalCandidate(
                    candidate_id=str(item.get("id") or item.get("candidate_id") or f"neural-{index}"),
                    candidate_type="neural",
                    content=content if not key_text else f"{key_text} → {content}",
                    score=score,
                    confidence=score,
                    domain=domain,
                    checkpoint_id=str(item.get("checkpoint_id") or checkpoint_id or "") or None,
                    provenance_status="neural_association",
                    metadata={
                        "route": route.to_dict() if route else {},
                        "trusted": False,
                        "encoder_id": encoder.encoder_id,
                    },
                )
            )

        scored.sort(key=lambda c: (-c.score, c.candidate_id))
        # Hard enforce: never mark trusted.
        limited: list[RetrievalCandidate] = []
        for cand in scored[: max(0, int(max_results))]:
            limited.append(
                RetrievalCandidate(
                    candidate_id=cand.candidate_id,
                    candidate_type="neural",
                    content=cand.content,
                    score=cand.score,
                    confidence=cand.confidence,
                    domain=cand.domain,
                    checkpoint_id=cand.checkpoint_id,
                    provenance_status="neural_association",
                    source_ref=cand.source_ref,
                    metadata={**dict(cand.metadata), "trusted": False},
                )
            )
        return limited

    return _retrieve


def resolve_production_retrieve_fns(
    settings: Mapping[str, Any],
    *,
    encoder: NeuralTextEncoder | None = None,
    exact_items: Sequence[Mapping[str, Any]] | None = None,
    exact_retrieve_fn: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
    associations: Sequence[Mapping[str, Any]] | None = None,
    memory: Any | None = None,
    domain_registry: DomainMemoryRegistry | None = None,
    embed_fn: Callable[[str], Sequence[float]] | None = None,
) -> dict[str, Any]:
    """Resolve Exact/Neural retrieve hooks for Chat dual retrieval.

    Returns a dict with ``exact_retrieve``, ``neural_retrieve``, ``encoder``,
    ``ready``, and optional ``error``. Never silently substitutes the toy
    encoder for production.
    """
    result: dict[str, Any] = {
        "exact_retrieve": None,
        "neural_retrieve": None,
        "encoder": None,
        "ready": False,
        "error": None,
        "encoder_status": None,
    }

    # Explicit injectables from settings win (tests / host wiring).
    if settings.get("neural_exact_retrieve_fn") is not None:
        result["exact_retrieve"] = settings.get("neural_exact_retrieve_fn")
    else:
        result["exact_retrieve"] = make_exact_retrieve_fn(exact_items, retrieve_fn=exact_retrieve_fn)

    if settings.get("neural_retrieve_fn") is not None:
        result["neural_retrieve"] = settings.get("neural_retrieve_fn")
        result["ready"] = True
        return result

    try:
        if encoder is None:
            explicit = settings.get("neural_encoder")
            if str(explicit or "").strip().lower() == EncoderBackend.TOY.value:
                # Production Chat path must not auto-build toy unless tests inject runtime.
                if settings.get("neural_toy_runtime") is None and embed_fn is None:
                    raise EncoderNotReady(
                        "toy encoder forbidden as silent production fallback",
                        detail={"neural_encoder": "toy"},
                    )
            encoder = build_encoder(
                encoder=explicit,
                settings=settings,
                runtime=settings.get("neural_toy_runtime"),
                embed_fn=embed_fn or settings.get("neural_embed_fn"),
                expected_dimension=settings.get("neural_embedding_dim"),
            )
        if not encoder.ready:
            raise EncoderNotReady("encoder not ready", detail=encoder.status())
        result["encoder"] = encoder
        result["encoder_status"] = encoder.status()
        result["neural_retrieve"] = make_neural_retrieve_fn(
            encoder=encoder,
            associations=associations if associations is not None else settings.get("neural_associations"),
            memory=memory if memory is not None else settings.get("neural_memory"),
            domain_registry=domain_registry,
            allow_trading=bool(settings.get("neural_domain_trading_enabled")),
            checkpoint_id=settings.get("neural_checkpoint_id"),
            max_results=int(settings.get("neural_dual_max_neural") or 2),
        )
        result["ready"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = type(exc).__name__
        result["error_detail"] = str(exc)
        result["ready"] = False
    return result
