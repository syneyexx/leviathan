"""Optional LoRA training worker launched by :mod:`training_service`.

Heavy ML packages are imported only after process startup. The normal HADES FastAPI
process therefore remains independent from PyTorch/Transformers. When Dataset Brain
has materialized a source locally, training prefers that offline snapshot.

ATME execution plans are honored when present on job.json. Strategy runtimes that
require custom streaming stay isolated to this worker process.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from dataset_brain import read_manifest
from gen2.flight_recorder import redact_secrets
from training_service import TrainingWorkspace, format_training_example, read_json, utc_now, write_job_state

_HIDDEN_RECORD_KEYS = frozenset(
    {
        "reasoning",
        "chain_of_thought",
        "chain-of-thought",
        "cot",
        "thought",
        "thoughts",
        "scratchpad",
        "internal_reasoning",
        "analysis",
    }
)


def _cancel_requested(job_path: Path) -> bool:
    return (job_path.parent / "cancel.requested").is_file()


def _dataset_root(job_path: Path) -> Path:
    return job_path.parents[2]


def _offline_brain_snapshot(dataset: dict[str, Any], training_root: Path) -> Path | None:
    dataset_id = str(dataset.get("id") or "")
    if not dataset_id:
        return None
    try:
        manifest = read_manifest(training_root, dataset_id)
    except KeyError:
        return None
    if not manifest or not manifest.get("materialized_complete"):
        return None
    path = Path(str(manifest.get("snapshot_path") or "")).expanduser().resolve()
    return path if path.is_file() else None


def _load_streaming_dataset(dataset: dict[str, Any], hf_token: str | None, training_root: Path):
    from datasets import load_dataset

    offline = _offline_brain_snapshot(dataset, training_root)
    if offline is not None:
        print(f"[HADES TRAINING] Offline Dataset Brain snapshot: {offline}", flush=True)
        return load_dataset("json", data_files=str(offline), split="train", streaming=True)

    source_type = str(dataset.get("source_type") or "")
    if source_type == "huggingface":
        source = dict(dataset.get("source") or {})
        return load_dataset(
            str(source["dataset_id"]),
            name=str(source["config"]),
            split=str(source["split"]),
            streaming=True,
            token=hf_token or None,
        )

    path = Path(str(dataset.get("path") or "")).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Datasetbestand bestaat niet meer: {path}")
    suffix = path.suffix.lower()
    if suffix in {".json", ".jsonl", ".ndjson"}:
        return load_dataset("json", data_files=str(path), split="train", streaming=True)
    if suffix == ".csv":
        return load_dataset("csv", data_files=str(path), split="train", streaming=True)
    if suffix == ".tsv":
        return load_dataset("csv", data_files=str(path), split="train", streaming=True, delimiter="\t")
    if suffix == ".parquet":
        return load_dataset("parquet", data_files=str(path), split="train", streaming=True)
    raise ValueError(f"Niet-ondersteund trainingsformaat: {suffix or '(geen extensie)'}.")


def _redact_training_text(text: str) -> str:
    if not text:
        return ""
    redacted = redact_secrets(text)
    return str(redacted).strip() if redacted is not None else ""


def _render_text(row: dict[str, Any], mapping: dict[str, Any], tokenizer: Any) -> str:
    explicit_field = str(mapping.get("text_field") or "").strip()
    if explicit_field and explicit_field.lower() in _HIDDEN_RECORD_KEYS:
        raise ValueError("Een hidden-reasoning kolom kan niet als trainings-tekstkolom worden gebruikt.")

    safe_row = {key: value for key, value in row.items() if str(key).lower() not in _HIDDEN_RECORD_KEYS}
    if explicit_field:
        return _redact_training_text(format_training_example(safe_row, mapping))

    messages = safe_row.get("messages")
    if isinstance(messages, list) and messages and getattr(tokenizer, "chat_template", None):
        try:
            rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
            if isinstance(rendered, str) and rendered.strip():
                return _redact_training_text(rendered)
        except (ValueError, TypeError, KeyError):
            pass
    return _redact_training_text(format_training_example(safe_row, mapping))


def _append_telemetry(job_path: Path, sample: dict[str, Any]) -> None:
    from training.telemetry import sanitize_telemetry_payload

    path = job_path.parent / "telemetry.json"
    payload: dict[str, Any]
    if path.is_file():
        try:
            payload = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            payload = {"samples": []}
    else:
        payload = {"samples": []}
    samples = payload.get("samples")
    if not isinstance(samples, list):
        samples = []
    samples.append(sanitize_telemetry_payload(sample))
    payload["samples"] = samples[-500:]
    # Atomic-ish replace via training_service helper pattern.
    from training_service import _atomic_write_json

    _atomic_write_json(path, payload)


def _resolve_strategy_name(job: dict[str, Any], params: dict[str, Any]) -> str:
    plan = job.get("resolved_execution_plan")
    if isinstance(plan, dict) and plan.get("strategy"):
        return str(plan["strategy"])
    if params.get("load_in_4bit"):
        return "gpu_resident_4bit"
    return str(params.get("memory_strategy") or "gpu_resident")


def run(job_path: Path) -> int:
    job_path = job_path.expanduser().resolve()
    job = read_json(job_path)
    training_root = _dataset_root(job_path)
    workspace = TrainingWorkspace(training_root)
    dataset = workspace.get_dataset(str(job["dataset_id"]))
    params = dict(job.get("parameters") or {})
    output_dir = Path(str(job["output_dir"])).expanduser().resolve()
    hf_token = os.environ.get("HF_TOKEN") or None
    stream_runtime = None
    peak_vram = 0
    peak_ram = 0
    h2d_bytes = 0

    try:
        import torch
        from peft import LoraConfig, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainerCallback,
            TrainingArguments,
        )

        from training.execution_plan import MemoryStrategy, TrainingExecutionPlan
        from training.failure_codes import TrainingFailureCode
        from training.telemetry import classify_bottleneck

        if _cancel_requested(job_path):
            write_job_state(
                job_path,
                {
                    "status": "cancelled",
                    "finished_at": utc_now(),
                    "error": None,
                    "failure_code": TrainingFailureCode.CANCELLED_BY_USER,
                },
            )
            return 0

        write_job_state(job_path, {"status": "waiting_for_model"})
        base_model = str(job["base_model"])
        strategy_name = _resolve_strategy_name(job, params)
        plan_raw = job.get("resolved_execution_plan")
        plan = TrainingExecutionPlan.model_validate(plan_raw) if isinstance(plan_raw, dict) else None
        print(f"[HADES TRAINING] Base model: {base_model}", flush=True)
        print(f"[HADES TRAINING] Dataset: {dataset.get('name') or dataset.get('id')}", flush=True)
        print(f"[HADES TRAINING] ATME strategy: {strategy_name}", flush=True)

        tokenizer = AutoTokenizer.from_pretrained(base_model, token=hf_token, trust_remote_code=False)
        if tokenizer.pad_token_id is None:
            if tokenizer.eos_token_id is None:
                raise ValueError("Tokenizer heeft geen pad_token of eos_token; veilige automatische padding is niet mogelijk.")
            tokenizer.pad_token = tokenizer.eos_token

        model_kwargs: dict[str, Any] = {"token": hf_token, "trust_remote_code": False, "dtype": "auto"}
        strategy = MemoryStrategy(strategy_name)
        if strategy == MemoryStrategy.GPU_RESIDENT_4BIT or bool(params.get("load_in_4bit")):
            from training.strategies import qlora as qlora_strategy

            if plan is None:
                plan = TrainingExecutionPlan(strategy=MemoryStrategy.GPU_RESIDENT_4BIT, feasible=True, confidence="medium")
            model_kwargs = qlora_strategy.apply_model_load_kwargs(plan, model_kwargs, torch_module=torch)
        elif strategy == MemoryStrategy.CPU_OFFLOAD:
            from training.strategies import cpu_offload as cpu_offload_strategy

            if plan is None:
                plan = TrainingExecutionPlan(strategy=MemoryStrategy.CPU_OFFLOAD, feasible=True, confidence="medium")
            model_kwargs = cpu_offload_strategy.apply_model_load_kwargs(plan, model_kwargs)
        elif strategy in {MemoryStrategy.RAM_LAYER_STREAMING, MemoryStrategy.NVME_LAYER_STREAMING}:
            from training.strategies import layer_streaming as layer_streaming_strategy

            if plan is None:
                plan = TrainingExecutionPlan(
                    strategy=strategy,
                    feasible=True,
                    confidence="medium",
                    buffer_count=int(params.get("resolved_buffer_count") or 1),
                    activation_checkpointing=str(params.get("activation_checkpointing") or "enabled"),  # type: ignore[arg-type]
                )
            model_kwargs = layer_streaming_strategy.apply_model_load_kwargs(plan, model_kwargs)
        else:
            from training.strategies import gpu_resident as gpu_resident_strategy

            if plan is None:
                plan = TrainingExecutionPlan(strategy=MemoryStrategy.GPU_RESIDENT, feasible=True, confidence="medium")
            model_kwargs = gpu_resident_strategy.apply_model_load_kwargs(plan, model_kwargs)

        write_job_state(job_path, {"status": "allocating"})
        model = AutoModelForCausalLM.from_pretrained(base_model, **model_kwargs)
        if hasattr(model.config, "use_cache"):
            model.config.use_cache = False

        if strategy == MemoryStrategy.GPU_RESIDENT_4BIT or bool(params.get("load_in_4bit")):
            from training.strategies import qlora as qlora_strategy

            model = qlora_strategy.prepare_model(model, plan)

        lora_config = LoraConfig(
            r=int(params["lora_r"]),
            lora_alpha=int(params["lora_alpha"]),
            lora_dropout=float(params["lora_dropout"]),
            bias="none",
            task_type="CAUSAL_LM",
            target_modules="all-linear",
        )
        model = get_peft_model(model, lora_config)

        if strategy in {MemoryStrategy.RAM_LAYER_STREAMING, MemoryStrategy.NVME_LAYER_STREAMING}:
            from training.strategies import layer_streaming as layer_streaming_strategy

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model, stream_runtime = layer_streaming_strategy.prepare_model(
                model, plan, torch_module=torch, device=device
            )

        trainable = model.get_nb_trainable_parameters()
        print(f"[HADES TRAINING] Trainable parameters: {trainable[0]} / {trainable[1]}", flush=True)

        raw_dataset = _load_streaming_dataset(dataset, hf_token, training_root)
        sequence_length = int(params["sequence_length"])
        mapping = dict(dataset.get("mapping") or {})

        def tokenize_row(row: dict[str, Any]) -> dict[str, Any]:
            text = _render_text(row, mapping, tokenizer)
            if not text:
                return {"input_ids": [], "attention_mask": []}
            encoded = tokenizer(text, truncation=True, max_length=sequence_length, add_special_tokens=True)
            return {
                "input_ids": list(encoded["input_ids"]),
                "attention_mask": list(encoded.get("attention_mask") or [1] * len(encoded["input_ids"])),
            }

        source_columns = list(getattr(raw_dataset, "column_names", None) or [])
        map_kwargs: dict[str, Any] = {"remove_columns": source_columns} if source_columns else {}
        tokenized = raw_dataset.map(tokenize_row, **map_kwargs)
        tokenized = tokenized.filter(lambda row: bool(row.get("input_ids")))
        tokenized = tokenized.select_columns(["input_ids", "attention_mask"])

        class HadesProgressCallback(TrainerCallback):
            def on_step_end(self, args, state, control, **kwargs):  # type: ignore[no-untyped-def]
                nonlocal peak_vram, peak_ram, h2d_bytes
                max_steps = max(1, int(state.max_steps or params["max_steps"]))
                step = max(0, int(state.global_step or 0))
                vram_alloc = None
                vram_reserved = None
                vram_free = None
                vram_total = None
                if torch.cuda.is_available():
                    try:
                        vram_alloc = int(torch.cuda.memory_allocated())
                        vram_reserved = int(torch.cuda.memory_reserved())
                        free, total = torch.cuda.mem_get_info()
                        vram_free = int(free)
                        vram_total = int(total)
                        peak_vram = max(peak_vram, vram_alloc)
                    except Exception:
                        pass
                try:
                    import resource

                    peak_ram = max(peak_ram, int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024)
                except Exception:
                    pass
                stream_meta: dict[str, Any] = {}
                if stream_runtime is not None:
                    stream_meta = stream_runtime.telemetry_snapshot()
                    h2d_bytes = max(h2d_bytes, int(stream_meta.get("h2d_bytes_total") or 0))
                bottleneck = classify_bottleneck(
                    gpu_util=None,
                    h2d_bytes_per_sec=None,
                    storage_read_bytes_per_sec=None,
                    step_duration_ms=None,
                    vram_allocated_bytes=vram_alloc,
                    vram_total_bytes=vram_total,
                    strategy=strategy_name,
                )
                write_job_state(
                    job_path,
                    {
                        "status": "running",
                        "step": step,
                        "max_steps": max_steps,
                        "progress": min(1.0, step / max_steps),
                        "runtime_peak_vram_bytes": peak_vram or None,
                        "runtime_peak_ram_bytes": peak_ram or None,
                        "runtime_bytes_host_to_device": h2d_bytes or None,
                        "observed_bottleneck": bottleneck,
                    },
                )
                _append_telemetry(
                    job_path,
                    {
                        "ts": utc_now(),
                        "strategy": strategy_name,
                        "step": step,
                        "max_steps": max_steps,
                        "vram_allocated_bytes": vram_alloc,
                        "vram_reserved_bytes": vram_reserved,
                        "vram_free_bytes": vram_free,
                        "vram_total_bytes": vram_total,
                        "process_ram_bytes": peak_ram or None,
                        "observed_bottleneck": bottleneck,
                        **stream_meta,
                    },
                )
                if _cancel_requested(job_path):
                    control.should_training_stop = True
                return control

            def on_log(self, args, state, control, logs=None, **kwargs):  # type: ignore[no-untyped-def]
                if isinstance(logs, dict):
                    serializable: dict[str, float | int | str] = {}
                    for key, value in logs.items():
                        if isinstance(value, (str, int, float)):
                            serializable[str(key)] = value
                    if serializable:
                        write_job_state(job_path, {"metrics": serializable})
                return control

        write_job_state(job_path, {"status": "warming_up"})
        output_dir.mkdir(parents=True, exist_ok=True)
        max_steps = int(params["max_steps"])
        load_in_4bit = strategy == MemoryStrategy.GPU_RESIDENT_4BIT or bool(params.get("load_in_4bit"))
        use_bf16 = bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported() and not load_in_4bit)
        use_fp16 = bool(torch.cuda.is_available() and not use_bf16 and not load_in_4bit)
        save_steps = max(10, min(100, max_steps // 4 if max_steps >= 40 else max_steps))
        gradient_checkpointing = str(params.get("activation_checkpointing") or (plan.activation_checkpointing if plan else "auto"))
        if gradient_checkpointing == "auto":
            gradient_checkpointing_enabled = strategy in {
                MemoryStrategy.CPU_OFFLOAD,
                MemoryStrategy.RAM_LAYER_STREAMING,
                MemoryStrategy.NVME_LAYER_STREAMING,
            }
        else:
            gradient_checkpointing_enabled = gradient_checkpointing == "enabled"

        arguments = TrainingArguments(
            output_dir=str(output_dir),
            max_steps=max_steps,
            per_device_train_batch_size=int(params["batch_size"]),
            gradient_accumulation_steps=int(params["gradient_accumulation_steps"]),
            learning_rate=float(params["learning_rate"]),
            logging_steps=1,
            save_strategy="steps",
            save_steps=save_steps,
            save_total_limit=2,
            report_to=[],
            remove_unused_columns=False,
            dataloader_num_workers=0,
            seed=42,
            bf16=use_bf16,
            fp16=use_fp16,
            gradient_checkpointing=gradient_checkpointing_enabled,
        )
        collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
        trainer = Trainer(
            model=model,
            args=arguments,
            train_dataset=tokenized,
            data_collator=collator,
            processing_class=tokenizer,
            callbacks=[HadesProgressCallback()],
        )
        write_job_state(job_path, {"status": "running"})
        trainer.train()

        if _cancel_requested(job_path):
            write_job_state(
                job_path,
                {
                    "status": "cancelled",
                    "finished_at": utc_now(),
                    "error": None,
                    "failure_code": TrainingFailureCode.CANCELLED_BY_USER,
                    "runtime_peak_vram_bytes": peak_vram or None,
                    "runtime_peak_ram_bytes": peak_ram or None,
                    "runtime_bytes_host_to_device": h2d_bytes or None,
                },
            )
            print("[HADES TRAINING] Geannuleerd.", flush=True)
            return 0

        write_job_state(job_path, {"status": "checkpointing"})
        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))
        write_job_state(
            job_path,
            {
                "status": "completed",
                "step": max_steps,
                "progress": 1.0,
                "finished_at": utc_now(),
                "error": None,
                "failure_code": None,
                "runtime_peak_vram_bytes": peak_vram or None,
                "runtime_peak_ram_bytes": peak_ram or None,
                "runtime_bytes_host_to_device": h2d_bytes or None,
            },
        )
        print(f"[HADES TRAINING] LoRA-adapter opgeslagen in {output_dir}", flush=True)
        return 0
    except BaseException as exc:
        from training.failure_codes import TrainingFailureCode

        error = f"{type(exc).__name__}: {exc}"
        failure_code = TrainingFailureCode.WORKER_CRASH
        text = error.lower()
        if "out of memory" in text or "cuda oom" in text:
            failure_code = TrainingFailureCode.CUDA_OOM
        elif "unsupported_architecture" in text:
            failure_code = TrainingFailureCode.UNSUPPORTED_ARCHITECTURE
        elif "bitsandbytes" in text:
            failure_code = TrainingFailureCode.BITSANDBYTES_UNAVAILABLE
        try:
            write_job_state(
                job_path,
                {
                    "status": "failed",
                    "error": error[:4000],
                    "failure_code": failure_code,
                    "finished_at": utc_now(),
                    "runtime_peak_vram_bytes": peak_vram or None,
                    "runtime_peak_ram_bytes": peak_ram or None,
                    "runtime_bytes_host_to_device": h2d_bytes or None,
                },
            )
        except Exception:
            pass
        print(f"[HADES TRAINING] MISLUKT: {error}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return 1
    finally:
        if stream_runtime is not None:
            try:
                stream_runtime.close()
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES isolated LoRA trainer")
    parser.add_argument("--job", required=True, help="Pad naar job.json")
    args = parser.parse_args()
    return run(Path(args.job))


if __name__ == "__main__":
    raise SystemExit(main())
