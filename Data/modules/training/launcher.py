"""Launch training workers as subprocesses using argv arrays only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.secrets import redact_secrets

from .config import TrainingConfig


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
        child_env = os.environ.copy()
        if env:
            child_env.update(env)
        # Never pass secrets via argv; env keys that look like tokens stay in env only.
        log_handle = log_path.open("a", encoding="utf-8")
        return subprocess.Popen(  # noqa: S603 — argv list, shell=False
            argv,
            cwd=str(cwd) if cwd else None,
            env=child_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            shell=False,
        )
