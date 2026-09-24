"""Canonical model-aware tokenization service (Inference Efficiency Plane).

Resolution order (truthful, never silent download on request path):
  1. EXACT_LOCAL_TOKENIZER — lightweight local artifact / registered fixture
  2. EXACT_RUNTIME_TOKENIZER — runtime-native tokenize without loading weights
  3. PROVIDER_REPORTED — not used for pre-count (post-usage only)
  4. TEMPLATE_AWARE_ESTIMATE — family/template-aware heuristic
  5. HEURISTIC — chars/4 fallback
  6. UNKNOWN — unsafe/unavailable

Does not load 30B/70B weights merely to count tokens.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

from Data.modules.common.hashing import sha256_text

from .bounded_cache import BoundedLRUCache
from .singleflight import SingleFlight
from .types import estimate_tokens


COMPILER_VERSION = "leviathan-tokenization-v1"


class TokenPrecision(str, Enum):
    EXACT_LOCAL_TOKENIZER = "EXACT_LOCAL_TOKENIZER"
    EXACT_RUNTIME_TOKENIZER = "EXACT_RUNTIME_TOKENIZER"
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    TEMPLATE_AWARE_ESTIMATE = "TEMPLATE_AWARE_ESTIMATE"
    HEURISTIC = "HEURISTIC"
    UNKNOWN = "UNKNOWN"


class TokenCountSource(str, Enum):
    LOCAL_TOKENIZER = "local_tokenizer"
    RUNTIME_TOKENIZER = "runtime_tokenizer"
    PROVIDER_USAGE = "provider_usage"
    TEMPLATE_AWARE = "template_aware"
    HEURISTIC_CHARS4 = "heuristic_chars4"
    UNKNOWN = "unknown"
    CACHE = "cache"


@dataclass(frozen=True)
class TokenizationRequest:
    text: str = ""
    messages: tuple[dict[str, Any], ...] = ()
    model_id: str | None = None
    provider_id: str | None = None
    runtime_kind: str | None = None
    model_revision: str | None = None
    tokenizer_id: str | None = None
    tokenizer_revision: str | None = None
    chat_template_id: str | None = None
    chat_template_revision: str | None = None
    tools_schema: Any | None = None
    multimodal_metadata: dict[str, Any] | None = None
    serialization_mode: str = "plain"
    add_generation_prompt: bool = False

    def content_digest(self) -> str:
        payload = {
            "text": self.text,
            "messages": list(self.messages),
            "tools": self.tools_schema,
            "mm": self.multimodal_metadata or {},
            "mode": self.serialization_mode,
            "gen": self.add_generation_prompt,
        }
        return sha256_text(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False))

    def cache_key(self) -> str:
        parts = [
            COMPILER_VERSION,
            self.model_id or "",
            self.provider_id or "",
            self.runtime_kind or "",
            self.model_revision or "",
            self.tokenizer_id or "",
            self.tokenizer_revision or "",
            self.chat_template_id or "",
            self.chat_template_revision or "",
            self.serialization_mode,
            "1" if self.add_generation_prompt else "0",
            self.content_digest(),
        ]
        return sha256_text("|".join(parts))


@dataclass(frozen=True)
class TokenCountResult:
    token_count: int
    source: TokenCountSource
    precision: TokenPrecision
    tokenizer_id: str | None = None
    tokenizer_revision: str | None = None
    chat_template_id: str | None = None
    cached: bool = False
    warnings: tuple[str, ...] = ()
    safety_margin_tokens: int = 0
    truth: dict[str, Any] = field(default_factory=dict)

    @property
    def is_exact(self) -> bool:
        return self.precision in {
            TokenPrecision.EXACT_LOCAL_TOKENIZER,
            TokenPrecision.EXACT_RUNTIME_TOKENIZER,
            TokenPrecision.PROVIDER_REPORTED,
        }

    @property
    def budget_count(self) -> int:
        """Conservative count for budgeting (includes safety margin when not exact)."""
        return int(self.token_count) + int(self.safety_margin_tokens)

    def public_dict(self) -> dict[str, Any]:
        return {
            "tokenCount": int(self.token_count),
            "budgetCount": self.budget_count,
            "source": self.source.value,
            "precision": self.precision.value,
            "tokenizerId": self.tokenizer_id,
            "tokenizerRevision": self.tokenizer_revision,
            "chatTemplateId": self.chat_template_id,
            "cached": bool(self.cached),
            "warnings": list(self.warnings),
            "safetyMarginTokens": int(self.safety_margin_tokens),
            "truth": {
                "is_exact": self.is_exact,
                "heuristic_is_not_exact": self.precision
                in {TokenPrecision.HEURISTIC, TokenPrecision.TEMPLATE_AWARE_ESTIMATE},
                **dict(self.truth),
            },
        }


class TokenizerBackend(Protocol):
    tokenizer_id: str
    tokenizer_revision: str

    def count_text(self, text: str) -> int: ...

    def count_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Any | None = None,
        add_generation_prompt: bool = False,
        chat_template_id: str | None = None,
    ) -> int: ...


@dataclass
class FixtureTokenizer:
    """Deterministic exact tokenizer for tests / known fixtures.

    Encoding: whitespace-delimited tokens + punctuation splits — NOT a real BPE.
    Marked EXACT only because the fixture defines the ground truth for itself.
    Never claim this equals GGUF/HF BPE for production models.
    """

    tokenizer_id: str = "fixture:whitespace_v1"
    tokenizer_revision: str = "1"

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        # Split on whitespace; keep non-empty. Punctuation attached counts as part of token.
        parts = [p for p in text.replace("\n", " \n ").split(" ") if p != ""]
        return max(1, len(parts)) if text.strip() else 0

    def count_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Any | None = None,
        add_generation_prompt: bool = False,
        chat_template_id: str | None = None,
    ) -> int:
        total = 0
        template = chat_template_id or "fixture_chat_v1"
        # Template overhead markers (deterministic).
        total += 2  # BOS-ish
        for msg in messages:
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or "")
            total += 3  # role markers / separators
            total += self.count_text(f"{role}:{content}")
        if tools is not None:
            blob = json.dumps(tools, sort_keys=True, default=str)
            total += 4 + self.count_text(blob)
        if add_generation_prompt:
            total += 2  # assistant prefix
        # Include template id length as tiny constant so template changes invalidate.
        total += len(template) % 7
        return total


@dataclass
class HeuristicTokenizer:
    tokenizer_id: str = "heuristic:chars4"
    tokenizer_revision: str = "1"

    def count_text(self, text: str) -> int:
        return estimate_tokens(text)

    def count_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Any | None = None,
        add_generation_prompt: bool = False,
        chat_template_id: str | None = None,
    ) -> int:
        total = 0
        for msg in messages:
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")
            total += estimate_tokens(role) + estimate_tokens(content) + 4
        if tools is not None:
            total += estimate_tokens(json.dumps(tools, sort_keys=True, default=str)) + 8
        if add_generation_prompt:
            total += 4
        if chat_template_id:
            total += 6  # conservative unknown template overhead
        return total


@dataclass
class TemplateAwareEstimator:
    """Family/template-aware estimate — never labeled exact."""

    tokenizer_id: str = "template_aware:v1"
    tokenizer_revision: str = "1"
    family: str | None = None

    def count_text(self, text: str) -> int:
        base = estimate_tokens(text)
        # Slightly conservative vs chars/4 for chatty templates.
        return int(base * 1.05) + 1 if text else 0

    def count_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Any | None = None,
        add_generation_prompt: bool = False,
        chat_template_id: str | None = None,
    ) -> int:
        total = 8  # BOS/system framing uncertainty
        for msg in messages:
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")
            total += 6  # role/special tokens estimate
            total += self.count_text(content)
            total += estimate_tokens(role)
        if tools is not None:
            total += estimate_tokens(json.dumps(tools, sort_keys=True, default=str)) + 16
        if add_generation_prompt:
            total += 4
        if chat_template_id:
            total += 8
        # Llama-family templates tend to add more special tokens.
        if (self.family or "").lower().startswith("llama"):
            total += 4 * max(1, len(messages))
        return total


def _try_tiktoken(tokenizer_id: str | None) -> TokenizerBackend | None:
    if not tokenizer_id:
        return None
    try:
        import tiktoken  # type: ignore
    except ImportError:
        return None
    try:
        if tokenizer_id.startswith("tiktoken:"):
            name = tokenizer_id.split(":", 1)[1]
            enc = tiktoken.get_encoding(name)
        elif "/" in tokenizer_id or tokenizer_id.startswith("gpt"):
            enc = tiktoken.encoding_for_model(tokenizer_id)
        else:
            enc = tiktoken.get_encoding(tokenizer_id)
    except Exception:  # noqa: BLE001
        return None

    class _TiktokenBackend:
        tokenizer_id = f"tiktoken:{getattr(enc, 'name', tokenizer_id)}"
        tokenizer_revision = "tiktoken"

        def count_text(self, text: str) -> int:
            return len(enc.encode(text or ""))

        def count_messages(
            self,
            messages: list[dict[str, Any]],
            *,
            tools: Any | None = None,
            add_generation_prompt: bool = False,
            chat_template_id: str | None = None,
        ) -> int:
            # OpenAI chat token accounting approximation (special tokens).
            total = 3  # every reply primed with <|start|>assistant
            for msg in messages:
                total += 4
                total += len(enc.encode(str(msg.get("role") or "")))
                total += len(enc.encode(str(msg.get("content") or "")))
            if tools is not None:
                total += len(enc.encode(json.dumps(tools, sort_keys=True, default=str)))
            if add_generation_prompt:
                total += 3
            return total

    return _TiktokenBackend()


def _try_hf_tokenizers(path_or_id: str | None) -> TokenizerBackend | None:
    if not path_or_id:
        return None
    try:
        from tokenizers import Tokenizer  # type: ignore
    except ImportError:
        return None
    try:
        import os

        if os.path.isfile(path_or_id):
            tok = Tokenizer.from_file(path_or_id)
        else:
            return None  # do not silently download
    except Exception:  # noqa: BLE001
        return None

    class _HFBackend:
        tokenizer_id = path_or_id
        tokenizer_revision = "hf-tokenizers-local"

        def count_text(self, text: str) -> int:
            return len(tok.encode(text or "").ids)

        def count_messages(
            self,
            messages: list[dict[str, Any]],
            *,
            tools: Any | None = None,
            add_generation_prompt: bool = False,
            chat_template_id: str | None = None,
        ) -> int:
            # Without a bound chat template, concatenate with role markers (not exact template).
            # Callers must not label this EXACT unless chat_template is also applied externally.
            parts = []
            for msg in messages:
                parts.append(f"<|{msg.get('role') or 'user'}|>\n{msg.get('content') or ''}")
            if tools is not None:
                parts.append(json.dumps(tools, sort_keys=True, default=str))
            if add_generation_prompt:
                parts.append("<|assistant|>\n")
            return len(tok.encode("\n".join(parts)).ids)

    return _HFBackend()


class TokenizationService:
    """ONE canonical model-aware tokenization abstraction."""

    def __init__(
        self,
        *,
        mode: str = "auto",  # auto | exact_preferred | heuristic_only
        safety_margin_ratio: float = 0.03,
        safety_margin_min: int = 8,
        max_cache_entries: int = 4096,
        max_cache_bytes: int = 16 * 1024 * 1024,
        runtime_tokenize: Callable[[TokenizationRequest], TokenCountResult | None] | None = None,
    ) -> None:
        self.mode = mode
        self.safety_margin_ratio = float(safety_margin_ratio)
        self.safety_margin_min = int(safety_margin_min)
        self._runtime_tokenize = runtime_tokenize
        self._registry: dict[str, TokenizerBackend] = {}
        self._model_tokenizer: dict[str, str] = {}
        self._lock = threading.RLock()
        self._cache: BoundedLRUCache[str, TokenCountResult] = BoundedLRUCache(
            max_entries=max_cache_entries,
            max_bytes=max_cache_bytes,
            name="tokenization",
            sizeof=lambda r: 128 + len(r.warnings) * 32,
        )
        self._flight: SingleFlight[TokenCountResult] = SingleFlight()
        self._heuristic = HeuristicTokenizer()
        # Always register the fixture tokenizer for tests / known fixtures.
        self.register_tokenizer(FixtureTokenizer())

    def set_enabled(self, enabled: bool) -> None:
        self._cache.set_enabled(enabled)

    def register_tokenizer(self, backend: TokenizerBackend) -> None:
        with self._lock:
            self._registry[backend.tokenizer_id] = backend

    def bind_model_tokenizer(self, model_id: str, tokenizer_id: str) -> None:
        with self._lock:
            self._model_tokenizer[model_id] = tokenizer_id

    def clear_cache(self) -> int:
        return self._cache.clear()

    def invalidate_tokenizer(self, tokenizer_id: str | None = None, revision: str | None = None) -> int:
        def pred(key: str, value: TokenCountResult) -> bool:
            if tokenizer_id and value.tokenizer_id != tokenizer_id:
                return False
            if revision and value.tokenizer_revision != revision:
                return False
            return tokenizer_id is not None or revision is not None

        return self._cache.invalidate_matching(pred)

    def cache_snapshot(self) -> dict[str, Any]:
        snap = self._cache.snapshot()
        snap["singleFlight"] = self._flight.stats()
        return snap

    def _resolve_backend(self, req: TokenizationRequest) -> tuple[TokenizerBackend | None, TokenPrecision, list[str]]:
        warnings: list[str] = []
        if self.mode == "heuristic_only":
            return self._heuristic, TokenPrecision.HEURISTIC, warnings

        # 1. Explicit / bound local tokenizer
        tok_id = req.tokenizer_id
        if not tok_id and req.model_id:
            with self._lock:
                tok_id = self._model_tokenizer.get(req.model_id)
        if tok_id:
            with self._lock:
                backend = self._registry.get(tok_id)
            if backend is not None:
                return backend, TokenPrecision.EXACT_LOCAL_TOKENIZER, warnings
            # Try optional libs without download
            for factory in (_try_tiktoken, _try_hf_tokenizers):
                backend = factory(tok_id)
                if backend is not None:
                    self.register_tokenizer(backend)
                    return backend, TokenPrecision.EXACT_LOCAL_TOKENIZER, warnings
            warnings.append(f"tokenizer_id_unresolved:{tok_id}")

        # Fixture shortcut when model_id requests it
        if req.model_id and req.model_id.startswith("fixture:"):
            with self._lock:
                backend = self._registry.get("fixture:whitespace_v1")
            if backend:
                return backend, TokenPrecision.EXACT_LOCAL_TOKENIZER, warnings

        # 2. Runtime-native tokenize (injected callback — never pretend)
        # Handled in count() via _runtime_tokenize before falling through.

        # 4. Template-aware estimate when family/template known
        if req.chat_template_id or req.runtime_kind:
            family = None
            if req.model_id and "/" in req.model_id:
                family = req.model_id.split("/")[-1].split("-")[0]
            return (
                TemplateAwareEstimator(family=family),
                TokenPrecision.TEMPLATE_AWARE_ESTIMATE,
                warnings,
            )

        return self._heuristic, TokenPrecision.HEURISTIC, warnings

    def _margin_for(self, count: int, precision: TokenPrecision) -> int:
        if precision in {
            TokenPrecision.EXACT_LOCAL_TOKENIZER,
            TokenPrecision.EXACT_RUNTIME_TOKENIZER,
            TokenPrecision.PROVIDER_REPORTED,
        }:
            return 0
        return max(self.safety_margin_min, int(count * self.safety_margin_ratio))

    def count(self, request: TokenizationRequest) -> TokenCountResult:
        key = request.cache_key()
        cached = self._cache.get(key)
        if cached is not None:
            return TokenCountResult(
                token_count=cached.token_count,
                source=TokenCountSource.CACHE,
                precision=cached.precision,
                tokenizer_id=cached.tokenizer_id,
                tokenizer_revision=cached.tokenizer_revision,
                chat_template_id=cached.chat_template_id,
                cached=True,
                warnings=cached.warnings,
                safety_margin_tokens=cached.safety_margin_tokens,
                truth=dict(cached.truth),
            )

        def _compute() -> TokenCountResult:
            # Re-check cache inside single-flight leader
            again = self._cache.get(key)
            if again is not None:
                return TokenCountResult(
                    token_count=again.token_count,
                    source=TokenCountSource.CACHE,
                    precision=again.precision,
                    tokenizer_id=again.tokenizer_id,
                    tokenizer_revision=again.tokenizer_revision,
                    chat_template_id=again.chat_template_id,
                    cached=True,
                    warnings=again.warnings,
                    safety_margin_tokens=again.safety_margin_tokens,
                    truth=dict(again.truth),
                )

            # Runtime tokenize attempt (exact when available)
            if self.mode != "heuristic_only" and self._runtime_tokenize is not None:
                try:
                    runtime_result = self._runtime_tokenize(request)
                except Exception as exc:  # noqa: BLE001
                    runtime_result = None
                    runtime_warning = f"runtime_tokenize_failed:{exc}"
                else:
                    runtime_warning = None
                if runtime_result is not None:
                    self._cache.put(key, runtime_result)
                    return runtime_result
            else:
                runtime_warning = None

            backend, precision, warnings = self._resolve_backend(request)
            if runtime_warning:
                warnings.append(runtime_warning)
            if backend is None:
                result = TokenCountResult(
                    token_count=0,
                    source=TokenCountSource.UNKNOWN,
                    precision=TokenPrecision.UNKNOWN,
                    warnings=tuple(warnings + ["tokenizer_unavailable"]),
                    safety_margin_tokens=self.safety_margin_min,
                    truth={"count_unavailable": True},
                )
                return result

            if request.messages:
                count = backend.count_messages(
                    list(request.messages),
                    tools=request.tools_schema,
                    add_generation_prompt=request.add_generation_prompt,
                    chat_template_id=request.chat_template_id,
                )
            else:
                count = backend.count_text(request.text)

            source = {
                TokenPrecision.EXACT_LOCAL_TOKENIZER: TokenCountSource.LOCAL_TOKENIZER,
                TokenPrecision.EXACT_RUNTIME_TOKENIZER: TokenCountSource.RUNTIME_TOKENIZER,
                TokenPrecision.TEMPLATE_AWARE_ESTIMATE: TokenCountSource.TEMPLATE_AWARE,
                TokenPrecision.HEURISTIC: TokenCountSource.HEURISTIC_CHARS4,
            }.get(precision, TokenCountSource.UNKNOWN)

            result = TokenCountResult(
                token_count=int(count),
                source=source,
                precision=precision,
                tokenizer_id=getattr(backend, "tokenizer_id", None),
                tokenizer_revision=getattr(backend, "tokenizer_revision", None)
                or request.tokenizer_revision,
                chat_template_id=request.chat_template_id,
                cached=False,
                warnings=tuple(warnings),
                safety_margin_tokens=self._margin_for(int(count), precision),
                truth={
                    "compiler_version": COMPILER_VERSION,
                    "model_id": request.model_id,
                },
            )
            self._cache.put(key, result)
            return result

        return self._flight.do(key, _compute)

    def count_text(
        self,
        text: str,
        *,
        model_id: str | None = None,
        tokenizer_id: str | None = None,
        tokenizer_revision: str | None = None,
        chat_template_id: str | None = None,
        **kwargs: Any,
    ) -> TokenCountResult:
        return self.count(
            TokenizationRequest(
                text=text,
                model_id=model_id,
                tokenizer_id=tokenizer_id,
                tokenizer_revision=tokenizer_revision,
                chat_template_id=chat_template_id,
                **kwargs,
            )
        )


# Process-wide default service (composition root may replace).
_default_service: TokenizationService | None = None
_default_lock = threading.Lock()


def get_tokenization_service() -> TokenizationService:
    global _default_service
    with _default_lock:
        if _default_service is None:
            _default_service = TokenizationService()
        return _default_service


def set_tokenization_service(service: TokenizationService | None) -> None:
    global _default_service
    with _default_lock:
        _default_service = service
