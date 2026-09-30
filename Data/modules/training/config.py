"""Immutable training configuration snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from Data.modules.common.hashing import sha256_text
from Data.modules.common.secrets import redact_secrets


TRAINING_METHODS = frozenset({"fixture", "sft", "lora", "qlora", "dpo"})
# Multi-GPU (DDP/FSDP/tensor parallel) is not implemented — do not expose it.
DEVICE_STRATEGIES = frozenset({"auto", "single"})
OPTIMIZERS = frozenset(
    {
        "adamw_torch",
        "adamw_torch_fused",
        "adamw_bnb_8bit",
        "paged_adamw_8bit",
        "paged_adamw_32bit",
        "adafactor",
        "sgd",
    }
)
BNB_OPTIMIZERS = frozenset({"adamw_bnb_8bit", "paged_adamw_8bit", "paged_adamw_32bit"})
LR_SCHEDULERS = frozenset(
    {"linear", "cosine", "cosine_with_restarts", "constant", "constant_with_warmup"}
)
BNB_4BIT_QUANT_TYPES = frozenset({"nf4", "fp4"})
BNB_COMPUTE_DTYPES = frozenset({"float16", "bfloat16", "float32"})


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
    # Round 4 SFT reproducibility / quality knobs
    base_model_revision: str | None = None
    tokenizer_revision: str | None = None
    chat_template: str | None = None
    assistant_loss_masking: bool = True
    packing: bool = False
    packing_max_chars: int = 2048
    val_split_ratio: float = 0.1
    test_split_ratio: float = 0.1
    # Production device / optimizer / eval knobs
    device_strategy: str = "auto"
    selected_stable_device_ids: list[str] = field(default_factory=list)
    # Filled at launch from selected_stable_device_ids; never trusted from the client.
    resolved_cuda_ordinals: list[int] = field(default_factory=list)
    optimizer: str = "adamw_torch"
    lr_scheduler_type: str = "linear"
    flash_attention: bool = False
    eval_during_training: bool = True
    save_total_limit: int | None = 3
    load_best_model_at_end: bool = False
    metric_for_best_model: str = "eval_loss"
    greater_is_better: bool = False
    early_stopping_patience: int | None = None
    bnb_4bit_quant_type: str = "nf4"
    bnb_4bit_use_double_quant: bool = True
    bnb_4bit_compute_dtype: str = "bfloat16"
    dpo_beta: float = 0.1
    # Planner suggestions are only applied when explicitly accepted.
    apply_planner_suggestions: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_method(self) -> str:
        return (self.method or "").strip().lower()

    @property
    def uses_4bit(self) -> bool:
        return self.normalized_method == "qlora" or bool(self.load_in_4bit)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not (self.name or "").strip():
            errors.append("name is required")
        method = self.normalized_method
        if method not in TRAINING_METHODS:
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
        errors.extend(self._validate_production_fields())
        return errors

    def _validate_production_fields(self) -> list[str]:
        errors: list[str] = []
        strategy = (self.device_strategy or "").strip().lower()
        if strategy not in DEVICE_STRATEGIES:
            errors.append(
                f"unsupported device_strategy: {self.device_strategy!r} "
                "(allowed: auto, single — multi-GPU is not implemented)"
            )
        if not isinstance(self.selected_stable_device_ids, list) or not all(
            isinstance(x, str) and x.strip() for x in self.selected_stable_device_ids
        ):
            errors.append("selected_stable_device_ids must be a list of non-empty strings")
        elif len(self.selected_stable_device_ids) > 1:
            errors.append("multi-GPU training is not implemented — select at most one device")
        if self.optimizer not in OPTIMIZERS:
            errors.append(f"unsupported optimizer: {self.optimizer!r}")
        if self.lr_scheduler_type not in LR_SCHEDULERS:
            errors.append(f"unsupported lr_scheduler_type: {self.lr_scheduler_type!r}")
        if self.save_total_limit is not None and int(self.save_total_limit) < 1:
            errors.append("save_total_limit must be >= 1 or null")
        if self.save_steps < 1:
            errors.append("save_steps must be >= 1")
        if self.eval_steps is not None and int(self.eval_steps) < 1:
            errors.append("eval_steps must be >= 1 or null")
        if self.load_best_model_at_end:
            if not self.eval_during_training:
                errors.append("load_best_model_at_end requires eval_during_training")
            eval_every = int(self.eval_steps or self.save_steps)
            if eval_every > 0 and int(self.save_steps) % eval_every != 0:
                errors.append("load_best_model_at_end requires save_steps to be a multiple of eval_steps")
            if not (self.metric_for_best_model or "").strip():
                errors.append("metric_for_best_model is required with load_best_model_at_end")
        if self.early_stopping_patience is not None:
            if int(self.early_stopping_patience) < 1:
                errors.append("early_stopping_patience must be >= 1 or null")
            if not self.load_best_model_at_end:
                errors.append("early_stopping_patience requires load_best_model_at_end")
        if self.bnb_4bit_quant_type not in BNB_4BIT_QUANT_TYPES:
            errors.append(f"unsupported bnb_4bit_quant_type: {self.bnb_4bit_quant_type!r}")
        if self.bnb_4bit_compute_dtype not in BNB_COMPUTE_DTYPES:
            errors.append(f"unsupported bnb_4bit_compute_dtype: {self.bnb_4bit_compute_dtype!r}")
        if not (float(self.dpo_beta) > 0):
            errors.append("dpo_beta must be > 0")
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

    def with_updates(self, **updates: Any) -> "TrainingConfig":
        data = self.to_dict()
        data.update(updates)
        return TrainingConfig.from_dict(data)

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
        for list_key in ("selected_stable_device_ids", "resolved_cuda_ordinals", "lora_target_modules"):
            if list_key in kwargs and kwargs[list_key] is None:
                kwargs.pop(list_key)
        if "selected_stable_device_ids" in kwargs and isinstance(kwargs["selected_stable_device_ids"], str):
            kwargs["selected_stable_device_ids"] = [kwargs["selected_stable_device_ids"]]
        if "resolved_cuda_ordinals" in kwargs:
            kwargs["resolved_cuda_ordinals"] = [int(x) for x in kwargs["resolved_cuda_ordinals"]]
        if "name" not in kwargs:
            kwargs["name"] = "training"
        if "method" not in kwargs:
            kwargs["method"] = "lora"
        if "base_model_ref" not in kwargs:
            kwargs["base_model_ref"] = "unspecified"
        return cls(**kwargs)
