"""SFT data preparation helpers — revisions, splits, masking, packing.

Pure-Python so Core stays importable without torch. The LoRA loop consumes
these structures when optional ML deps are present.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SftExample:
    text: str
    labels_mask: list[int] | None = None  # 1 = train loss, 0 = ignored (prompt)
    role_spans: dict[str, tuple[int, int]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "labels_mask_sum": sum(self.labels_mask) if self.labels_mask else None,
            "labels_mask_len": len(self.labels_mask) if self.labels_mask else 0,
            "role_spans": dict(self.role_spans),
            "metadata": dict(self.metadata),
            "truth": {"assistant_masking_is_not_full_sequence_lm": bool(self.labels_mask)},
        }


@dataclass(frozen=True)
class SftSplit:
    train: list[SftExample]
    validation: list[SftExample]
    test: list[SftExample]
    seed: int
    provenance: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "train_count": len(self.train),
            "validation_count": len(self.validation),
            "test_count": len(self.test),
            "seed": self.seed,
            "provenance": dict(self.provenance),
            "truth": {
                "training_loss_is_not_evaluation": True,
                "held_out_splits_required_for_eval_claims": True,
            },
        }


def apply_chat_template(
    messages: list[dict[str, str]],
    *,
    template: str | None = None,
) -> str:
    """Render chat messages. Default is a simple role-tagged template (not a model claim)."""
    if template:
        # Minimal mustache-style: {role} / {content} per message joined.
        parts = []
        for msg in messages:
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or "")
            parts.append(
                template.replace("{role}", role).replace("{content}", content)
            )
        return "\n".join(parts)
    lines: list[str] = []
    for msg in messages:
        role = str(msg.get("role") or "user").strip() or "user"
        content = str(msg.get("content") or "").strip()
        lines.append(f"<|{role}|>\n{content}")
    lines.append("<|assistant|>")
    return "\n".join(lines)


def build_assistant_masked_example(
    messages: list[dict[str, str]],
    *,
    template: str | None = None,
) -> SftExample:
    """Build text where only assistant token spans receive loss (char-level mask proxy).

    Char-level masks are converted to token masks by the trainer after tokenization;
    this records the assistant span in characters for provenance + tests.
    """
    prompt_msgs = [m for m in messages if str(m.get("role") or "") != "assistant"]
    assistant_msgs = [m for m in messages if str(m.get("role") or "") == "assistant"]
    prompt = apply_chat_template(prompt_msgs, template=template)
    # Ensure prompt ends ready for assistant continuation.
    if not prompt.endswith("<|assistant|>"):
        prompt = prompt.rstrip() + "\n<|assistant|>"
    assistant_body = "\n".join(str(m.get("content") or "") for m in assistant_msgs).strip()
    full = prompt + "\n" + assistant_body if assistant_body else prompt
    mask = [0] * len(prompt)
    if assistant_body:
        # +1 for the newline between prompt and assistant body
        mask.append(0)  # newline
        mask.extend([1] * len(assistant_body))
    else:
        mask = [0] * len(full)
    # Length align (safety)
    if len(mask) != len(full):
        mask = [0] * (len(full) - len(assistant_body)) + [1] * len(assistant_body)
    return SftExample(
        text=full,
        labels_mask=mask,
        role_spans={
            "prompt": (0, len(prompt)),
            "assistant": (len(full) - len(assistant_body), len(full)) if assistant_body else (len(full), len(full)),
        },
        metadata={"assistant_loss_masking": True, "chat_template": template or "default_role_tags"},
    )


def examples_from_raw_texts(
    texts: list[str],
    *,
    messages_list: list[list[dict[str, str]]] | None = None,
    chat_template: str | None = None,
    assistant_loss_masking: bool = False,
) -> list[SftExample]:
    out: list[SftExample] = []
    if messages_list:
        for messages in messages_list:
            if assistant_loss_masking:
                out.append(build_assistant_masked_example(messages, template=chat_template))
            else:
                out.append(
                    SftExample(
                        text=apply_chat_template(messages, template=chat_template),
                        labels_mask=None,
                        metadata={"assistant_loss_masking": False},
                    )
                )
        return out
    for text in texts:
        out.append(SftExample(text=text, labels_mask=None, metadata={"assistant_loss_masking": False}))
    return out


def pack_examples(
    examples: list[SftExample],
    *,
    max_chars: int = 2048,
) -> list[SftExample]:
    """Greedy pack consecutive examples into packed sequences (char budget)."""
    if max_chars < 32 or not examples:
        return list(examples)
    packed: list[SftExample] = []
    buf_text: list[str] = []
    buf_mask: list[int] = []
    for ex in examples:
        candidate = ("\n".join(buf_text + [ex.text])) if buf_text else ex.text
        if buf_text and len(candidate) > max_chars:
            packed.append(
                SftExample(
                    text="\n".join(buf_text),
                    labels_mask=buf_mask or None,
                    metadata={"packed": True, "n": len(buf_text)},
                )
            )
            buf_text = [ex.text]
            buf_mask = list(ex.labels_mask) if ex.labels_mask else [1] * len(ex.text)
        else:
            if buf_text:
                buf_mask.append(0)  # separator newline — no loss on pack join
            buf_text.append(ex.text)
            if ex.labels_mask:
                buf_mask.extend(ex.labels_mask)
            else:
                buf_mask.extend([1] * len(ex.text))
    if buf_text:
        packed.append(
            SftExample(
                text="\n".join(buf_text),
                labels_mask=buf_mask or None,
                metadata={"packed": True, "n": len(buf_text)},
            )
        )
    return packed


def split_examples(
    examples: list[SftExample],
    *,
    seed: int = 42,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
) -> SftSplit:
    """Deterministic train/validation/test split. Held-out sets must not train."""
    n = len(examples)
    val_ratio = max(0.0, min(0.45, float(val_ratio)))
    test_ratio = max(0.0, min(0.45, float(test_ratio)))
    if val_ratio + test_ratio >= 1.0:
        test_ratio = max(0.0, 0.9 - val_ratio)
    indices = list(range(n))
    rng = random.Random(int(seed))
    rng.shuffle(indices)
    n_test = int(n * test_ratio) if n >= 5 else 0
    n_val = int(n * val_ratio) if n >= 5 else (1 if n >= 3 and val_ratio > 0 else 0)
    test_idx = indices[:n_test]
    val_idx = indices[n_test : n_test + n_val]
    train_idx = indices[n_test + n_val :]
    if not train_idx and examples:
        # Never leave empty train — steal from val/test if tiny corpora.
        train_idx = indices[:]
        val_idx, test_idx = [], []
    provenance = {
        "seed": int(seed),
        "val_ratio": val_ratio,
        "test_ratio": test_ratio,
        "fingerprint": hashlib.sha256(
            json.dumps([examples[i].text for i in train_idx[:20]], ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16],
    }
    return SftSplit(
        train=[examples[i] for i in train_idx],
        validation=[examples[i] for i in val_idx],
        test=[examples[i] for i in test_idx],
        seed=int(seed),
        provenance=provenance,
    )


def revision_provenance(
    *,
    base_model_ref: str,
    base_model_revision: str | None,
    tokenizer_revision: str | None,
    chat_template: str | None,
    seed: int,
    assistant_loss_masking: bool,
    packing: bool,
) -> dict[str, Any]:
    return {
        "base_model_ref": base_model_ref,
        "base_model_revision": base_model_revision or "unpinned",
        "tokenizer_revision": tokenizer_revision or base_model_revision or "unpinned",
        "chat_template": chat_template or "default_role_tags",
        "seed": seed,
        "assistant_loss_masking": assistant_loss_masking,
        "packing": packing,
        "truth": {
            "unpinned_revision_is_not_reproducible": not bool(base_model_revision),
            "training_loss_is_not_evaluation": True,
        },
    }
