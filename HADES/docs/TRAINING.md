# HADES TRAINEN

HADES `TRAINEN` is an optional, isolated dataset and LoRA fine-tuning workspace exposed from **Modellen → TRAINEN**. It is deliberately separated from the normal LM Studio inference path so training failures, CUDA out-of-memory conditions, missing ML packages, or remote dataset failures do not prevent HADES from starting or using Chat/Agents.

## Boundary and non-goals

- The normal backend does **not** import PyTorch, Transformers, Datasets, PEFT, Accelerate or bitsandbytes.
- A training job runs in a separate Python process (`backend/training_worker.py`).
- The output is a **PEFT LoRA adapter** plus tokenizer metadata. HADES does not pretend that a loaded LM Studio GGUF model can be fine-tuned in place.
- A base model must be either a Hugging Face model ID or a local Hugging Face Transformers model directory. A standalone GGUF file is rejected by the API.
- Converting/merging an adapter to a deployable GGUF is intentionally outside this first boundary; that conversion depends on the target model/runtime and should be a separately verified workflow.

## Dataset sources

### Large local datasets (recommended for very large files)

Register an existing path. HADES stores metadata and a short preview but does **not** copy the source file into its own data directory. This is the intended path for datasets that are tens or hundreds of GB.

Supported registrations:

- JSONL / NDJSON — streamed line by line for inspection and training.
- CSV / TSV — streamed by row for inspection and training.
- JSON arrays — supported for bounded files; JSON files above 256 MB are rejected for preview because parsing would require loading the array into memory. Convert large JSON arrays to JSONL or Parquet.
- Parquet — metadata can be registered without `pyarrow`; preview becomes available once the optional training stack (which includes the Hugging Face Datasets dependencies) is installed.

Browser upload is capped at 512 MB. Larger files should use path registration to avoid duplicating large data.

### Hugging Face datasets

HADES uses the official Hugging Face Dataset Viewer API to discover configs/splits and fetch a small preview. The registered metadata contains only the dataset ID/config/split and the preview; it does not download the full dataset.

During training, Hugging Face `datasets.load_dataset(..., streaming=True)` streams the selected split. This avoids materializing a large dataset in RAM and avoids requiring the whole dataset to be downloaded before training begins. Hugging Face's normal local cache behavior still applies to model files and any dataset transport/cache layers used by the installed library.

For gated/private datasets, enter an HF token in the TRAINEN UI. HADES passes it to the current API call and, when starting a worker, through the child-process environment. It is not written to dataset/job JSON metadata.

## Input formatting

An explicit `text_field` can be selected. Without one, HADES recognizes common supervised fine-tuning shapes:

- `messages: [{role, content}, ...]` (uses the tokenizer's chat template when one exists during training)
- `instruction` + optional `input` + `output`
- `prompt` + `completion`
- `text`
- as a last resort, the first non-empty string column

HADES does not generate missing answers or synthesize training examples automatically in this subsystem.

## Optional training installation

The standard HADES installation stays lightweight. Install training dependencies only on machines that should train models:

```powershell
python -m pip install -r backend/requirements-training.txt
```

For NVIDIA machines, select/install the PyTorch build appropriate for the local driver/toolchain if the default PyPI wheel is not the desired build. `bitsandbytes` remains optional and is required only for the 4-bit QLoRA switch.

The TRAINEN page reports package availability before enabling the start button.

## Job lifecycle

1. HADES validates the dataset registration, model source and local policies.
2. The backend writes a job descriptor under the HADES data directory.
3. The backend launches `training_worker.py` as a separate Python process and redirects stdout/stderr to a per-job log.
4. The worker streams/tokenizes examples, attaches LoRA to all linear layers, trains with Transformers `Trainer`, and persists progress after steps.
5. A stop request creates a cancellation marker. The Trainer callback stops at the next safe callback boundary.
6. On success, the adapter/tokenizer is written below the job's `adapter` directory. On failure, a structured error remains in `job.json` and the log is available from the UI.

A cancellation requested while the worker is inside a blocking model download/load can take effect only after that operation returns; HADES does not kill arbitrary persisted PIDs because PID reuse would make that unsafe across restarts.

## Policies and privacy

- Local path registration obeys `file_read_policy`.
- Hugging Face inspection/registration and remote model/dataset training obey `network_policy`.
- `block` cannot be overridden by the TRAINEN request.
- With policy `ask`, the explicit UI action supplies per-action approval.
- No training data is automatically inserted into HADES Memory or Knowledge.
- Dataset and job IDs are validated before filesystem path construction to prevent path traversal through API identifiers.

## Storage

Training state is filesystem-backed under the same HADES data root as the configured core database:

```text
<data-root>/training/
  datasets/<dataset-id>/dataset.json
  uploads/<upload-id>/<uploaded-source>
  jobs/<job-id>/job.json
  jobs/<job-id>/train.log
  jobs/<job-id>/adapter/
```

This avoids a database migration and keeps the feature additive. Local zero-copy registrations point to the original source and therefore require that the file remains at that path for training.

## Adaptive Training Memory Engine (ATME)

TRAINEN includes an Adaptive Training Memory Engine that plans a resource-aware execution strategy before launch. See `docs/TRAINING_ATME.md` for architecture, strategies, API extensions, and honesty gates.

The TRAINEN UI exposes:

- memory strategy selection (`auto` / GPU only / save VRAM / experimental streaming);
- execution-plan preview without starting a job;
- resolved strategy + measured bottleneck on active jobs.

Planning and hardware inspection do **not** require the optional training ML stack for normal HADES startup.

## Verification scope

Focused tests live in `backend/tests/test_training.py` and `backend/tests/test_atme_*.py` and cover deterministic SFT formatting, zero-copy registration, invalid JSONL diagnostics, mapping validation, optional Parquet preview behavior, Hugging Face ID validation, local file policy gates, ATME planning/estimation, telemetry redaction, buffer pooling, and capability-gated numerical parity. Full release verification must still pass before merge. Do not treat missing GitHub checks as verification when those checks are intentionally disabled.
