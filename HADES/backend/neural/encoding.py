"""Frozen-model text encoding for Phase 4 slow-memory training.

Deterministic toy tokenization (no Hugging Face downloads) + mean-pooled
last-layer hidden states from a frozen backbone.

V2: ``toy_tokenize`` / ``FrozenTextEncoder`` remain research/test fixtures.
Production Neural encoding uses ``neural.encoder.LmStudioEmbeddingEncoder``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping

from neural.deps import require_torch
from neural.errors import NeuralError
from neural.samples import NeuralSample, NeuralSampleType, strip_hidden_fields


class NeuralEncodingError(NeuralError):
    code = "neural_encoding_error"


_TOKEN_RE = re.compile(r"\S+")


def toy_tokenize(text: str, *, vocab_size: int, max_seq_len: int) -> list[int]:
    """Map text to a bounded token-id sequence via stable hashing (research-only)."""
    if vocab_size < 2:
        raise NeuralEncodingError("vocab_size must be >= 2")
    if max_seq_len < 1:
        raise NeuralEncodingError("max_seq_len must be >= 1")
    raw = str(text or "")
    parts = _TOKEN_RE.findall(raw) or [raw[:1] or " "]
    ids: list[int] = []
    for part in parts:
        digest = hashlib.sha256(part.encode("utf-8", "ignore")).digest()
        # Reserve id 0 as pad; map into 1..vocab_size-1
        token_id = 1 + (int.from_bytes(digest[:4], "big") % (vocab_size - 1))
        ids.append(token_id)
        if len(ids) >= max_seq_len:
            break
    if not ids:
        ids = [1]
    return ids[:max_seq_len]


@dataclass(frozen=True)
class SlowMemoryExample:
    """One key→value text pair for slow neural-memory training."""

    example_id: str
    key_text: str
    value_text: str
    split: str = "train"
    source_sample_id: str | None = None
    sample_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "key_text": self.key_text,
            "value_text": self.value_text,
            "split": self.split,
            "source_sample_id": self.source_sample_id,
            "sample_type": self.sample_type,
        }


def example_from_row(
    row_index: int,
    row: Mapping[str, Any],
    *,
    dataset_id: str,
    eval_ratio: float = 0.1,
) -> SlowMemoryExample | None:
    """Build a key/value training pair from a dataset row without inventing labels."""
    from neural.samples import deterministic_split, _stable_hash
    from training_service import format_training_example

    safe = strip_hidden_fields(row)
    instruction = str(safe.get("instruction") or "").strip()
    output = str(safe.get("output") or "").strip()
    if instruction and output:
        key_text, value_text = instruction, output
        sample_type = NeuralSampleType.INSTRUCTION_RESPONSE.value
    else:
        query = str(safe.get("query") or safe.get("question") or "").strip()
        answer = str(safe.get("answer") or safe.get("response") or "").strip()
        if query and answer:
            key_text, value_text = query, answer
            sample_type = NeuralSampleType.QUERY_ANSWER.value
        else:
            problem = str(safe.get("problem_statement") or "").strip()
            patch = str(safe.get("patch") or "").strip()
            if problem and patch:
                key_text, value_text = problem, patch
                sample_type = NeuralSampleType.CODE_PATCH.value
            else:
                prompt = str(safe.get("prompt") or "").strip()
                completion = str(safe.get("completion") or "").strip()
                if prompt and completion:
                    key_text, value_text = prompt, completion
                    sample_type = NeuralSampleType.CONTEXT_CONTINUATION.value
                else:
                    text = format_training_example(safe, {}).strip()
                    if len(text) < 8:
                        return None
                    mid = max(1, len(text) // 2)
                    key_text, value_text = text[:mid].strip(), text[mid:].strip()
                    if not key_text or not value_text:
                        return None
                    sample_type = NeuralSampleType.ADJACENT_WINDOW.value

    example_id = f"{dataset_id}:slow:{row_index}:{_stable_hash(key_text + '\n' + value_text)[:16]}"
    split = deterministic_split(example_id, eval_ratio=eval_ratio)
    return SlowMemoryExample(
        example_id=example_id,
        key_text=key_text,
        value_text=value_text,
        split=split,
        source_sample_id=f"{dataset_id}:{row_index}",
        sample_type=sample_type,
    )


def example_from_neural_sample(sample: NeuralSample) -> SlowMemoryExample | None:
    """Conservative fallback: adjacent windows over compiled sample text."""
    text = str(sample.text or "").strip()
    if len(text) < 8:
        return None
    mid = max(1, len(text) // 2)
    key_text, value_text = text[:mid].strip(), text[mid:].strip()
    if not key_text or not value_text:
        return None
    return SlowMemoryExample(
        example_id=f"slow:{sample.sample_id}",
        key_text=key_text,
        value_text=value_text,
        split=sample.split,
        source_sample_id=sample.sample_id,
        sample_type=sample.sample_type.value if sample.sample_type else None,
    )


class FrozenTextEncoder:
    """Encode text with a frozen backbone; never trains base weights."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.torch = require_torch()
        if not hasattr(runtime.base_model, "forward_hidden"):
            raise NeuralEncodingError("base model lacks forward_hidden()")
        from neural.toy_transformer import assert_module_frozen

        assert_module_frozen(runtime.base_model)

    @property
    def hidden_size(self) -> int:
        return int(self.runtime.toy_config.hidden_size)

    def tokenize(self, text: str) -> Any:
        cfg = self.runtime.toy_config
        ids = toy_tokenize(text, vocab_size=cfg.vocab_size, max_seq_len=cfg.max_seq_len)
        return self.torch.tensor([ids], dtype=self.torch.long, device=self.runtime.device)

    def encode_text(self, text: str) -> Any:
        """Return L2-normalized mean-pooled hidden vector ``[hidden]``."""
        torch = self.torch
        input_ids = self.tokenize(text)
        with torch.no_grad():
            hidden = self.runtime.base_model.forward_hidden(input_ids)
            pooled = hidden.mean(dim=1).squeeze(0)
            if not torch.isfinite(pooled).all():
                raise NeuralEncodingError("non-finite frozen encoding")
            return torch.nn.functional.normalize(pooled, dim=0)
