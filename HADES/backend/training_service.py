"""Isolated local training workspace for HADES.

The core HADES runtime must not depend on heavyweight ML training packages.  This
module therefore keeps dataset inspection/registration in the normal backend and
launches the optional trainer in a separate Python process only when requested.
"""

from __future__ import annotations

import csv
import importlib.metadata
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import httpx

HF_DATASET_SERVER = "https://datasets-server.huggingface.co"
HF_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DATASET_RECORD_ID_RE = re.compile(r"^ds_[0-9a-f]{16}$")
JOB_RECORD_ID_RE = re.compile(r"^train_[0-9a-f]{16}$")
SUPPORTED_LOCAL_EXTENSIONS = {".jsonl", ".ndjson", ".json", ".csv", ".tsv", ".parquet"}
UPLOAD_LIMIT_BYTES = 512 * 1024 * 1024
JSON_PREVIEW_LIMIT_BYTES = 256 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        os.replace(temp_name, path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Verwacht JSON-object in {path.name}.")
    return value


def write_job_state(job_path: str | Path, updates: dict[str, Any]) -> dict[str, Any]:
    path = Path(job_path)
    current = read_json(path)
    current.update(updates)
    current["updated_at"] = utc_now()
    _atomic_write_json(path, current)
    return current


def _process_is_alive(pid: int) -> bool:
    """Best-effort cross-platform liveness check without signalling/killing the worker."""
    if int(pid or 0) <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _clean_name(value: str, *, fallback: str) -> str:
    value = " ".join(str(value or "").strip().split())
    return value[:160] or str(fallback)[:160]


def _safe_dataset_id(value: str) -> str:
    value = str(value or "").strip()
    if not HF_DATASET_ID_RE.fullmatch(value):
        raise ValueError("Hugging Face dataset-ID moet de vorm 'organisatie/dataset' hebben.")
    return value


def _safe_split_component(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 160 or any(ch in value for ch in "\r\n\0"):
        raise ValueError(f"Ongeldige Hugging Face {label}.")
    return value


def _stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def format_training_example(row: dict[str, Any], mapping: dict[str, Any] | None = None) -> str:
    """Convert common coding/SFT dataset shapes to deterministic useful text.

    Mapping can explicitly select ``text_field``. Otherwise chat, instruction,
    prompt/completion, query/answer and repository issue/patch conventions are
    detected before the conservative first-string fallback. No content is invented.
    """

    mapping = mapping or {}
    text_field = str(mapping.get("text_field") or "").strip()
    if text_field:
        return _stringify_cell(row.get(text_field))

    messages = row.get("messages")
    if isinstance(messages, list) and messages:
        rendered: list[str] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = _stringify_cell(message.get("role")) or "user"
            content = _stringify_cell(message.get("content"))
            if content:
                rendered.append(f"<{role}>\n{content}")
        if rendered:
            return "\n\n".join(rendered)

    instruction = _stringify_cell(row.get("instruction"))
    output = _stringify_cell(row.get("output"))
    if instruction and output:
        input_text = _stringify_cell(row.get("input"))
        parts = [f"### Instructie\n{instruction}"]
        if input_text:
            parts.append(f"### Input\n{input_text}")
        parts.append(f"### Antwoord\n{output}")
        return "\n\n".join(parts)

    query = _stringify_cell(row.get("query"))
    answer = _stringify_cell(row.get("answer"))
    if query and answer:
        return f"### Vraag\n{query}\n\n### Antwoord\n{answer}"

    prompt = _stringify_cell(row.get("prompt"))
    completion = _stringify_cell(row.get("completion"))
    if prompt and completion:
        # Preserve a readable boundary after strip(); authors often put the space in prompt.
        return f"{prompt} {completion}"

    question = _stringify_cell(row.get("question"))
    response = _stringify_cell(row.get("response")) or answer
    if question and response:
        return f"### Vraag\n{question}\n\n### Antwoord\n{response}"

    problem_statement = _stringify_cell(row.get("problem_statement"))
    patch = _stringify_cell(row.get("patch"))
    if problem_statement and patch:
        parts = [f"### Probleem\n{problem_statement}"]
        pr_description = _stringify_cell(row.get("pr_description"))
        if pr_description:
            parts.append(f"### PR-context\n{pr_description}")
        parts.append(f"### Patch\n{patch}")
        test_patch = _stringify_cell(row.get("test_patch"))
        if test_patch:
            parts.append(f"### Testpatch\n{test_patch}")
        fail_to_pass = _stringify_cell(row.get("FAIL_TO_PASS"))
        pass_to_pass = _stringify_cell(row.get("PASS_TO_PASS"))
        if fail_to_pass:
            parts.append(f"### FAIL_TO_PASS\n{fail_to_pass}")
        if pass_to_pass:
            parts.append(f"### PASS_TO_PASS\n{pass_to_pass}")
        return "\n\n".join(parts)

    text = _stringify_cell(row.get("text"))
    if text:
        return text

    for value in row.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class TrainingWorkspace:
    """Filesystem-backed registry with no schema migration or core-runtime coupling."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.datasets_dir = self.root / "datasets"
        self.jobs_dir = self.root / "jobs"
        self.uploads_dir = self.root / "uploads"
        for path in (self.datasets_dir, self.jobs_dir, self.uploads_dir):
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_database(cls, database: Any) -> "TrainingWorkspace":
        db_path = Path(str(database.path)).expanduser().resolve()
        return cls(db_path.parent / "training")

    def capabilities(self) -> dict[str, Any]:
        packages: dict[str, dict[str, Any]] = {}
        for module_name, package_name in (
            ("torch", "torch"),
            ("transformers", "transformers"),
            ("datasets", "datasets"),
            ("peft", "peft"),
            ("accelerate", "accelerate"),
            ("bitsandbytes", "bitsandbytes"),
            ("pyarrow", "pyarrow"),
        ):
            available = importlib.util.find_spec(module_name) is not None
            version: str | None = None
            if available:
                try:
                    version = importlib.metadata.version(package_name)
                except importlib.metadata.PackageNotFoundError:
                    version = None
            packages[module_name] = {"available": available, "version": version}
        required = ("torch", "transformers", "datasets", "peft", "accelerate")
        return {
            "trainer_ready": all(packages[name]["available"] for name in required),
            "required_packages": list(required),
            "packages": packages,
            "workspace": str(self.root),
            "upload_limit_bytes": UPLOAD_LIMIT_BYTES,
            "supported_local_extensions": sorted(SUPPORTED_LOCAL_EXTENSIONS),
            "training_mode": "lora_adapter",
            "atme": {
                "planner_version": 1,
                "strategies": [
                    "auto",
                    "gpu_resident",
                    "gpu_resident_4bit",
                    "cpu_offload",
                    "ram_layer_streaming",
                    "nvme_layer_streaming",
                ],
                "streaming_architecture_v1": "llama_like",
                "streamed_resume_supported": False,
            },
            "note": "Training is opt-in; the normal HADES runtime does not import these ML packages.",
        }

    def _dataset_meta_path(self, dataset_id: str) -> Path:
        if not DATASET_RECORD_ID_RE.fullmatch(str(dataset_id or "")):
            raise KeyError(dataset_id)
        return self.datasets_dir / dataset_id / "dataset.json"

    def _job_path(self, job_id: str) -> Path:
        if not JOB_RECORD_ID_RE.fullmatch(str(job_id or "")):
            raise KeyError(job_id)
        return self.jobs_dir / job_id / "job.json"

    def hardware_snapshot(self) -> dict[str, Any]:
        from training.hardware_probe import collect_hardware_snapshot

        return collect_hardware_snapshot(storage_paths=[self.root]).to_public_dict()

    def inspect_model(self, base_model: str) -> dict[str, Any]:
        from training.model_inspector import inspect_model_reference

        return inspect_model_reference(base_model).to_public_dict()

    def create_plan(
        self,
        *,
        base_model: str,
        dataset_id: str | None = None,
        max_steps: int = 200,
        learning_rate: float = 2e-4,
        sequence_length: int = 1024,
        batch_size: int = 1,
        gradient_accumulation_steps: int = 8,
        lora_r: int = 16,
        lora_alpha: int = 32,
        lora_dropout: float = 0.05,
        memory_strategy: str = "auto",
        activation_checkpointing: str = "auto",
        host_memory_limit_bytes: int | None = None,
        vram_reserve_bytes: int | None = None,
        stream_buffer_count: int | str = "auto",
        experimental_streaming_allowed: bool = False,
        load_in_4bit: bool | None = None,
    ) -> dict[str, Any]:
        from training.execution_plan import MemoryStrategy, PlanRequest
        from training.planner import plan_training

        if dataset_id:
            self.get_dataset(dataset_id)
        request = PlanRequest(
            base_model=str(base_model or "").strip(),
            dataset_id=dataset_id,
            max_steps=max_steps,
            learning_rate=learning_rate,
            sequence_length=sequence_length,
            batch_size=batch_size,
            gradient_accumulation_steps=gradient_accumulation_steps,
            lora_r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            memory_strategy=MemoryStrategy(str(memory_strategy or "auto")),
            activation_checkpointing=activation_checkpointing,  # type: ignore[arg-type]
            host_memory_limit_bytes=host_memory_limit_bytes,
            vram_reserve_bytes=vram_reserve_bytes,
            stream_buffer_count=stream_buffer_count,  # type: ignore[arg-type]
            experimental_streaming_allowed=bool(experimental_streaming_allowed),
            load_in_4bit=load_in_4bit,
        )
        response = plan_training(request, storage_paths=[str(self.root)])
        return response.model_dump(mode="json")

    def latest_benchmark(self) -> dict[str, Any] | None:
        from training.benchmark import load_latest_benchmark

        profile = load_latest_benchmark(self.root)
        return profile.to_public_dict() if profile else None

    def run_calibration_benchmark(self, *, include_storage: bool = False, include_gpu: bool = True) -> dict[str, Any]:
        """Optional bounded calibration. Never runs a long silent benchmark."""

        import time

        from training.benchmark import BenchmarkProfile, save_benchmark
        from training.execution_plan import stable_hash
        from training.hardware_probe import collect_hardware_snapshot

        started = time.perf_counter()
        hardware = collect_hardware_snapshot(storage_paths=[self.root])
        notes: list[str] = []
        host_to_device = None
        pinned = None
        storage_read = None
        gpu_throughput = None
        allocation_headroom = None
        sync_overhead = None
        status = "completed_partial"

        # Storage sequential read micro-benchmark (bounded ~16 MiB).
        if include_storage and hardware.storage:
            probe_dir = self.root / "atme" / "benchmarks"
            probe_dir.mkdir(parents=True, exist_ok=True)
            probe_file = probe_dir / "seqread.bin"
            payload = os.urandom(1 * 1024 * 1024)
            with probe_file.open("wb") as handle:
                for _ in range(16):
                    handle.write(payload)
            t0 = time.perf_counter()
            read_bytes = 0
            with probe_file.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    read_bytes += len(chunk)
            elapsed = max(1e-6, time.perf_counter() - t0)
            storage_read = read_bytes / elapsed
            try:
                probe_file.unlink()
            except OSError:
                pass
            notes.append("storage sequential read measured over 16 MiB probe file")

        # GPU micro-benchmarks require torch+CUDA and stay optional.
        if include_gpu:
            try:
                import torch
            except ImportError:
                notes.append("torch unavailable; GPU benchmark skipped")
                status = "completed_partial"
            else:
                if not torch.cuda.is_available():
                    notes.append("CUDA unavailable; GPU benchmark skipped")
                    status = "completed_partial"
                else:
                    device = torch.device("cuda")
                    try:
                        src = torch.randn(8, 1024, 1024, device="cpu")
                        torch.cuda.synchronize()
                        t0 = time.perf_counter()
                        dst = src.to(device, non_blocking=False)
                        torch.cuda.synchronize()
                        host_to_device = src.numel() * src.element_size() / max(1e-6, time.perf_counter() - t0)
                        try:
                            pinned_src = src.pin_memory()
                            torch.cuda.synchronize()
                            t1 = time.perf_counter()
                            _ = pinned_src.to(device, non_blocking=True)
                            torch.cuda.synchronize()
                            pinned = pinned_src.numel() * pinned_src.element_size() / max(1e-6, time.perf_counter() - t1)
                        except RuntimeError as exc:
                            notes.append(f"pinned transfer unavailable: {exc}")
                        a = torch.randn(1024, 1024, device=device)
                        b = torch.randn(1024, 1024, device=device)
                        torch.cuda.synchronize()
                        t2 = time.perf_counter()
                        for _ in range(20):
                            c = a @ b
                        torch.cuda.synchronize()
                        gpu_throughput = 20 / max(1e-6, time.perf_counter() - t2)
                        free, total = torch.cuda.mem_get_info()
                        allocation_headroom = int(free)
                        t3 = time.perf_counter()
                        torch.cuda.synchronize()
                        sync_overhead = (time.perf_counter() - t3) * 1000.0
                        status = "completed"
                        del dst, a, b, c
                        torch.cuda.empty_cache()
                    except RuntimeError as exc:
                        notes.append(f"GPU benchmark failed: {exc}")
                        status = "failed"

        duration_ms = int((time.perf_counter() - started) * 1000)
        now = utc_now()
        profile = BenchmarkProfile(
            id=f"bench_{stable_hash({'hw': hardware.profile_hash, 'ts': now})[:16]}",
            created_at=now,
            hardware_profile_hash=hardware.profile_hash,
            driver_version=str(hardware.gpu.driver_version.value) if hardware.gpu.driver_version.value else None,
            platform_system=str(hardware.host.platform_system.value) if hardware.host.platform_system.value else None,
            cancelled=False,
            duration_ms=duration_ms,
            host_to_device_bytes_per_sec=host_to_device,
            pinned_host_to_device_bytes_per_sec=pinned,
            storage_sequential_read_bytes_per_sec=storage_read,
            gpu_microbenchmark_throughput=gpu_throughput,
            allocation_headroom_bytes=allocation_headroom,
            sync_overhead_ms=sync_overhead,
            notes=notes,
            status=status,
            provenance={"kind": "calibration", "bounded": "true"},
        )
        return save_benchmark(self.root, profile).to_public_dict()

    def job_telemetry(self, job_id: str) -> dict[str, Any]:
        from training.telemetry import sanitize_telemetry_payload

        job = self.get_job(job_id)
        path = self._job_path(job_id).parent / "telemetry.json"
        samples: list[dict[str, Any]] = []
        if path.is_file():
            try:
                raw = read_json(path)
                if isinstance(raw.get("samples"), list):
                    samples = [sanitize_telemetry_payload(item) for item in raw["samples"] if isinstance(item, dict)]
            except (OSError, ValueError, json.JSONDecodeError):
                samples = []
        plan = job.get("resolved_execution_plan")
        return sanitize_telemetry_payload(
            {
                "job_id": job_id,
                "status": job.get("status"),
                "strategy": (plan or {}).get("strategy") if isinstance(plan, dict) else None,
                "runtime_peak_vram_bytes": job.get("runtime_peak_vram_bytes"),
                "runtime_peak_ram_bytes": job.get("runtime_peak_ram_bytes"),
                "runtime_bytes_host_to_device": job.get("runtime_bytes_host_to_device"),
                "observed_bottleneck": job.get("observed_bottleneck"),
                "samples": samples[-120:],
            }
        )

    def list_datasets(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not self.datasets_dir.exists():
            return items
        for child in self.datasets_dir.iterdir():
            meta = child / "dataset.json"
            if not meta.is_file():
                continue
            try:
                item = read_json(meta)
                if DATASET_RECORD_ID_RE.fullmatch(str(item.get("id") or "")):
                    items.append(item)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return items

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        path = self._dataset_meta_path(dataset_id)
        if not path.is_file():
            raise KeyError(dataset_id)
        return read_json(path)

    def _iter_local_rows(self, path: Path, *, limit: int) -> Iterator[dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix in {".jsonl", ".ndjson"}:
            with path.open("r", encoding="utf-8-sig") as handle:
                yielded = 0
                for line_no, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Ongeldige JSONL op regel {line_no}: {exc.msg}.") from exc
                    if not isinstance(value, dict):
                        raise ValueError(f"JSONL-regel {line_no} is geen object.")
                    yield value
                    yielded += 1
                    if yielded >= limit:
                        return
            return

        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=delimiter)
                if not reader.fieldnames:
                    raise ValueError("CSV/TSV heeft geen kolomkoppen.")
                for index, row in enumerate(reader):
                    yield dict(row)
                    if index + 1 >= limit:
                        return
            return

        if suffix == ".json":
            if path.stat().st_size > JSON_PREVIEW_LIMIT_BYTES:
                raise ValueError("Grote JSON-array wordt niet in geheugen geladen. Gebruik JSONL of Parquet voor grote datasets.")
            with path.open("r", encoding="utf-8-sig") as handle:
                value = json.load(handle)
            if isinstance(value, dict):
                rows = value.get("data") or value.get("rows")
            else:
                rows = value
            if not isinstance(rows, list):
                raise ValueError("JSON-dataset moet een array zijn, of een object met 'data'/'rows'.")
            for row in rows[:limit]:
                if not isinstance(row, dict):
                    raise ValueError("JSON-dataset bevat een record dat geen object is.")
                yield row
            return

        if suffix == ".parquet":
            if importlib.util.find_spec("pyarrow") is None:
                return
            import pyarrow.parquet as pq  # type: ignore[import-not-found]

            table = pq.read_table(path, columns=None).slice(0, limit)
            for row in table.to_pylist():
                if isinstance(row, dict):
                    yield row
            return

        raise ValueError(f"Niet-ondersteund datasetformaat: {suffix or '(geen extensie)'}.")

    def inspect_local(self, source_path: str | Path, *, preview_rows: int = 20) -> dict[str, Any]:
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(str(path))
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_LOCAL_EXTENSIONS:
            raise ValueError(f"Ondersteund: {', '.join(sorted(SUPPORTED_LOCAL_EXTENSIONS))}.")
        preview_rows = max(1, min(int(preview_rows), 50))
        rows = list(self._iter_local_rows(path, limit=preview_rows))
        columns: list[str] = []
        for row in rows:
            for key in row:
                key_text = str(key)
                if key_text not in columns:
                    columns.append(key_text)
        return {
            "path": str(path),
            "format": suffix.lstrip("."),
            "size_bytes": path.stat().st_size,
            "columns": columns[:200],
            "preview": rows,
            "preview_count": len(rows),
            "preview_available": bool(rows) or suffix != ".parquet",
        }

    def register_local(
        self,
        source_path: str | Path,
        *,
        name: str = "",
        text_field: str = "",
        managed_upload: bool = False,
    ) -> dict[str, Any]:
        inspected = self.inspect_local(source_path)
        text_field = text_field.strip()
        if text_field and inspected["columns"] and text_field not in set(inspected["columns"]):
            raise ValueError("De gekozen tekstkolom komt niet voor in de dataset-preview.")
        dataset_id = f"ds_{secrets.token_hex(8)}"
        now = utc_now()
        record = {
            "id": dataset_id,
            "name": _clean_name(name, fallback=Path(inspected["path"]).stem),
            "source_type": "upload" if managed_upload else "local",
            "status": "ready",
            "format": inspected["format"],
            "path": inspected["path"],
            "size_bytes": inspected["size_bytes"],
            "row_count": None,
            "columns": inspected["columns"],
            "preview": inspected["preview"],
            "mapping": {"text_field": text_field} if text_field else {},
            "source": {"managed_upload": bool(managed_upload)},
            "created_at": now,
            "updated_at": now,
        }
        _atomic_write_json(self._dataset_meta_path(dataset_id), record)
        return record

    def prepare_upload_path(self, filename: str) -> Path:
        safe_name = Path(str(filename or "dataset.jsonl")).name
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_LOCAL_EXTENSIONS:
            raise ValueError(f"Ondersteund: {', '.join(sorted(SUPPORTED_LOCAL_EXTENSIONS))}.")
        upload_id = f"upload_{secrets.token_hex(8)}"
        target = self.uploads_dir / upload_id / safe_name
        target.parent.mkdir(parents=True, exist_ok=False)
        return target

    async def inspect_huggingface(
        self,
        dataset_id: str,
        *,
        token: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        dataset_id = _safe_dataset_id(dataset_id)
        headers = {"Authorization": f"Bearer {token.strip()}"} if token and token.strip() else {}
        timeout = httpx.Timeout(max(5.0, min(float(timeout_seconds), 120.0)))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(f"{HF_DATASET_SERVER}/splits", params={"dataset": dataset_id}, headers=headers)
            if response.status_code >= 400:
                raise ValueError(f"Hugging Face gaf HTTP {response.status_code} voor deze dataset.")
            payload = response.json()
        splits = payload.get("splits") if isinstance(payload, dict) else None
        if not isinstance(splits, list):
            raise ValueError("Hugging Face gaf geen bruikbare splitlijst terug.")
        normalized = []
        for item in splits:
            if not isinstance(item, dict):
                continue
            config = str(item.get("config") or "")
            split = str(item.get("split") or "")
            if config and split:
                normalized.append({"config": config, "split": split})
        return {"dataset_id": dataset_id, "splits": normalized}

    async def preview_huggingface(
        self,
        dataset_id: str,
        *,
        config: str,
        split: str,
        token: str | None = None,
        rows: int = 20,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        dataset_id = _safe_dataset_id(dataset_id)
        config = _safe_split_component(config, "config")
        split = _safe_split_component(split, "split")
        rows = max(1, min(int(rows), 100))
        headers = {"Authorization": f"Bearer {token.strip()}"} if token and token.strip() else {}
        timeout = httpx.Timeout(max(5.0, min(float(timeout_seconds), 120.0)))
        params = {"dataset": dataset_id, "config": config, "split": split, "offset": 0, "length": rows}
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(f"{HF_DATASET_SERVER}/rows", params=params, headers=headers)
            if response.status_code >= 400:
                raise ValueError(f"Hugging Face preview gaf HTTP {response.status_code}.")
            payload = response.json()
        raw_rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(raw_rows, list):
            raise ValueError("Hugging Face gaf geen bruikbare rijen terug.")
        preview: list[dict[str, Any]] = []
        for item in raw_rows:
            row = item.get("row") if isinstance(item, dict) else None
            if isinstance(row, dict):
                preview.append(row)
        columns: list[str] = []
        for row in preview:
            for key in row:
                key_text = str(key)
                if key_text not in columns:
                    columns.append(key_text)
        return {
            "dataset_id": dataset_id,
            "config": config,
            "split": split,
            "columns": columns[:200],
            "preview": preview,
            "row_count": payload.get("num_rows_total") if isinstance(payload, dict) else None,
            "partial": bool(payload.get("partial")) if isinstance(payload, dict) else False,
        }

    async def register_huggingface(
        self,
        dataset_id: str,
        *,
        config: str,
        split: str,
        name: str = "",
        text_field: str = "",
        token: str | None = None,
    ) -> dict[str, Any]:
        inspected = await self.preview_huggingface(
            dataset_id,
            config=config,
            split=split,
            token=token,
            rows=20,
        )
        text_field = text_field.strip()
        if text_field and inspected["columns"] and text_field not in set(inspected["columns"]):
            raise ValueError("De gekozen tekstkolom komt niet voor in de dataset-preview.")
        item_id = f"ds_{secrets.token_hex(8)}"
        now = utc_now()
        record = {
            "id": item_id,
            "name": _clean_name(name, fallback=dataset_id),
            "source_type": "huggingface",
            "status": "ready",
            "format": "huggingface",
            "path": None,
            "size_bytes": None,
            "row_count": inspected.get("row_count"),
            "columns": inspected["columns"],
            "preview": inspected["preview"],
            "mapping": {"text_field": text_field} if text_field else {},
            "source": {
                "dataset_id": _safe_dataset_id(dataset_id),
                "config": _safe_split_component(config, "config"),
                "split": _safe_split_component(split, "split"),
            },
            "created_at": now,
            "updated_at": now,
        }
        _atomic_write_json(self._dataset_meta_path(item_id), record)
        return record

    def update_mapping(self, dataset_id: str, *, text_field: str = "") -> dict[str, Any]:
        record = self.get_dataset(dataset_id)
        if text_field and text_field not in set(record.get("columns") or []):
            raise ValueError("De gekozen tekstkolom komt niet voor in de dataset-preview.")
        record["mapping"] = {"text_field": text_field.strip()} if text_field.strip() else {}
        record["updated_at"] = utc_now()
        _atomic_write_json(self._dataset_meta_path(dataset_id), record)
        return record

    def delete_dataset(self, dataset_id: str) -> None:
        record = self.get_dataset(dataset_id)
        dataset_dir = self._dataset_meta_path(dataset_id).parent
        for job in self.list_jobs():
            if job.get("dataset_id") == dataset_id and job.get("status") in {
                "queued",
                "planning",
                "profiling",
                "waiting_for_model",
                "allocating",
                "warming_up",
                "running",
                "checkpointing",
                "cancelling",
            }:
                raise ValueError("Dataset hoort bij een actieve trainingstaak en kan nu niet worden verwijderd.")
        if record.get("source_type") == "upload":
            path = Path(str(record.get("path") or ""))
            try:
                if path.is_file() and self.uploads_dir in path.parents:
                    path.unlink()
                    path.parent.rmdir()
            except OSError as exc:
                raise ValueError(f"Beheerde datasetdata verwijderen mislukt: {exc}") from exc
        try:
            self._dataset_meta_path(dataset_id).unlink()
            dataset_dir.rmdir()
        except OSError as exc:
            raise ValueError(f"Datasetmetadata verwijderen mislukt: {exc}") from exc

    def list_jobs(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not self.jobs_dir.exists():
            return items
        for child in self.jobs_dir.iterdir():
            path = child / "job.json"
            if not path.is_file():
                continue
            try:
                item = read_json(path)
                if JOB_RECORD_ID_RE.fullmatch(str(item.get("id") or "")):
                    items.append(item)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return items

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        if not path.is_file():
            raise KeyError(job_id)
        job = read_json(path)
        if job.get("status") in {"running", "cancelling", "planning", "waiting_for_model", "allocating", "warming_up", "checkpointing"}:
            pid = int(job.get("pid") or 0)
            if not _process_is_alive(pid):
                job = write_job_state(
                    path,
                    {
                        "status": "interrupted",
                        "error": "Training worker is niet meer actief; procesliveness kon niet worden bevestigd.",
                        "finished_at": utc_now(),
                    },
                )
        return job

    def create_job(
        self,
        *,
        dataset_id: str,
        base_model: str,
        max_steps: int = 200,
        learning_rate: float = 2e-4,
        sequence_length: int = 1024,
        batch_size: int = 1,
        gradient_accumulation_steps: int = 8,
        lora_r: int = 16,
        lora_alpha: int = 32,
        lora_dropout: float = 0.05,
        load_in_4bit: bool = False,
        memory_strategy: str = "auto",
        activation_checkpointing: str = "auto",
        host_memory_limit_bytes: int | None = None,
        vram_reserve_bytes: int | None = None,
        stream_buffer_count: int | str = "auto",
        experimental_streaming_allowed: bool = False,
        token: str | None = None,
    ) -> dict[str, Any]:
        from training.execution_plan import MemoryStrategy, PlanRequest
        from training.failure_codes import TrainingFailureCode
        from training.planner import plan_to_job_fields, plan_training

        dataset = self.get_dataset(dataset_id)
        caps = self.capabilities()
        if not caps["trainer_ready"]:
            missing = [name for name in caps["required_packages"] if not caps["packages"][name]["available"]]
            raise RuntimeError(f"Trainingsdependencies ontbreken: {', '.join(missing)}.")
        base_model = str(base_model or "").strip()
        if not base_model or len(base_model) > 1000 or any(ch in base_model for ch in "\r\n\0"):
            raise ValueError("Ongeldig basismodel-pad of Hugging Face model-ID.")

        # Legacy checkbox maps into strategy when caller still sends load_in_4bit without strategy.
        strategy_value = str(memory_strategy or "auto").strip() or "auto"
        try:
            strategy = MemoryStrategy(strategy_value)
        except ValueError as exc:
            raise ValueError(f"Ongeldige memory_strategy: {strategy_value}") from exc

        load_in_4bit_hint: bool | None = bool(load_in_4bit)
        if strategy == MemoryStrategy.GPU_RESIDENT_4BIT:
            load_in_4bit_hint = True
        elif strategy != MemoryStrategy.AUTO and strategy != MemoryStrategy.GPU_RESIDENT_4BIT:
            load_in_4bit_hint = False

        if (strategy == MemoryStrategy.GPU_RESIDENT_4BIT or load_in_4bit_hint is True) and not caps["packages"]["bitsandbytes"]["available"]:
            if strategy == MemoryStrategy.GPU_RESIDENT_4BIT or (strategy == MemoryStrategy.AUTO and load_in_4bit):
                raise RuntimeError("4-bit training vereist de optionele package 'bitsandbytes'.")

        values = {
            "max_steps": max(1, min(int(max_steps), 1_000_000)),
            "learning_rate": max(1e-8, min(float(learning_rate), 1.0)),
            "sequence_length": max(64, min(int(sequence_length), 131_072)),
            "batch_size": max(1, min(int(batch_size), 128)),
            "gradient_accumulation_steps": max(1, min(int(gradient_accumulation_steps), 4096)),
            "lora_r": max(1, min(int(lora_r), 1024)),
            "lora_alpha": max(1, min(int(lora_alpha), 8192)),
            "lora_dropout": max(0.0, min(float(lora_dropout), 0.95)),
            "load_in_4bit": bool(load_in_4bit_hint) if load_in_4bit_hint is not None else bool(load_in_4bit),
            "memory_strategy": strategy.value,
            "activation_checkpointing": str(activation_checkpointing or "auto"),
            "host_memory_limit_bytes": host_memory_limit_bytes,
            "vram_reserve_bytes": vram_reserve_bytes,
            "stream_buffer_count": stream_buffer_count,
            "experimental_streaming_allowed": bool(experimental_streaming_allowed),
        }

        plan_request = PlanRequest(
            base_model=base_model,
            dataset_id=dataset_id,
            max_steps=values["max_steps"],
            learning_rate=values["learning_rate"],
            sequence_length=values["sequence_length"],
            batch_size=values["batch_size"],
            gradient_accumulation_steps=values["gradient_accumulation_steps"],
            lora_r=values["lora_r"],
            lora_alpha=values["lora_alpha"],
            lora_dropout=values["lora_dropout"],
            memory_strategy=strategy,
            activation_checkpointing=values["activation_checkpointing"],  # type: ignore[arg-type]
            host_memory_limit_bytes=host_memory_limit_bytes,
            vram_reserve_bytes=vram_reserve_bytes,
            stream_buffer_count=stream_buffer_count,  # type: ignore[arg-type]
            experimental_streaming_allowed=bool(experimental_streaming_allowed),
            load_in_4bit=load_in_4bit_hint,
        )
        plan_response = plan_training(plan_request, storage_paths=[str(self.root)])
        selected = plan_response.selected
        if selected is None or not selected.feasible:
            reason = None
            code = TrainingFailureCode.STRATEGY_REJECTED
            if selected is not None:
                reason = selected.rejection_reason
                code = selected.failure_code or code
            elif plan_response.candidates:
                reason = plan_response.candidates[0].rejection_reason
                code = plan_response.candidates[0].failure_code or code
            raise RuntimeError(f"ATME-plan afgewezen ({code}): {reason or 'geen haalbare strategie'}")

        # Keep legacy parameter synchronized with resolved strategy.
        values["load_in_4bit"] = selected.strategy == MemoryStrategy.GPU_RESIDENT_4BIT
        values["memory_strategy"] = selected.strategy.value
        values["resolved_buffer_count"] = selected.buffer_count

        job_id = f"train_{secrets.token_hex(8)}"
        job_dir = self.jobs_dir / job_id
        output_dir = job_dir / "adapter"
        job_dir.mkdir(parents=True, exist_ok=False)
        now = utc_now()
        job = {
            "id": job_id,
            "dataset_id": dataset_id,
            "dataset_name": dataset.get("name"),
            "base_model": base_model,
            "status": "planning",
            "progress": 0.0,
            "step": 0,
            "max_steps": values["max_steps"],
            "parameters": values,
            "output_dir": str(output_dir),
            "log_path": str(job_dir / "train.log"),
            "error": None,
            "failure_code": None,
            "pid": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "observed_bottleneck": None,
            **plan_to_job_fields(selected, plan_request),
        }
        job_path = job_dir / "job.json"
        _atomic_write_json(job_path, job)

        worker_path = Path(__file__).resolve().parent / "training_worker.py"
        env = os.environ.copy()
        if token and token.strip():
            env["HF_TOKEN"] = token.strip()
        log_handle = (job_dir / "train.log").open("ab", buffering=0)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                [sys.executable, str(worker_path), "--job", str(job_path)],
                cwd=str(worker_path.parent),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
            )
        except Exception as exc:
            log_handle.close()
            write_job_state(
                job_path,
                {
                    "status": "failed",
                    "error": f"Trainer starten mislukt: {exc}",
                    "failure_code": TrainingFailureCode.WORKER_CRASH,
                    "finished_at": utc_now(),
                },
            )
            raise
        finally:
            try:
                log_handle.close()
            except OSError:
                pass
        try:
            return write_job_state(
                job_path,
                {"status": "running", "pid": process.pid, "started_at": utc_now()},
            )
        except Exception:
            try:
                process.terminate()
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except (OSError, subprocess.SubprocessError):
                    pass
            raise

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        active = {
            "queued",
            "planning",
            "profiling",
            "waiting_for_model",
            "allocating",
            "warming_up",
            "running",
            "checkpointing",
            "cancelling",
        }
        if job.get("status") not in active:
            return job
        cancel_path = self._job_path(job_id).parent / "cancel.requested"
        cancel_path.write_text("cancel\n", encoding="utf-8")
        return write_job_state(self._job_path(job_id), {"status": "cancelling"})

    def tail_log(self, job_id: str, *, max_bytes: int = 64_000) -> str:
        job = self.get_job(job_id)
        path = Path(str(job.get("log_path") or ""))
        if not path.is_file():
            return ""
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
            data = handle.read(max_bytes)
        return data.decode("utf-8", errors="replace")
