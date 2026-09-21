"""Checkpoint helpers for streamed training (honesty-first).

End-to-end streamed resume is NOT advertised until proven. These helpers only
persist adapter checkpoints through the normal PEFT/Trainer save path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def save_adapter_checkpoint(model: Any, output_dir: str | Path) -> Path:
    path = Path(output_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    if hasattr(model, "save_pretrained"):
        model.save_pretrained(str(path))
        return path
    raise RuntimeError("Model does not support save_pretrained for adapter persistence")


def streamed_resume_supported() -> bool:
    """Explicit capability flag — false until restore is end-to-end proven."""

    return False
