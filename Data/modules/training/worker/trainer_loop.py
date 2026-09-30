"""Production trainer loop — method dispatch for fixture / SFT / LoRA / QLoRA / DPO.

Optional torch/transformers/peft/trl are imported lazily so the API process never
crashes when they are absent. Metrics are measured (loss, lr, tokens/sec) or
derived (perplexity from loss) — never fabricated accuracy.
"""

from __future__ import annotations

import json
import math
import os
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_file, sha256_text
from Data.modules.common.secrets import redact_secrets

from ..capabilities import safe_import
from ..collators import MaskedCausalLMCollator, tokenize_sft_examples
from ..config import TrainingConfig
from ..events import TrainingEventLog
from ..store import TrainingStore, utc_now
from ..types import DurableTrainingStatus


CancelCheck = Callable[[], bool]

_DTYPE_MAP = {
    "float16": "float16",
    "fp16": "float16",
    "bfloat16": "bfloat16",
    "bf16": "bfloat16",
    "float32": "float32",
    "fp32": "float32",
}


def _fixture_forced(config: TrainingConfig) -> bool:
    if (config.method or "").lower() == "fixture":
        return True
    return os.getenv("LEVIATHAN_TRAINING_FIXTURE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run_training_loop(
    *,
    job_id: str,
    store: TrainingStore,
    config: TrainingConfig,
    output_dir: Path,
    events: TrainingEventLog,
    cancel_check: CancelCheck,
) -> dict[str, Any]:
    ensure_dir(output_dir)
    if _fixture_forced(config):
        return run_fixture_loop(
            job_id=job_id,
            store=store,
            config=config,
            output_dir=output_dir,
            events=events,
            cancel_check=cancel_check,
        )
    method = config.normalized_method
    if method == "sft":
        return run_causal_lm_loop(
            job_id=job_id,
            store=store,
            config=config,
            output_dir=output_dir,
            events=events,
            cancel_check=cancel_check,
            mode="sft",
        )
    if method == "lora":
        return run_causal_lm_loop(
            job_id=job_id,
            store=store,
            config=config,
            output_dir=output_dir,
            events=events,
            cancel_check=cancel_check,
            mode="lora",
        )
    if method == "qlora":
        return run_causal_lm_loop(
            job_id=job_id,
            store=store,
            config=config,
            output_dir=output_dir,
            events=events,
            cancel_check=cancel_check,
            mode="qlora",
        )
    if method == "dpo":
        return run_dpo_loop(
            job_id=job_id,
            store=store,
            config=config,
            output_dir=output_dir,
            events=events,
            cancel_check=cancel_check,
        )
    raise RuntimeError(f"Unsupported training method: {config.method!r}")


def run_fixture_loop(
    *,
    job_id: str,
    store: TrainingStore,
    config: TrainingConfig,
    output_dir: Path,
    events: TrainingEventLog,
    cancel_check: CancelCheck,
) -> dict[str, Any]:
    steps = max(1, int(config.fixture_steps))
    sleep_s = max(0.0, int(config.fixture_sleep_ms) / 1000.0)
    events.emit("phase_changed", phase="running", message="fixture training started")
    store.update_job(job_id, status=DurableTrainingStatus.RUNNING, phase="running")

    last_loss = 1.0
    for step in range(1, steps + 1):
        if cancel_check():
            events.emit("cancelled", step=step)
            ckpt = _write_fixture_checkpoint(output_dir, step=step, loss=last_loss)
            _register_checkpoint(store, job_id, ckpt, step=step, loss=last_loss)
            store.update_job(
                job_id,
                status=DurableTrainingStatus.CANCELLED,
                phase="cancelled",
                progress=step / steps,
                finished_at=utc_now(),
                error="Cancelled by request",
                checkpoint={"path": str(ckpt), "step": step},
            )
            return {"status": "cancelled", "steps": step, "mode": "fixture"}

        # Deterministic decaying "loss" — labeled fixture, not a real model metric.
        last_loss = round(1.0 / step, 6)
        store.append_metric(
            job_id,
            metric_name="train_loss",
            metric_value=last_loss,
            step=step,
            epoch=step / steps,
            metadata={"fixture": True, "note": "deterministic fixture metric"},
        )
        events.emit("metric", metric="train_loss", value=last_loss, step=step)
        store.update_job(job_id, progress=step / steps, metrics_summary={"train_loss": last_loss, "step": step})

        if step == steps // 2 or step == steps:
            ckpt = _write_fixture_checkpoint(output_dir, step=step, loss=last_loss)
            _register_checkpoint(store, job_id, ckpt, step=step, loss=last_loss)
            events.emit("checkpoint_saved", path=str(ckpt), step=step)

        if sleep_s:
            time.sleep(sleep_s)

    store.update_job(job_id, status=DurableTrainingStatus.EVALUATING, phase="evaluating")
    events.emit("evaluation_started")
    eval_loss = round(last_loss * 0.9, 6)
    store.append_metric(
        job_id,
        metric_name="eval_loss",
        metric_value=eval_loss,
        step=steps,
        metadata={"fixture": True},
    )
    evaluation = {
        "eval_loss": eval_loss,
        "fixture": True,
        "note": "Fixture evaluation — not a claim of model improvement",
    }
    events.emit("evaluation_finished", evaluation=evaluation)

    store.update_job(job_id, status=DurableTrainingStatus.EXPORTING, phase="exporting")
    adapter_dir = output_dir / "adapter"
    ensure_dir(adapter_dir)
    adapter_file = adapter_dir / "adapter_config.json"
    payload = {
        "method": "fixture",
        "base_model_ref": config.base_model_ref,
        "steps": steps,
        "seed": config.seed,
        "config_hash": config.config_hash(),
    }
    atomic_write_text(adapter_file, redact_secrets(json.dumps(payload, indent=2)))
    content_hash = sha256_file(adapter_file)

    card_path = output_dir / "MODEL_CARD.md"
    card = _model_card_markdown(config, evaluation=evaluation, mode="fixture")
    atomic_write_text(card_path, card)

    artifact = store.add_artifact(
        job_id=job_id,
        artifact_type="fixture_adapter",
        path=str(adapter_dir),
        base_model_ref=config.base_model_ref,
        dataset_version_id=config.dataset_version_id,
        method="fixture",
        config_hash=config.config_hash(),
        content_hash=content_hash,
        model_card_path=str(card_path),
        evaluation=evaluation,
        compatibility={"runtime": "fixture_only", "inference_ready": False},
        metadata={"fixture": True},
    )
    store.update_job(
        job_id,
        status=DurableTrainingStatus.COMPLETED,
        phase="completed",
        progress=1.0,
        finished_at=utc_now(),
        artifact_id=artifact.artifact_id,
        evaluation=evaluation,
        metrics_summary={"train_loss": last_loss, "eval_loss": eval_loss, "steps": steps},
    )
    events.emit("completed", artifact_id=artifact.artifact_id)
    return {
        "status": "completed",
        "steps": steps,
        "mode": "fixture",
        "artifact_id": artifact.artifact_id,
        "evaluation": evaluation,
    }


# ---------------------------------------------------------------------------
# Causal LM: SFT (full FT) / LoRA / QLoRA
# ---------------------------------------------------------------------------


def run_causal_lm_loop(
    *,
    job_id: str,
    store: TrainingStore,
    config: TrainingConfig,
    output_dir: Path,
    events: TrainingEventLog,
    cancel_check: CancelCheck,
    mode: str,
) -> dict[str, Any]:
    torch = safe_import("torch")
    transformers = safe_import("transformers")
    datasets_mod = safe_import("datasets")
    if torch is None or transformers is None or datasets_mod is None:
        missing = [
            name
            for name, mod in (
                ("torch", torch),
                ("transformers", transformers),
                ("datasets", datasets_mod),
            )
            if mod is None
        ]
        raise RuntimeError(f"Missing required packages for {mode} training: {', '.join(missing)}")

    use_peft = mode in {"lora", "qlora"}
    use_qlora = mode == "qlora" or bool(config.load_in_4bit and mode != "sft")
    if use_peft:
        peft = safe_import("peft")
        if peft is None:
            raise RuntimeError(f"Missing required package for {mode} training: peft")
    if use_qlora:
        bnb = safe_import("bitsandbytes")
        if bnb is None:
            raise RuntimeError("QLoRA/4-bit requires bitsandbytes")

    events.emit("phase_changed", phase="running", message=f"{mode} training started")
    store.update_job(job_id, status=DurableTrainingStatus.RUNNING, phase="running")

    dataset_path = config.dataset_path
    if not dataset_path or not Path(dataset_path).exists():
        raise RuntimeError(f"dataset_path required and must exist for {mode} training")

    from transformers import (  # type: ignore[import-not-found]
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    model_id = _local_model_id(config)
    tokenizer = _load_tokenizer(config, model_id)
    model = _load_causal_model(config, model_id, mode=mode, use_qlora=use_qlora)

    if config.gradient_checkpointing:
        if hasattr(model, "config") and hasattr(model.config, "use_cache"):
            model.config.use_cache = False
        if hasattr(model, "gradient_checkpointing_enable"):
            model.gradient_checkpointing_enable()

    if use_peft:
        from peft import LoraConfig, get_peft_model  # type: ignore[import-not-found]

        if use_qlora:
            from peft import prepare_model_for_kbit_training  # type: ignore[import-not-found]

            model = prepare_model_for_kbit_training(model)
        lora = LoraConfig(
            r=int(config.lora_r),
            lora_alpha=int(config.lora_alpha),
            lora_dropout=float(config.lora_dropout),
            target_modules=list(config.lora_target_modules),
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora)

    from ..sft_data import (
        examples_from_raw_texts,
        pack_examples,
        revision_provenance,
        split_examples,
    )

    raw = _load_dataset_payload(Path(dataset_path))
    examples = examples_from_raw_texts(
        raw["texts"],
        messages_list=raw.get("messages_list") or None,
        chat_template=config.chat_template,
        assistant_loss_masking=bool(config.assistant_loss_masking and raw.get("messages_list")),
    )
    if config.packing:
        examples = pack_examples(examples, max_chars=int(config.packing_max_chars))
    split = split_examples(
        examples,
        seed=int(config.seed),
        val_ratio=float(config.val_split_ratio),
        test_ratio=float(config.test_split_ratio),
    )
    if len(split.train) < 1:
        raise RuntimeError("Dataset contains no usable training examples after split")

    sft_prov = revision_provenance(
        base_model_ref=config.base_model_ref,
        base_model_revision=config.base_model_revision,
        tokenizer_revision=config.tokenizer_revision,
        chat_template=config.chat_template,
        seed=int(config.seed),
        assistant_loss_masking=bool(config.assistant_loss_masking),
        packing=bool(config.packing),
    )
    sft_prov["split"] = split.public_dict()
    sft_prov["mode"] = mode
    events.emit("sft_provenance", provenance=sft_prov)

    use_masking = bool(config.assistant_loss_masking)
    train_tok = tokenize_sft_examples(
        tokenizer,
        split.train,
        max_length=int(config.max_seq_length),
        assistant_loss_masking=use_masking,
    )
    if not train_tok["input_ids"]:
        raise RuntimeError("All training examples were fully masked after tokenization")
    ds = datasets_mod.Dataset.from_dict(train_tok)
    eval_ds = None
    if split.validation and config.eval_during_training:
        eval_tok = tokenize_sft_examples(
            tokenizer,
            split.validation,
            max_length=int(config.max_seq_length),
            assistant_loss_masking=use_masking,
        )
        if eval_tok["input_ids"]:
            eval_ds = datasets_mod.Dataset.from_dict(eval_tok)

    collator = MaskedCausalLMCollator(pad_token_id=int(tokenizer.pad_token_id))
    args = _build_training_arguments(config, output_dir, has_eval=eval_ds is not None)
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ds,
        eval_dataset=eval_ds,
        data_collator=collator,
    )
    _attach_callbacks(trainer, store=store, job_id=job_id, events=events, config=config, cancel_check=cancel_check, collator=collator)

    train_started = time.perf_counter()
    tokens_before = collator.tokens_seen
    train_result = trainer.train(resume_from_checkpoint=config.resume_from_checkpoint)
    wall = max(1e-6, time.perf_counter() - train_started)
    tokens_delta = max(0, collator.tokens_seen - tokens_before)
    tokens_per_sec = tokens_delta / wall

    if cancel_check():
        return _cancel_save(
            trainer=trainer,
            store=store,
            job_id=job_id,
            output_dir=output_dir,
            events=events,
            mode=mode,
        )

    adapter_dir = output_dir / "adapter"
    ensure_dir(adapter_dir)
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))

    metrics = dict(getattr(train_result, "metrics", {}) or {})
    _record_throughput_metrics(
        store=store,
        job_id=job_id,
        events=events,
        metrics=metrics,
        tokens_per_sec=tokens_per_sec,
        tokens_seen=tokens_delta,
        wall_seconds=wall,
    )

    evaluation = _run_held_out_eval(
        trainer=trainer,
        store=store,
        job_id=job_id,
        events=events,
        eval_ds=eval_ds,
        train_metrics=metrics,
        provenance=sft_prov,
    )

    return _finalize_adapter_job(
        store=store,
        job_id=job_id,
        config=config,
        output_dir=output_dir,
        adapter_dir=adapter_dir,
        events=events,
        evaluation=evaluation,
        metrics=metrics,
        mode=mode,
        peft=use_peft,
    )


# ---------------------------------------------------------------------------
# Durable TRL DPO
# ---------------------------------------------------------------------------


def run_dpo_loop(
    *,
    job_id: str,
    store: TrainingStore,
    config: TrainingConfig,
    output_dir: Path,
    events: TrainingEventLog,
    cancel_check: CancelCheck,
) -> dict[str, Any]:
    torch = safe_import("torch")
    transformers = safe_import("transformers")
    datasets_mod = safe_import("datasets")
    peft = safe_import("peft")
    trl = safe_import("trl")
    missing = [
        name
        for name, mod in (
            ("torch", torch),
            ("transformers", transformers),
            ("datasets", datasets_mod),
            ("peft", peft),
            ("trl", trl),
        )
        if mod is None
    ]
    if missing:
        raise RuntimeError(
            f"Durable DPO (method=dpo) requires TRL DPOTrainer deps missing: {', '.join(missing)}. "
            "Pure-Python preference micro objective is can_run_dpo_micro / recipe pref_dpo_v1."
        )

    events.emit("phase_changed", phase="running", message="TRL DPO training started")
    store.update_job(job_id, status=DurableTrainingStatus.RUNNING, phase="running")

    dataset_path = config.dataset_path
    if not dataset_path or not Path(dataset_path).exists():
        raise RuntimeError("dataset_path required and must exist for DPO training")

    from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore[import-not-found]
    from peft import LoraConfig  # type: ignore[import-not-found]
    from trl import DPOConfig, DPOTrainer  # type: ignore[import-not-found]

    model_id = _local_model_id(config)
    tokenizer = _load_tokenizer(config, model_id)
    model = _load_causal_model(config, model_id, mode="dpo", use_qlora=False)
    if config.gradient_checkpointing and hasattr(model, "config") and hasattr(model.config, "use_cache"):
        model.config.use_cache = False

    pairs = _load_preference_pairs(Path(dataset_path))
    if len(pairs) < 2:
        raise RuntimeError("DPO requires at least 2 preference pairs with chosen/rejected")

    # Deterministic held-out split for honest eval (not train loss).
    rng_seed = int(config.seed)
    import random

    shuffled = list(pairs)
    random.Random(rng_seed).shuffle(shuffled)
    n_val = max(1, int(len(shuffled) * float(config.val_split_ratio))) if config.eval_during_training else 0
    n_val = min(n_val, len(shuffled) - 1) if len(shuffled) > 1 else 0
    val_rows = shuffled[:n_val]
    train_rows = shuffled[n_val:] or shuffled
    train_ds = datasets_mod.Dataset.from_list(train_rows)
    eval_ds = datasets_mod.Dataset.from_list(val_rows) if val_rows else None

    peft_config = LoraConfig(
        r=int(config.lora_r),
        lora_alpha=int(config.lora_alpha),
        lora_dropout=float(config.lora_dropout),
        target_modules=list(config.lora_target_modules),
        bias="none",
        task_type="CAUSAL_LM",
    )

    dpo_kwargs: dict[str, Any] = {
        "output_dir": str(output_dir / "hf_runs"),
        "per_device_train_batch_size": int(config.train_batch_size),
        "per_device_eval_batch_size": int(config.eval_batch_size),
        "gradient_accumulation_steps": int(config.gradient_accumulation),
        "learning_rate": float(config.learning_rate),
        "num_train_epochs": float(config.epochs or 1.0),
        "max_steps": int(config.max_steps) if config.max_steps else -1,
        "logging_steps": int(config.logging_steps),
        "save_steps": int(config.save_steps),
        "warmup_steps": int(config.warmup_steps),
        "weight_decay": float(config.weight_decay),
        "fp16": (config.precision or "").lower() == "fp16",
        "bf16": (config.precision or "").lower() == "bf16",
        "gradient_checkpointing": bool(config.gradient_checkpointing),
        "report_to": [],
        "seed": int(config.seed),
        "remove_unused_columns": False,
        "optim": str(config.optimizer),
        "lr_scheduler_type": str(config.lr_scheduler_type),
        "save_total_limit": int(config.save_total_limit) if config.save_total_limit else None,
        "beta": float(config.dpo_beta),
        "max_length": int(config.max_seq_length),
        "max_prompt_length": max(8, int(config.max_seq_length) // 2),
    }
    if eval_ds is not None and config.eval_during_training:
        eval_steps = int(config.eval_steps or config.save_steps)
        dpo_kwargs["eval_strategy"] = "steps"
        dpo_kwargs["eval_steps"] = eval_steps
        if config.load_best_model_at_end:
            dpo_kwargs["load_best_model_at_end"] = True
            dpo_kwargs["metric_for_best_model"] = str(config.metric_for_best_model)
            dpo_kwargs["greater_is_better"] = bool(config.greater_is_better)
    else:
        dpo_kwargs["eval_strategy"] = "no"

    # DPOConfig may reject unknown keys across TRL versions — filter defensively.
    try:
        dpo_args = DPOConfig(**dpo_kwargs)
    except TypeError:
        # Older TRL: fall back to TrainingArguments-compatible subset + beta separately.
        from transformers import TrainingArguments  # type: ignore[import-not-found]

        beta = dpo_kwargs.pop("beta", float(config.dpo_beta))
        dpo_kwargs.pop("max_prompt_length", None)
        # Keep max_length if supported by TrainingArguments (usually not) — drop safely.
        dpo_kwargs.pop("max_length", None)
        for key in ("eval_strategy", "evaluation_strategy"):
            if key in dpo_kwargs:
                pass
        try:
            dpo_args = DPOConfig(**{**dpo_kwargs, "beta": beta})
        except TypeError:
            base = TrainingArguments(**{k: v for k, v in dpo_kwargs.items() if k not in {"beta"}})
            dpo_args = base
            # Attach beta for trainer ctor below.
            setattr(dpo_args, "beta", beta)

    trainer_kwargs: dict[str, Any] = {
        "model": model,
        "args": dpo_args,
        "train_dataset": train_ds,
        "eval_dataset": eval_ds,
        "processing_class": tokenizer,
        "peft_config": peft_config,
    }
    # TRL API drift: tokenizer vs processing_class; beta on args vs ctor.
    try:
        trainer = DPOTrainer(**trainer_kwargs)
    except TypeError:
        trainer_kwargs.pop("processing_class", None)
        trainer_kwargs["tokenizer"] = tokenizer
        try:
            trainer = DPOTrainer(**trainer_kwargs)
        except TypeError:
            trainer_kwargs["beta"] = float(config.dpo_beta)
            trainer = DPOTrainer(**trainer_kwargs)

    _attach_callbacks(
        trainer,
        store=store,
        job_id=job_id,
        events=events,
        config=config,
        cancel_check=cancel_check,
        collator=None,
    )

    train_started = time.perf_counter()
    train_result = trainer.train(resume_from_checkpoint=config.resume_from_checkpoint)
    wall = max(1e-6, time.perf_counter() - train_started)

    if cancel_check():
        return _cancel_save(
            trainer=trainer,
            store=store,
            job_id=job_id,
            output_dir=output_dir,
            events=events,
            mode="dpo",
        )

    adapter_dir = output_dir / "adapter"
    ensure_dir(adapter_dir)
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))

    metrics = dict(getattr(train_result, "metrics", {}) or {})
    metrics["wall_seconds"] = round(wall, 4)
    if "train_loss" in metrics or "loss" in metrics:
        loss_v = float(metrics.get("train_loss", metrics.get("loss")))
        _append_derived_perplexity(store, job_id, events, loss_v, step=int(metrics.get("global_step") or 0))

    evaluation: dict[str, Any] = {
        "train_metrics": metrics,
        "dpo_beta": float(config.dpo_beta),
        "pair_counts": {"train": len(train_rows), "validation": len(val_rows)},
        "note": "TRL DPOTrainer durable job — not the pure-Python dpo_micro recipe",
    }
    store.update_job(job_id, status=DurableTrainingStatus.EVALUATING, phase="evaluating")
    events.emit("evaluation_started")
    if eval_ds is not None:
        try:
            eval_metrics = dict(trainer.evaluate() or {})
            evaluation["eval_metrics"] = eval_metrics
            eval_loss = eval_metrics.get("eval_loss")
            if eval_loss is not None:
                store.append_metric(
                    job_id,
                    metric_name="eval_loss",
                    metric_value=float(eval_loss),
                    step=int(metrics.get("global_step") or 0),
                    metadata={"held_out": True, "dpo": True},
                )
                _append_derived_perplexity(
                    store, job_id, events, float(eval_loss), step=int(metrics.get("global_step") or 0), name="eval_perplexity"
                )
        except Exception as exc:  # noqa: BLE001
            evaluation["eval_error"] = str(exc)[:400]
    events.emit("evaluation_finished", evaluation=evaluation)

    return _finalize_adapter_job(
        store=store,
        job_id=job_id,
        config=config,
        output_dir=output_dir,
        adapter_dir=adapter_dir,
        events=events,
        evaluation=evaluation,
        metrics=metrics,
        mode="dpo",
        peft=True,
    )


# Back-compat alias used by older imports/tests.
def run_lora_loop(**kwargs: Any) -> dict[str, Any]:
    return run_causal_lm_loop(mode="lora", **kwargs)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _local_model_id(config: TrainingConfig) -> str:
    from ..model_source import resolve_model_source

    source = resolve_model_source(config.base_model_ref, revision=config.base_model_revision)
    if source.path:
        return source.path
    return config.base_model_ref


def _load_tokenizer(config: TrainingConfig, model_id: str) -> Any:
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    tok_kwargs: dict[str, Any] = {"local_files_only": True}
    if config.tokenizer_revision:
        tok_kwargs["revision"] = config.tokenizer_revision
    elif config.base_model_revision:
        tok_kwargs["revision"] = config.base_model_revision
    tokenizer = AutoTokenizer.from_pretrained(model_id, **tok_kwargs)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def _torch_dtype(precision: str) -> Any | None:
    torch = safe_import("torch")
    if torch is None:
        return None
    key = (precision or "fp32").lower()
    if key in {"bf16", "bfloat16"}:
        return torch.bfloat16
    if key in {"fp16", "float16"}:
        return torch.float16
    return None


def _bnb_compute_dtype(name: str) -> Any:
    torch = safe_import("torch")
    key = _DTYPE_MAP.get((name or "").lower(), "bfloat16")
    if torch is None:
        return key
    return getattr(torch, key)


def _load_causal_model(
    config: TrainingConfig,
    model_id: str,
    *,
    mode: str,
    use_qlora: bool,
) -> Any:
    from transformers import AutoModelForCausalLM  # type: ignore[import-not-found]

    load_kwargs: dict[str, Any] = {"local_files_only": True}
    if config.base_model_revision:
        load_kwargs["revision"] = config.base_model_revision
    if config.flash_attention:
        load_kwargs["attn_implementation"] = "flash_attention_2"
    dtype = _torch_dtype(config.precision)
    if dtype is not None and not use_qlora:
        load_kwargs["torch_dtype"] = dtype

    if use_qlora:
        from transformers import BitsAndBytesConfig  # type: ignore[import-not-found]

        load_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=str(config.bnb_4bit_quant_type),
            bnb_4bit_use_double_quant=bool(config.bnb_4bit_use_double_quant),
            bnb_4bit_compute_dtype=_bnb_compute_dtype(config.bnb_4bit_compute_dtype),
        )
        # Single-GPU only — never device_map="auto" (multi-GPU not implemented).
        load_kwargs["device_map"] = {"": 0}

    return AutoModelForCausalLM.from_pretrained(model_id, **load_kwargs)


def _build_training_arguments(config: TrainingConfig, output_dir: Path, *, has_eval: bool) -> Any:
    from transformers import TrainingArguments  # type: ignore[import-not-found]

    kwargs: dict[str, Any] = {
        "output_dir": str(output_dir / "hf_runs"),
        "per_device_train_batch_size": int(config.train_batch_size),
        "per_device_eval_batch_size": int(config.eval_batch_size),
        "gradient_accumulation_steps": int(config.gradient_accumulation),
        "learning_rate": float(config.learning_rate),
        "num_train_epochs": float(config.epochs or 1.0),
        "max_steps": int(config.max_steps) if config.max_steps else -1,
        "logging_steps": int(config.logging_steps),
        "save_steps": int(config.save_steps),
        "warmup_steps": int(config.warmup_steps),
        "weight_decay": float(config.weight_decay),
        "fp16": (config.precision or "").lower() == "fp16",
        "bf16": (config.precision or "").lower() == "bf16",
        "gradient_checkpointing": bool(config.gradient_checkpointing),
        "report_to": [],
        "seed": int(config.seed),
        "remove_unused_columns": False,
        "optim": str(config.optimizer),
        "lr_scheduler_type": str(config.lr_scheduler_type),
        "dataloader_num_workers": int(config.dataloader_workers),
        "save_total_limit": int(config.save_total_limit) if config.save_total_limit else None,
    }
    if has_eval and config.eval_during_training:
        eval_steps = int(config.eval_steps or config.save_steps)
        # Prefer modern eval_strategy; fall back for older transformers.
        kwargs["eval_strategy"] = "steps"
        kwargs["eval_steps"] = eval_steps
        if config.load_best_model_at_end:
            kwargs["load_best_model_at_end"] = True
            kwargs["metric_for_best_model"] = str(config.metric_for_best_model)
            kwargs["greater_is_better"] = bool(config.greater_is_better)
    else:
        kwargs["eval_strategy"] = "no"

    try:
        return TrainingArguments(**kwargs)
    except TypeError:
        if "eval_strategy" in kwargs:
            kwargs["evaluation_strategy"] = kwargs.pop("eval_strategy")
        return TrainingArguments(**kwargs)


def _attach_callbacks(
    trainer: Any,
    *,
    store: TrainingStore,
    job_id: str,
    events: TrainingEventLog,
    config: TrainingConfig,
    cancel_check: CancelCheck,
    collator: MaskedCausalLMCollator | None,
) -> None:
    try:
        from transformers import TrainerCallback  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return

    class LeviathanCallback(TrainerCallback):
        def on_step_end(self, args, state, control, **kwargs):  # noqa: ANN001
            if cancel_check():
                control.should_training_stop = True
            return control

        def on_log(self, args, state, control, logs=None, **kwargs):  # noqa: ANN001
            if not logs or state.global_step is None:
                return control
            step = int(state.global_step)
            epoch = float(state.epoch) if state.epoch is not None else None
            loss = logs.get("loss")
            if loss is not None:
                store.append_metric(
                    job_id,
                    metric_name="train_loss",
                    metric_value=float(loss),
                    step=step,
                    epoch=epoch,
                )
                events.emit("metric", metric="train_loss", value=float(loss), step=step)
                _append_derived_perplexity(store, job_id, events, float(loss), step=step)
            lr = logs.get("learning_rate")
            if lr is not None:
                store.append_metric(
                    job_id,
                    metric_name="learning_rate",
                    metric_value=float(lr),
                    step=step,
                    epoch=epoch,
                )
                events.emit("metric", metric="learning_rate", value=float(lr), step=step)
            # Never record fabricated accuracy — only pass through real keys if present.
            summary: dict[str, Any] = {"step": step}
            if loss is not None:
                summary["train_loss"] = float(loss)
            if lr is not None:
                summary["learning_rate"] = float(lr)
            store.update_job(
                job_id,
                progress=min(0.99, float(state.epoch or 0) / max(float(config.epochs or 1), 1e-6)),
                metrics_summary=summary,
            )
            return control

    trainer.add_callback(LeviathanCallback())

    if config.early_stopping_patience and config.load_best_model_at_end:
        try:
            from transformers import EarlyStoppingCallback  # type: ignore[import-not-found]

            trainer.add_callback(
                EarlyStoppingCallback(early_stopping_patience=int(config.early_stopping_patience))
            )
        except Exception:  # noqa: BLE001
            pass


def _append_derived_perplexity(
    store: TrainingStore,
    job_id: str,
    events: TrainingEventLog,
    loss: float,
    *,
    step: int,
    name: str = "train_perplexity",
) -> None:
    # Perplexity = exp(loss) for causal LM NLL — derived, not fabricated.
    if not math.isfinite(loss) or loss > 20:
        return
    ppl = float(math.exp(loss))
    store.append_metric(job_id, metric_name=name, metric_value=ppl, step=step, metadata={"derived_from": "loss"})
    events.emit("metric", metric=name, value=ppl, step=step)


def _record_throughput_metrics(
    *,
    store: TrainingStore,
    job_id: str,
    events: TrainingEventLog,
    metrics: dict[str, Any],
    tokens_per_sec: float,
    tokens_seen: int,
    wall_seconds: float,
) -> None:
    metrics["tokens_seen"] = int(tokens_seen)
    metrics["wall_seconds"] = round(wall_seconds, 4)
    metrics["tokens_per_sec"] = round(tokens_per_sec, 4)
    store.append_metric(
        job_id,
        metric_name="tokens_per_sec",
        metric_value=float(tokens_per_sec),
        step=int(metrics.get("global_step") or metrics.get("train_steps") or 0),
        metadata={"measured": True, "tokens_seen": tokens_seen, "wall_seconds": wall_seconds},
    )
    events.emit("metric", metric="tokens_per_sec", value=float(tokens_per_sec))
    loss = metrics.get("train_loss")
    if loss is not None:
        _append_derived_perplexity(
            store, job_id, events, float(loss), step=int(metrics.get("global_step") or 0)
        )


def _run_held_out_eval(
    *,
    trainer: Any,
    store: TrainingStore,
    job_id: str,
    events: TrainingEventLog,
    eval_ds: Any,
    train_metrics: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    evaluation: dict[str, Any] = {"train_metrics": train_metrics, "sft_provenance": provenance}
    store.update_job(job_id, status=DurableTrainingStatus.EVALUATING, phase="evaluating")
    events.emit("evaluation_started")
    if eval_ds is not None:
        try:
            eval_metrics = dict(trainer.evaluate() or {})
            # Strip any accidental accuracy fabrication keys if Trainer injected them from unused heads.
            eval_metrics.pop("eval_accuracy", None)
            eval_metrics.pop("accuracy", None)
            evaluation["eval_metrics"] = eval_metrics
            eval_loss = eval_metrics.get("eval_loss")
            if eval_loss is not None:
                store.append_metric(
                    job_id,
                    metric_name="eval_loss",
                    metric_value=float(eval_loss),
                    step=int(train_metrics.get("train_steps") or train_metrics.get("global_step") or 0),
                    metadata={"held_out": True},
                )
                _append_derived_perplexity(
                    store,
                    job_id,
                    events,
                    float(eval_loss),
                    step=int(train_metrics.get("global_step") or 0),
                    name="eval_perplexity",
                )
            evaluation["note"] = "Held-out validation metrics recorded — train loss is not evaluation"
        except Exception as exc:  # noqa: BLE001
            evaluation["eval_error"] = str(exc)[:400]
            evaluation["note"] = "Held-out eval attempted but failed; train metrics only"
    else:
        evaluation["note"] = "No validation split — train metrics only; not an improvement claim"
    events.emit("evaluation_finished", evaluation=evaluation)
    return evaluation


def _cancel_save(
    *,
    trainer: Any,
    store: TrainingStore,
    job_id: str,
    output_dir: Path,
    events: TrainingEventLog,
    mode: str,
) -> dict[str, Any]:
    ckpt_dir = output_dir / "checkpoint-cancel"
    ensure_dir(ckpt_dir)
    try:
        trainer.save_model(str(ckpt_dir))
    except Exception:  # noqa: BLE001
        pass
    store.update_job(
        job_id,
        status=DurableTrainingStatus.CANCELLED,
        phase="cancelled",
        finished_at=utc_now(),
        error="Cancelled by request",
        checkpoint={"path": str(ckpt_dir)},
    )
    events.emit("cancelled")
    return {"status": "cancelled", "mode": mode}


def _finalize_adapter_job(
    *,
    store: TrainingStore,
    job_id: str,
    config: TrainingConfig,
    output_dir: Path,
    adapter_dir: Path,
    events: TrainingEventLog,
    evaluation: dict[str, Any],
    metrics: dict[str, Any],
    mode: str,
    peft: bool,
) -> dict[str, Any]:
    card_path = output_dir / "MODEL_CARD.md"
    atomic_write_text(card_path, _model_card_markdown(config, evaluation=evaluation, mode=mode))
    manifest = adapter_dir / "leviathan_adapter.json"
    atomic_write_text(
        manifest,
        redact_secrets(
            json.dumps(
                {
                    "method": config.method,
                    "mode": mode,
                    "base_model_ref": config.base_model_ref,
                    "base_model_revision": config.base_model_revision,
                    "tokenizer_revision": config.tokenizer_revision or config.base_model_revision,
                    "config_hash": config.config_hash(),
                    "seed": config.seed,
                    "resume_from_checkpoint": config.resume_from_checkpoint,
                    "local_files_only": True,
                },
                indent=2,
            )
        ),
    )
    content_hash = sha256_file(manifest)
    artifact = store.add_artifact(
        job_id=job_id,
        artifact_type=f"{mode}_adapter",
        path=str(adapter_dir),
        base_model_ref=config.base_model_ref,
        dataset_version_id=config.dataset_version_id,
        method=config.method,
        config_hash=config.config_hash(),
        content_hash=content_hash,
        model_card_path=str(card_path),
        evaluation=evaluation,
        compatibility={"peft": peft, "inference_ready": False, "local_files_only": True},
    )
    store.update_job(
        job_id,
        status=DurableTrainingStatus.COMPLETED,
        phase="completed",
        progress=1.0,
        finished_at=utc_now(),
        artifact_id=artifact.artifact_id,
        evaluation=evaluation,
        metrics_summary=metrics,
    )
    events.emit("completed", artifact_id=artifact.artifact_id)
    return {"status": "completed", "mode": mode, "artifact_id": artifact.artifact_id, "metrics": metrics}


def _load_dataset_payload(path: Path) -> dict[str, Any]:
    """Load texts and optional chat message lists for SFT."""
    texts: list[str] = []
    messages_list: list[list[dict[str, str]]] = []
    if path.is_dir():
        files = sorted(path.glob("**/*.jsonl")) + sorted(path.glob("**/*.txt"))
    else:
        files = [path]
    for file in files:
        raw = file.read_text(encoding="utf-8", errors="replace")
        if file.suffix == ".jsonl":
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    if isinstance(obj.get("messages"), list):
                        msgs = [m for m in obj["messages"] if isinstance(m, dict)]
                        if msgs:
                            messages_list.append(msgs)  # type: ignore[arg-type]
                            parts = [
                                str(m.get("content") or "")
                                for m in msgs
                                if isinstance(m, dict) and m.get("content") is not None
                            ]
                            if parts:
                                texts.append("\n".join(parts))
                            continue
                    if "text" in obj:
                        texts.append(str(obj["text"]))
        else:
            for block in raw.split("\n\n"):
                block = block.strip()
                if block:
                    texts.append(block)
    return {"texts": texts, "messages_list": messages_list or None}


def _load_preference_pairs(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    files = sorted(path.glob("**/*.jsonl")) if path.is_dir() else [path]
    for file in files:
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            chosen = obj.get("chosen", obj.get("preferred_text"))
            rejected = obj.get("rejected", obj.get("rejected_text"))
            if not chosen or not rejected:
                continue
            prompt = str(obj.get("prompt") or obj.get("query") or "")
            rows.append({"prompt": prompt, "chosen": str(chosen), "rejected": str(rejected)})
    return rows


def _load_text_examples(path: Path) -> list[str]:
    return list(_load_dataset_payload(path)["texts"])


def _write_fixture_checkpoint(output_dir: Path, *, step: int, loss: float) -> Path:
    ckpt_dir = output_dir / f"checkpoint-{step}"
    ensure_dir(ckpt_dir)
    path = ckpt_dir / "state.json"
    atomic_write_text(
        path,
        json.dumps({"step": step, "loss": loss, "fixture": True}, indent=2),
    )
    return path


def _register_checkpoint(
    store: TrainingStore,
    job_id: str,
    path: Path,
    *,
    step: int,
    loss: float,
) -> None:
    store.add_checkpoint(
        job_id=job_id,
        path=str(path),
        step=step,
        epoch=None,
        content_hash=sha256_text(path.read_text(encoding="utf-8")),
        metrics={"train_loss": loss},
        metadata={"fixture": True},
    )
    store.update_job(job_id, checkpoint={"path": str(path), "step": step})


def _model_card_markdown(config: TrainingConfig, *, evaluation: dict[str, Any], mode: str) -> str:
    return "\n".join(
        [
            f"# Model card — {config.name}",
            "",
            f"- Mode: `{mode}`",
            f"- Method: `{config.method}`",
            f"- Base model: `{config.base_model_ref}`",
            f"- Dataset version: `{config.dataset_version_id or 'n/a'}`",
            f"- Seed: `{config.seed}`",
            f"- Config hash: `{config.config_hash()}`",
            f"- Evaluation: `{json.dumps(evaluation)}`",
            "",
            "This card contains only measured or declared metadata. No fabricated benchmarks.",
            "",
        ]
    )


def format_worker_error(exc: BaseException) -> str:
    return redact_secrets(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
