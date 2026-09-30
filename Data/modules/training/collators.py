"""Tokenization + collation for causal-LM SFT with assistant-only loss masking.

``SftExample.labels_mask`` is character-level (1 = train, 0 = ignore). It is
mapped to token labels with the fast tokenizer's ``offset_mapping``; tokens whose
character span contains no trainable characters get ``-100``.
"""

from __future__ import annotations

from typing import Any, Sequence

from .sft_data import SftExample

IGNORE_INDEX = -100


def char_mask_to_token_labels(
    input_ids: Sequence[int],
    offsets: Sequence[Sequence[int]],
    char_mask: Sequence[int] | None,
    attention_mask: Sequence[int] | None = None,
) -> list[int]:
    labels: list[int] = []
    n_chars = len(char_mask) if char_mask is not None else 0
    for idx, token_id in enumerate(input_ids):
        if attention_mask is not None and not attention_mask[idx]:
            labels.append(IGNORE_INDEX)
            continue
        if char_mask is None:
            labels.append(int(token_id))
            continue
        start, end = int(offsets[idx][0]), int(offsets[idx][1])
        if end <= start:
            # Special tokens (BOS/EOS) have empty spans: train EOS only after trainable text.
            prev_trainable = bool(labels) and labels[-1] != IGNORE_INDEX
            labels.append(int(token_id) if prev_trainable and idx > 0 else IGNORE_INDEX)
            continue
        span = char_mask[max(0, start) : min(n_chars, end)]
        labels.append(int(token_id) if any(span) else IGNORE_INDEX)
    return labels


def _prefix_token_count(tokenizer: Any, text: str, max_length: int) -> int:
    enc = tokenizer(text, truncation=True, max_length=max_length, add_special_tokens=True)
    return len(enc["input_ids"])


def tokenize_sft_examples(
    tokenizer: Any,
    examples: Sequence[SftExample],
    *,
    max_length: int,
    assistant_loss_masking: bool,
) -> dict[str, list[list[int]]]:
    """Tokenize without padding; returns input_ids / attention_mask / labels lists."""
    out: dict[str, list[list[int]]] = {"input_ids": [], "attention_mask": [], "labels": []}
    fast = bool(getattr(tokenizer, "is_fast", False))
    for ex in examples:
        use_mask = bool(assistant_loss_masking and ex.labels_mask)
        if use_mask and fast:
            enc = tokenizer(
                ex.text,
                truncation=True,
                max_length=max_length,
                return_offsets_mapping=True,
            )
            ids = list(enc["input_ids"])
            attn = list(enc.get("attention_mask") or [1] * len(ids))
            labels = char_mask_to_token_labels(ids, enc["offset_mapping"], ex.labels_mask, attn)
        else:
            enc = tokenizer(ex.text, truncation=True, max_length=max_length)
            ids = list(enc["input_ids"])
            attn = list(enc.get("attention_mask") or [1] * len(ids))
            labels = [int(t) if a else IGNORE_INDEX for t, a in zip(ids, attn)]
            if use_mask:
                # Slow tokenizer fallback: mask the prompt prefix by re-tokenizing it.
                prompt_end = int((ex.role_spans.get("assistant") or (0, 0))[0])
                cut = _prefix_token_count(tokenizer, ex.text[:prompt_end], max_length) if prompt_end else 0
                labels = [IGNORE_INDEX] * min(cut, len(labels)) + labels[cut:]
        if not any(label != IGNORE_INDEX for label in labels):
            # Fully masked after truncation — contributes no loss; skip.
            continue
        out["input_ids"].append(ids)
        out["attention_mask"].append(attn)
        out["labels"].append(labels)
    return out


class MaskedCausalLMCollator:
    """Dynamic right-padding collator that preserves precomputed ``labels``.

    Counts non-padding tokens so tokens/sec is measured, not inferred.
    """

    def __init__(self, pad_token_id: int, *, pad_to_multiple_of: int | None = None) -> None:
        self.pad_token_id = int(pad_token_id)
        self.pad_to_multiple_of = pad_to_multiple_of
        self.tokens_seen = 0

    def pad(self, features: Sequence[dict[str, Any]]) -> dict[str, list[list[int]]]:
        longest = max(len(f["input_ids"]) for f in features)
        if self.pad_to_multiple_of:
            m = int(self.pad_to_multiple_of)
            longest = ((longest + m - 1) // m) * m
        batch: dict[str, list[list[int]]] = {"input_ids": [], "attention_mask": [], "labels": []}
        for f in features:
            ids = list(f["input_ids"])
            attn = list(f.get("attention_mask") or [1] * len(ids))
            labels = list(f.get("labels") or [t if a else IGNORE_INDEX for t, a in zip(ids, attn)])
            pad = longest - len(ids)
            batch["input_ids"].append(ids + [self.pad_token_id] * pad)
            batch["attention_mask"].append(attn + [0] * pad)
            batch["labels"].append(labels + [IGNORE_INDEX] * pad)
            self.tokens_seen += int(sum(attn))
        return batch

    def __call__(self, features: Sequence[dict[str, Any]]) -> dict[str, Any]:
        import torch  # type: ignore[import-not-found]

        padded = self.pad(features)
        return {key: torch.tensor(value, dtype=torch.long) for key, value in padded.items()}
