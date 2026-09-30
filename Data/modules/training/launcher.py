"""Launch training workers as subprocesses using argv arrays only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.secrets import redact_secrets

from .config import TrainingConfig
from .env_policy import build_trainer_child_env


def _merge_env(
    env: dict[str, str] | None,
    *,
    cuda_visible_devices: str | None,
    extra_env: dict[str, str] | None,
) -> dict[str, str] | None:
    merged: dict[str, str] = {}
    if env:
        merged.update(env)
    if extra_env:
        merged.update(extra_env)
    if cuda_visible_devices is not None:
        merged["CUDA_VISIBLE_DEVICES"] = str(cuda_visible_devices)
    return merged or None


class TrainingLauncher:
    def __init__(self, *, python_executable: str | None = None) -> None:
        self.python_executable = python_executable or sys.executable

    def build_argv(
        self,
        *,
        job_id: str,
        db_path: Path,
        config_path: Path,
        output_dir: Path,
        log_path: Path,
        events_path: Path,
    ) -> list[str]:
        return [
            self.python_executable,
            "-m",
            "Data.modules.training.worker.entry",
            "--job-id",
            job_id,
            "--db-path",
            str(db_path),
            "--config-path",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--log-path",
            str(log_path),
            "--events-path",
            str(events_path),
        ]

    def write_config(self, path: Path, config: TrainingConfig) -> Path:
        ensure_dir(path.parent)
        atomic_write_text(path, redact_secrets(json.dumps(config.public_dict(), indent=2)))
        return path

    def build_child_env(
        self,
        *,
        env: dict[str, str] | None = None,
        cuda_visible_devices: str | None = None,
        extra_env: dict[str, str] | None = None,
        base: dict[str, str] | None = None,
    ) -> dict[str, str]:
        return build_trainer_child_env(
            _merge_env(env, cuda_visible_devices=cuda_visible_devices, extra_env=extra_env),
            base=base,
        )

    def spawn(
        self,
        *,
        job_id: str,
        db_path: Path,
        config: TrainingConfig,
        output_dir: Path,
        log_path: Path,
        events_path: Path,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        cuda_visible_devices: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.Popen[Any]:
        ensure_dir(output_dir)
        ensure_dir(log_path.parent)
        ensure_dir(events_path.parent)
        config_path = output_dir / "config.json"
        self.write_config(config_path, config)
        argv = self.build_argv(
            job_id=job_id,
            db_path=db_path,
            config_path=config_path,
            output_dir=output_dir,
            log_path=log_path,
            events_path=events_path,
        )
        # Scrubbed env — never copy full host/API secrets into trainer.
        child_env = build_trainer_child_env(
            _merge_env(env, cuda_visible_devices=cuda_visible_devices, extra_env=extra_env)
        )
        # Log sink is a file handle so a full pipe cannot deadlock the child.
        log_handle = log_path.open("a", encoding="utf-8")
        popen_kwargs: dict[str, Any] = {
            "cwd": str(cwd) if cwd else None,
            "env": child_env,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "shell": False,
        }
        # New process group on POSIX so supervisor can kill the full tree.
        if sys.platform != "win32":
            popen_kwargs["start_new_session"] = True
        return subprocess.Popen(argv, **popen_kwargs)  # noqa: S603 — argv list, shell=False
