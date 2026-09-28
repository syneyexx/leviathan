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
        child_env = build_trainer_child_env(env)
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
