"""Production Neural encoder backends (V2).

Two backends:

* ``toy`` — hash tokenizer + toy transformer (research / unit tests only).
* ``lm_studio_embedding`` — frozen vectors from local LM Studio embeddings.

Production Neural (``neural_allow`` + mode ≠ off) must use embeddings when an
``embedding_model_id`` is configured. Never silently fall back to toy in
production. PyTorch is not imported at module load.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from neural.errors import NeuralError


class NeuralEncoderError(NeuralError):
    code = "neural_encoder_error"


class EncoderNotReady(NeuralEncoderError):
    code = "neural_encoder_not_ready"


class EncoderBackend(str, Enum):
    TOY = "toy"
    LM_STUDIO_EMBEDDING = "lm_studio_embedding"


# Architecture / schema markers for V2 production memory.
PRODUCTION_ARCHITECTURE_VERSION = "parametric_mlp_v2_embedding"
TOY_ARCHITECTURE_VERSION = "parametric_mlp_v2_toy"
NEURAL_MEMORY_SCHEMA_VERSION = 2


@runtime_checkable
class NeuralTextEncoder(Protocol):
    """Frozen text → vector encoder used by Neural Memory."""

    @property
    def encoder_id(self) -> str: ...

    @property
    def backend(self) -> EncoderBackend: ...

    @property
    def dimension(self) -> int: ...

    @property
    def ready(self) -> bool: ...

    def encode_text(self, text: str) -> Any: ...

    def encode_texts(self, texts: Sequence[str]) -> list[Any]: ...

    def status(self) -> dict[str, Any]: ...


def _l2_normalize_list(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(x) * float(x) for x in vector))
    if not math.isfinite(norm) or norm <= 0.0:
        raise NeuralEncoderError("non-finite or zero embedding norm")
    return [float(x) / norm for x in vector]


@dataclass(frozen=True)
class FrozenEmbeddingVector:
    """Torch-free embedding vector with a tensor-like ``shape`` for callers.

    Production dual-retrieval cosine scoring must work without importing
    PyTorch. Parametric ``NeuralMemory`` paths that need tensors should call
    ``vector_to_tensor`` explicitly.
    """

    values: tuple[float, ...]

    @property
    def shape(self) -> tuple[int, ...]:
        return (len(self.values),)

    def tolist(self) -> list[float]:
        return list(self.values)

    def detach(self) -> "FrozenEmbeddingVector":
        return self

    def cpu(self) -> "FrozenEmbeddingVector":
        return self

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self):
        return iter(self.values)


def vector_to_tensor(vector: Sequence[float], *, device: str = "cpu") -> Any:
    """Convert a Python float vector to a torch tensor (lazy torch import)."""
    from neural.deps import require_torch

    torch = require_torch()
    tensor = torch.as_tensor(list(vector), dtype=torch.float32, device=device)
    if not torch.isfinite(tensor).all():
        raise NeuralEncoderError("non-finite encoder tensor")
    return torch.nn.functional.normalize(tensor, dim=0)


@dataclass
class ToyNeuralEncoder:
    """Test-only encoder wrapping the Phase 4 FrozenTextEncoder / toy runtime."""

    runtime: Any
    _frozen: Any = None

    def __post_init__(self) -> None:
        from neural.encoding import FrozenTextEncoder

        self._frozen = FrozenTextEncoder(self.runtime)

    @property
    def encoder_id(self) -> str:
        return "toy_transformer_v1"

    @property
    def backend(self) -> EncoderBackend:
        return EncoderBackend.TOY

    @property
    def dimension(self) -> int:
        return int(self._frozen.hidden_size)

    @property
    def ready(self) -> bool:
        return self._frozen is not None

    def encode_text(self, text: str) -> Any:
        return self._frozen.encode_text(text)

    def encode_texts(self, texts: Sequence[str]) -> list[Any]:
        return [self.encode_text(t) for t in texts]

    def status(self) -> dict[str, Any]:
        return {
            "encoder_id": self.encoder_id,
            "backend": self.backend.value,
            "dimension": self.dimension,
            "ready": self.ready,
            "production": False,
            "note": "toy encoder is research/test-only",
        }


@dataclass
class LmStudioEmbeddingEncoder:
    """Frozen local embedding vectors (LM Studio / OpenAI-compatible).

    Accepts either a ``LocalEmbeddingProvider``-like object with ``embed_one`` /
    ``embed_texts``, or an injectable ``embed_fn`` for tests.
    """

    model_id: str
    embed_fn: Callable[[str], Sequence[float]] | None = None
    provider: Any | None = None
    expected_dimension: int | None = None
    device: str = "cpu"
    _locked_dim: int | None = None
    _last_error: str | None = None

    def __post_init__(self) -> None:
        self.model_id = str(self.model_id or "").strip()
        if self.expected_dimension is not None:
            self._locked_dim = int(self.expected_dimension)

    @property
    def encoder_id(self) -> str:
        return f"lm_studio_embedding:{self.model_id or 'unconfigured'}"

    @property
    def backend(self) -> EncoderBackend:
        return EncoderBackend.LM_STUDIO_EMBEDDING

    @property
    def dimension(self) -> int:
        if self._locked_dim is None:
            raise EncoderNotReady(
                "embedding dimension unknown until first successful encode",
                detail={"model_id": self.model_id},
            )
        return int(self._locked_dim)

    @property
    def ready(self) -> bool:
        if not self.model_id:
            return False
        if self.embed_fn is None and self.provider is None:
            return False
        return self._last_error is None

    def _raw_embed(self, text: str) -> list[float]:
        if self.embed_fn is not None:
            raw = self.embed_fn(text)
        elif self.provider is not None:
            raw = self.provider.embed_one(text)
        else:
            raise EncoderNotReady(
                "no embedding provider configured",
                detail={"model_id": self.model_id},
            )
        vector = [float(x) for x in raw]
        if not vector:
            raise NeuralEncoderError("empty embedding vector")
        return _l2_normalize_list(vector)

    def _lock_dim(self, dim: int) -> None:
        if dim < 1:
            raise NeuralEncoderError("embedding dimension must be >= 1")
        if self._locked_dim is None:
            self._locked_dim = dim
            return
        if dim != self._locked_dim:
            # Prefer embeddings.DimensionMismatchError when the package is
            # importable; otherwise raise a typed NeuralEncoderError so tests /
            # offline hosts without httpx still fail closed.
            detail = {"expected": self._locked_dim, "got": dim, "model_id": self.model_id}
            try:
                from embeddings import DimensionMismatchError

                raise DimensionMismatchError(
                    "neural encoder dimension mismatch",
                    detail=detail,
                )
            except ImportError:
                raise NeuralEncoderError(
                    "neural encoder dimension mismatch",
                    detail=detail,
                ) from None

    def encode_text(self, text: str) -> Any:
        """Encode text to a frozen vector.

        Returns a torch tensor only when PyTorch is available; otherwise a
        ``FrozenEmbeddingVector`` so production Chat dual retrieval stays
        torch-free (ADR-N2). Never silently falls back to the toy encoder.
        """
        try:
            vector = self._raw_embed(text)
            self._lock_dim(len(vector))
            self._last_error = None
            try:
                from neural.deps import neural_available

                if neural_available():
                    return vector_to_tensor(vector, device=self.device)
            except Exception:
                pass
            return FrozenEmbeddingVector(tuple(vector))
        except Exception as exc:  # noqa: BLE001 — surface typed readiness
            self._last_error = type(exc).__name__
            raise

    def encode_texts(self, texts: Sequence[str]) -> list[Any]:
        return [self.encode_text(t) for t in texts]

    def encode_text_list(self, text: str) -> list[float]:
        """Return a normalized Python list (no torch) for callers that only score."""
        vector = self._raw_embed(text)
        self._lock_dim(len(vector))
        self._last_error = None
        return vector

    def status(self) -> dict[str, Any]:
        return {
            "encoder_id": self.encoder_id,
            "backend": self.backend.value,
            "dimension": self._locked_dim,
            "ready": self.ready and self._locked_dim is not None,
            "production": True,
            "model_id": self.model_id,
            "last_error": self._last_error,
        }


def resolve_production_encoder_backend(
    settings: Mapping[str, Any] | None = None,
    *,
    explicit: str | EncoderBackend | None = None,
) -> EncoderBackend:
    """Choose encoder backend.

    Explicit ``encoder=toy`` wins (tests). Otherwise production prefers
    ``lm_studio_embedding`` when ``embedding_model_id`` is set.
    """
    if explicit is not None:
        return EncoderBackend(explicit) if isinstance(explicit, str) else explicit
    settings = settings or {}
    raw = settings.get("neural_encoder")
    if raw is not None:
        return EncoderBackend(str(raw).strip().lower())
    model_id = str(settings.get("embedding_model_id") or "").strip()
    if model_id:
        return EncoderBackend.LM_STUDIO_EMBEDDING
    # No embedding model → not a production-ready default; callers must treat as not ready.
    return EncoderBackend.LM_STUDIO_EMBEDDING


def build_encoder(
    *,
    encoder: str | EncoderBackend | None = None,
    settings: Mapping[str, Any] | None = None,
    runtime: Any | None = None,
    embed_fn: Callable[[str], Sequence[float]] | None = None,
    provider: Any | None = None,
    expected_dimension: int | None = None,
    device: str = "cpu",
) -> NeuralTextEncoder:
    """Construct a Neural text encoder.

    Production path never invents a toy encoder when embeddings are intended.
    """
    settings = settings or {}
    backend = resolve_production_encoder_backend(settings, explicit=encoder)

    if backend is EncoderBackend.TOY:
        if runtime is None:
            raise EncoderNotReady(
                "toy encoder requires an explicit Neural runtime",
                detail={"encoder": "toy"},
            )
        return ToyNeuralEncoder(runtime=runtime)

    model_id = str(settings.get("embedding_model_id") or "").strip()
    if provider is None and embed_fn is None and model_id:
        try:
            from embeddings import provider_from_settings

            provider = provider_from_settings(dict(settings))
        except Exception:
            provider = None

    if not model_id and embed_fn is None and provider is None:
        raise EncoderNotReady(
            "embedding_model_id unset; production Neural encoder not ready",
            detail={"backend": backend.value},
        )

    if provider is not None and not model_id:
        model_id = str(getattr(provider, "model_id", "") or "provider")

    enc = LmStudioEmbeddingEncoder(
        model_id=model_id or "unconfigured",
        embed_fn=embed_fn,
        provider=provider,
        expected_dimension=expected_dimension,
        device=device,
    )
    if not enc.ready:
        raise EncoderNotReady(
            "lm_studio_embedding encoder not ready",
            detail=enc.status(),
        )
    return enc


def memory_config_for_encoder(
    encoder: NeuralTextEncoder,
    *,
    mode: Any = None,
    seed: int = 0,
    **overrides: Any,
) -> Any:
    """Build a NeuralMemoryConfig matched to an encoder's dimension + arch."""
    from neural.config import NeuralMemoryConfig
    from neural.contracts import NeuralMode

    if mode is None:
        mode = NeuralMode.OFF
    elif isinstance(mode, str):
        mode = NeuralMode(mode)

    dim = int(encoder.dimension)
    arch = (
        TOY_ARCHITECTURE_VERSION
        if encoder.backend is EncoderBackend.TOY
        else PRODUCTION_ARCHITECTURE_VERSION
    )
    payload = {
        "dim": dim,
        "hidden_dim": max(64, dim * 2),
        "fast_hidden_dim": max(32, dim),
        "mode": mode,
        "seed": seed,
        "architecture_version": arch,
        "schema_version": NEURAL_MEMORY_SCHEMA_VERSION,
        "extra": {
            "encoder_id": encoder.encoder_id,
            "encoder_backend": encoder.backend.value,
        },
    }
    payload.update(overrides)
    return NeuralMemoryConfig.from_dict(payload)
