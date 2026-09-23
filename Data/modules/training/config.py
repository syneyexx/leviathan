"""Immutable training configuration snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from Data.modules.common.hashing import sha256_text
from Data.modules.common.secrets import redact_secrets


@dataclass
class TrainingConfig:
    name: str
    method: str
    base_model_ref: str
    dataset_version_id: str | None = None
    output_dir: str | None = None
    seed: int = 42
    epochs: float | None = 1.0
    max_steps: int | None = None
    train_batch_size: int = 1
    eval_batch_size: int = 1
    gradient_accumulation: int = 1
    learning_rate: float = 2e-4
    warmup_steps: int = 0
    weight_decay: float = 0.0
    max_seq_length: int = 512
    logging_steps: int = 1
    save_steps: int = 50
    eval_steps: int | None = None
    precision: str = "fp32"
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    lora_target_modules: list[str] = field(default_factory=lambda: ["q_proj", "v_proj"])
    gradient_checkpointing: bool = False
    load_in_4bit: bool = False
    dataloader_workers: int = 0
    dataset_path: str | None = None
    resume_from_checkpoint: str | None = None
    fixture_steps: int = 5
    fixture_sleep_ms: int = 50
    mixture_id: str | None = None
    mixture_content_hash: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not (self.name or "").strip():
            errors.append("name is required")
        method = (self.method or "").strip().lower()
        if method not in {"fixture", "sft", "lora", "qlora", "dpo"}:
            errors.append(f"unsupported method: {self.method!r}")
        if not (self.base_model_ref or "").strip() and method != "fixture":
            errors.append("base_model_ref is required")
        if self.train_batch_size < 1:
            errors.append("train_batch_size must be >= 1")
        if self.gradient_accumulation < 1:
            errors.append("gradient_accumulation must be >= 1")
        if self.learning_rate <= 0:
            errors.append("learning_rate must be > 0")
        if self.max_seq_length < 8:
            errors.append("max_seq_length must be >= 8")
        if self.epochs is None and self.max_steps is None:
            errors.append("epochs or max_steps is required")
        if method == "qlora" and not self.load_in_4bit:
            # QLoRA implies 4-bit; auto-correct is caller's choice — flag for planner.
            pass
        if method != "fixture" and not self.dataset_version_id and not self.dataset_path and not self.mixture_id:
            errors.append(
                "dataset_version_id, dataset_path, or mixture_id is required for non-fixture methods"
            )
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_dict(self) -> dict[str, Any]:
        """Redacted view suitable for API / manifests."""
        raw = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return json.loads(redact_secrets(raw))

    def config_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return sha256_text(payload)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrainingConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs: dict[str, Any] = {}
        extra = dict(data.get("extra") or {})
        for key, value in data.items():
            if key == "extra":
                continue
            if key in known:
                kwargs[key] = value
            else:
                extra[key] = value
        if extra:
            kwargs["extra"] = extra
        if "name" not in kwargs:
            kwargs["name"] = "training"
        if "method" not in kwargs:
            kwargs["method"] = "lora"
        if "base_model_ref" not in kwargs:
            kwargs["base_model_ref"] = "unspecified"
        return cls(**kwargs)
