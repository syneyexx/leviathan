from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface for vector embeddings.

    Knowledge must not fabricate vectors when a provider is unavailable.
    """

    provider_id: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...

    def available(self) -> bool:
        ...

    def status(self) -> dict[str, Any]:
        ...


class NullEmbeddingProvider:
    """Explicit no-embedding provider — hybrid retrieval falls back to lexical only."""

    provider_id = "null"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("NullEmbeddingProvider cannot embed documents")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("NullEmbeddingProvider cannot embed queries")

    def available(self) -> bool:
        return False

    def status(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "available": False,
            "reason": "null_provider",
            "is_semantic": False,
            "truth": {"unavailable_is_not_success": True},
        }

    @property
    def is_semantic(self) -> bool:
        return False


def _tokenize(text: str) -> list[str]:
    # Unicode letters/digits so Dutch (and other) queries are not silently zeroed.
    return re.findall(r"[^\W_]{2,}", text.lower(), flags=re.UNICODE)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 1e-12:
        return vec
    return [v / norm for v in vec]


@dataclass
class LocalHashEmbeddingProvider:
    """Deterministic local bag-of-hashes embeddings (no heavy deps).

    Always available. Not a neural embedding model — honest about that.
    Suitable for hybrid fusion tests and offline dense-ish retrieval.
    """

    dimensions: int = 256
    provider_id: str = "local_hash"

    def available(self) -> bool:
        return True

    def status(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "available": True,
            "dimensions": self.dimensions,
            "production_grade": False,
            "is_semantic": False,
            "truth": {
                "hash_embedding_is_not_neural_model": True,
                "hash_vectors_are_not_semantic_embeddings": True,
                "local_deterministic": True,
            },
        }

    @property
    def is_semantic(self) -> bool:
        return False

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        tokens = _tokenize(text)
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            # Two signed feature hashes per token (feature hashing).
            for offset in (0, 8):
                bucket = int.from_bytes(digest[offset : offset + 4], "little") % self.dimensions
                sign = 1.0 if digest[offset + 4] % 2 == 0 else -1.0
                vec[bucket] += sign
        return _l2_normalize(vec)


@dataclass
class SentenceTransformersEmbeddingProvider:
    """Optional sentence-transformers local backend.

    Unavailable when deps/model missing — never fabricates vectors as success.
    Heavy dependency stays optional; Core remains importable without it.
    """

    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    provider_id: str = "sentence_transformers"
    _model: Any = field(default=None, repr=False)
    _error: str | None = field(default=None, repr=False)
    _dimensions: int | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self._error = f"sentence-transformers unavailable: {exc}"
            return
        try:
            self._model = SentenceTransformer(self.model_name)
            probe = self._model.encode(["probe"], normalize_embeddings=True)
            self._dimensions = int(len(probe[0]))
            self._error = None
        except Exception as exc:  # noqa: BLE001
            self._model = None
            self._error = f"sentence-transformers model load failed: {exc}"

    def available(self) -> bool:
        return self._model is not None

    def status(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "available": self.available(),
            "model_name": self.model_name,
            "dimensions": self._dimensions,
            "error": self._error,
            "production_grade": self.available(),
            "is_semantic": self.available(),
            "truth": {
                "optional_dependency": True,
                "unavailable_is_not_success": True,
                "neural_embeddings_when_available": self.available(),
            },
        }

    @property
    def is_semantic(self) -> bool:
        return self.available()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            raise RuntimeError(self._error or "SentenceTransformersEmbeddingProvider unavailable")
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, row)) for row in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@dataclass
class RerankerProvider:
    """Optional local cross-encoder reranker. Honest unavailable when deps missing."""

    model_name: str | None = None
    provider_id: str = "cross_encoder"
    _model: Any = field(default=None, repr=False)
    _error: str | None = field(default="reranker_not_configured", repr=False)

    def __post_init__(self) -> None:
        if not self.model_name:
            self._error = "LEVIATHAN_RERANKER_MODEL unset"
            return
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self._error = f"CrossEncoder unavailable: {exc}"
            return
        try:
            self._model = CrossEncoder(self.model_name)
            self._error = None
        except Exception as exc:  # noqa: BLE001
            self._model = None
            self._error = f"reranker model load failed: {exc}"

    def available(self) -> bool:
        return self._model is not None

    def status(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "available": self.available(),
            "model_name": self.model_name,
            "error": self._error,
            "truth": {"unavailable_is_not_success": True},
        }

    def score(self, query: str, passages: list[str]) -> list[float]:
        if self._model is None:
            raise RuntimeError(self._error or "RerankerProvider unavailable")
        pairs = [(query, passage) for passage in passages]
        scores = self._model.predict(pairs)
        return [float(s) for s in scores]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def build_embedding_provider(
    *,
    kind: str = "null",
    model_name: str | None = None,
    hash_dimensions: int = 256,
) -> EmbeddingProvider:
    """Factory used by Core. Never auto-installs packages.

    ``kind="auto"`` resolves via the intelligence substrate resolver:
    local sentence-transformers when already available, else LocalHash.
    Never auto-downloads when ST is unavailable.
    """
    normalized = (kind or "null").strip().lower()
    if normalized == "auto":
        from Data.modules.intelligence.embeddings_resolve import resolve_embedding_provider

        provider, _info = resolve_embedding_provider(
            kind="auto",
            model_name=model_name,
            hash_dimensions=hash_dimensions,
        )
        return provider
    if normalized in {"null", "none", "off"}:
        return NullEmbeddingProvider()
    if normalized in {"hash", "local_hash", "local"}:
        return LocalHashEmbeddingProvider(dimensions=hash_dimensions)
    if normalized in {"sentence_transformers", "st", "sbert", "huggingface", "hf"}:
        name = (model_name or "sentence-transformers/all-MiniLM-L6-v2").strip()
        provider = SentenceTransformersEmbeddingProvider(model_name=name)
        if provider.available():
            return provider
        # Honest degrade: keep Null rather than silently claiming ST success.
        # Callers may choose LocalHash separately when RAG_V3 wants dense fusion offline.
        return provider
    raise ValueError(f"Unknown embedding provider kind: {kind!r}")
