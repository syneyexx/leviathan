"""Real LoRA/QLoRA trainer loop + deterministic fixture mode.

Optional torch/transformers/peft are imported lazily so the API process never
crashes when they are absent.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_file, sha256_text
from Data.modules.common.secrets import redact_secrets

from ..capabilities import safe_import
from ..config import TrainingConfig
from ..events import TrainingEventLog
from ..store import TrainingStore, utc_now
from ..types import DurableTrainingStatus


CancelCheck = Callable[[], bool]


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
    method = (config.method or "").lower()
    if method == "dpo":
        # Honesty: durable worker must not silently run causal-LM LoRA under method=dpo.
        # Preference optimization is the recipe `dpo_micro` path (DpoRecipeTrainer).
        raise RuntimeError(
            "Durable job method=dpo does not run causal-LM LoRA. "
            "Use recipe pref_dpo_v1 / DpoRecipeTrainer (dpo_micro) for preference pairs. "
            "HF/GPU production DPO is not claimed."
        )
    if _fixture_forced(config):
        return run_fixture_loop(
            job_id=job_id,
            store=store,
            config=config,
            output_dir=output_dir,
            events=events,
            cancel_check=cancel_check,
        )
    return run_lora_loop(
        job_id=job_id,
        store=store,
        config=config,
        output_dir=output_dir,
        events=events,
        cancel_check=cancel_check,
    )


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

    # Evaluate (fixture)
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

    # Export adapter stub
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


def run_lora_loop(
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
    peft = safe_import("peft")
    if torch is None or transformers is None or peft is None:
        missing = [
            name
            for name, mod in (("torch", torch), ("transformers", transformers), ("peft", peft))
            if mod is None
        ]
        raise RuntimeError(f"Missing required packages for LoRA training: {', '.join(missing)}")

    events.emit("phase_changed", phase="running", message="LoRA training started")
    store.update_job(job_id, status=DurableTrainingStatus.RUNNING, phase="running")

    # Real path: load model + PEFT + Trainer when dataset path exists.
    dataset_path = config.dataset_path
    if not dataset_path or not Path(dataset_path).exists():
        raise RuntimeError("dataset_path required and must exist for LoRA training")

    from transformers import (  # type: ignore[import-not-found]
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model  # type: ignore[import-not-found]

    events.emit("log", message=f"Loading tokenizer/model: {config.base_model_ref}")
    tok_kwargs: dict[str, Any] = {}
    model_kwargs: dict[str, Any] = {}
    if config.tokenizer_revision:
        tok_kwargs["revision"] = config.tokenizer_revision
    if config.base_model_revision:
        model_kwargs["revision"] = config.base_model_revision
        tok_kwargs.setdefault("revision", config.base_model_revision)
    tokenizer = AutoTokenizer.from_pretrained(config.base_model_ref, **tok_kwargs)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    load_kwargs: dict[str, Any] = dict(model_kwargs)
    if config.load_in_4bit or (config.method or "").lower() == "qlora":
        bnb = safe_import("bitsandbytes")
        if bnb is None:
            raise RuntimeError("QLoRA/4-bit requires bitsandbytes")
        from transformers import BitsAndBytesConfig  # type: ignore[import-not-found]

        load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True)
        load_kwargs["device_map"] = "auto"

    model = AutoModelForCausalLM.from_pretrained(config.base_model_ref, **load_kwargs)
    if config.load_in_4bit or (config.method or "").lower() == "qlora":
        # Required for stable k-bit LoRA; without this, QLoRA is fragile.
        try:
            from peft import prepare_model_for_kbit_training  # type: ignore[import-not-found]

            model = prepare_model_for_kbit_training(model)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"QLoRA requires prepare_model_for_kbit_training: {exc}") from exc
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
    train_texts = [ex.text for ex in split.train]
    if len(train_texts) < 1:
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
    events.emit("sft_provenance", provenance=sft_prov)

    def tokenize_batch(batch: dict[str, list[str]]) -> dict[str, Any]:
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=int(config.max_seq_length),
            padding="max_length",
        )

    # Prefer HF datasets if available; else simple torch Dataset.
    datasets_mod = safe_import("datasets")
    if datasets_mod is not None:
        ds = datasets_mod.Dataset.from_dict({"text": train_texts})
        ds = ds.map(tokenize_batch, batched=True, remove_columns=["text"])
        eval_ds = None
        if split.validation:
            eval_ds = datasets_mod.Dataset.from_dict({"text": [ex.text for ex in split.validation]})
            eval_ds = eval_ds.map(tokenize_batch, batched=True, remove_columns=["text"])
    else:
        raise RuntimeError("datasets package required for LoRA training path")

    args = TrainingArguments(
        output_dir=str(output_dir / "hf_runs"),
        per_device_train_batch_size=int(config.train_batch_size),
        per_device_eval_batch_size=int(config.eval_batch_size),
        gradient_accumulation_steps=int(config.gradient_accumulation),
        learning_rate=float(config.learning_rate),
        num_train_epochs=float(config.epochs or 1.0),
        max_steps=int(config.max_steps) if config.max_steps else -1,
        logging_steps=int(config.logging_steps),
        save_steps=int(config.save_steps),
        warmup_steps=int(config.warmup_steps),
        weight_decay=float(config.weight_decay),
        fp16=config.precision == "fp16",
        bf16=config.precision == "bf16",
        gradient_checkpointing=bool(config.gradient_checkpointing),
        report_to=[],
        seed=int(config.seed),
        remove_unused_columns=False,
        evaluation_strategy="epoch" if eval_ds is not None else "no",
    )

    class _CancelCallback:
        def __init__(self) -> None:
            self.trainer = None

        def on_step_end(self, args, state, control, **kwargs):  # noqa: ANN001
            if cancel_check():
                control.should_training_stop = True
            if state.global_step and state.log_history:
                last = state.log_history[-1]
                loss = last.get("loss")
                if loss is not None:
                    store.append_metric(
                        job_id,
                        metric_name="train_loss",
                        metric_value=float(loss),
                        step=int(state.global_step),
                        epoch=float(state.epoch) if state.epoch is not None else None,
                    )
                    events.emit("metric", metric="train_loss", value=float(loss), step=int(state.global_step))
                    store.update_job(
                        job_id,
                        progress=min(0.99, float(state.epoch or 0) / max(float(config.epochs or 1), 1e-6)),
                        metrics_summary={"train_loss": float(loss), "step": int(state.global_step)},
                    )
            return control

    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ds,
        eval_dataset=eval_ds,
        data_collator=collator,
    )
    # Attach cancel by wrapping train loop checks via callback if available.
    try:
        from transformers import TrainerCallback  # type: ignore[import-not-found]

        class CancelCallback(TrainerCallback):
            def on_step_end(self, args, state, control, **kwargs):  # noqa: ANN001
                if cancel_check():
                    control.should_training_stop = True
                return control

            def on_log(self, args, state, control, logs=None, **kwargs):  # noqa: ANN001
                if not logs:
                    return control
                loss = logs.get("loss")
                if loss is not None and state.global_step is not None:
                    store.append_metric(
                        job_id,
                        metric_name="train_loss",
                        metric_value=float(loss),
                        step=int(state.global_step),
                        epoch=float(state.epoch) if state.epoch is not None else None,
                    )
                    events.emit(
                        "metric",
                        metric="train_loss",
                        value=float(loss),
                        step=int(state.global_step),
                    )
                return control

        trainer.add_callback(CancelCallback())
    except Exception:  # noqa: BLE001
        pass

    train_result = trainer.train(resume_from_checkpoint=config.resume_from_checkpoint)
    if cancel_check():
        ckpt_dir = output_dir / "checkpoint-cancel"
        ensure_dir(ckpt_dir)
        trainer.save_model(str(ckpt_dir))
        store.update_job(
            job_id,
            status=DurableTrainingStatus.CANCELLED,
            phase="cancelled",
            finished_at=utc_now(),
            error="Cancelled by request",
            checkpoint={"path": str(ckpt_dir)},
        )
        events.emit("cancelled")
        return {"status": "cancelled", "mode": "lora"}

    adapter_dir = output_dir / "adapter"
    ensure_dir(adapter_dir)
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))

    metrics = dict(getattr(train_result, "metrics", {}) or {})
    evaluation: dict[str, Any] = {"train_metrics": metrics, "sft_provenance": sft_prov}
    store.update_job(job_id, status=DurableTrainingStatus.EVALUATING, phase="evaluating")
    events.emit("evaluation_started")
    # Held-out evaluation — training loss is not evaluation.
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
                    step=int(metrics.get("train_steps") or metrics.get("global_step") or 0),
                    metadata={"held_out": True},
                )
            evaluation["note"] = "Held-out validation metrics recorded — train loss is not evaluation"
        except Exception as exc:  # noqa: BLE001
            evaluation["eval_error"] = str(exc)[:400]
            evaluation["note"] = "Held-out eval attempted but failed; train metrics only"
    else:
        evaluation["note"] = "No validation split — train metrics only; not an improvement claim"
    events.emit("evaluation_finished", evaluation=evaluation)

    card_path = output_dir / "MODEL_CARD.md"
    atomic_write_text(card_path, _model_card_markdown(config, evaluation=evaluation, mode="lora"))
    manifest = adapter_dir / "leviathan_adapter.json"
    atomic_write_text(
        manifest,
        redact_secrets(
            json.dumps(
                {
                    "method": config.method,
                    "base_model_ref": config.base_model_ref,
                    "base_model_revision": config.base_model_revision,
                    "tokenizer_revision": config.tokenizer_revision or config.base_model_revision,
                    "config_hash": config.config_hash(),
                    "seed": config.seed,
                    "sft_provenance": sft_prov,
                    "resume_from_checkpoint": config.resume_from_checkpoint,
                },
                indent=2,
            )
        ),
    )
    content_hash = sha256_file(manifest)
    artifact = store.add_artifact(
        job_id=job_id,
        artifact_type="lora_adapter",
        path=str(adapter_dir),
        base_model_ref=config.base_model_ref,
        dataset_version_id=config.dataset_version_id,
        method=config.method,
        config_hash=config.config_hash(),
        content_hash=content_hash,
        model_card_path=str(card_path),
        evaluation=evaluation,
        compatibility={"peft": True, "inference_ready": False},
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
    return {"status": "completed", "mode": "lora", "artifact_id": artifact.artifact_id, "metrics": metrics}


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
