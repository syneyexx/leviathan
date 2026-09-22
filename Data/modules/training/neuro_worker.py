"""Neuro recipe trainer backends — EXTERNAL-FIRST ephemeral worker path.

Control plane (TrainingRecipeRegistry) stays in Core. When
LEVIATHAN_NEURO_TRAINING_REAL_WORKER is enabled, recipe execution runs in an
ephemeral subprocess so heavy/crashable work cannot take down Core.

No parallel training database — metrics return to the registry only.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .recipes import FixtureRecipeTrainer, TrainingRecipe


@dataclass
class EphemeralRecipeWorkerTrainer:
    """Spawn a short-lived subprocess to execute a recipe step.

    Uses FixtureRecipeTrainer semantics inside the worker when ML deps are absent.
    Reports honest metrics or FAILED — never fabricates COMPLETED with empty metrics.
    """

    backend_id: str = "ephemeral_recipe_worker"
    python_executable: str | None = None
    timeout_seconds: float = 60.0

    def available(self) -> bool:
        return True

    def execute(
        self,
        recipe: TrainingRecipe,
        *,
        samples: Sequence[Mapping[str, Any]],
        config: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        python = self.python_executable or sys.executable
        payload = {
            "recipe": recipe.public_dict(),
            "samples": [dict(s) for s in samples],
            "config": dict(config or {}),
        }
        with tempfile.TemporaryDirectory(prefix="leviathan-neuro-recipe-") as tmp:
            work = Path(tmp)
            in_path = work / "input.json"
            out_path = work / "output.json"
            in_path.write_text(json.dumps(payload), encoding="utf-8")
            # Inline worker module invocation — argv only, no shell.
            code = (
                "import json,sys\n"
                "from pathlib import Path\n"
                "from Data.modules.training.recipes import FixtureRecipeTrainer, TrainingRecipe\n"
                f"inp=json.loads(Path({str(in_path)!r}).read_text(encoding='utf-8'))\n"
                "r=inp['recipe']\n"
                "recipe=TrainingRecipe(\n"
                " recipe_id=r['recipe_id'], name=r['name'], objective=r['objective'],\n"
                " loss=r['loss'], formulation=r['formulation'],\n"
                " data_sources=tuple(r.get('data_sources') or ()),\n"
                " requires_verification=bool(r.get('requires_verification', True)),\n"
                " freezes_base_model=bool(r.get('freezes_base_model', True)),\n"
                " metadata=dict(r.get('metadata') or {}),\n"
                ")\n"
                "metrics=dict(FixtureRecipeTrainer(backend_id='ephemeral_worker_inner')"
                ".execute(recipe, samples=inp.get('samples') or [], config=inp.get('config')))\n"
                "metrics['worker']='ephemeral_subprocess'\n"
                "metrics['truth']=dict(metrics.get('truth') or {})\n"
                "metrics['truth']['external_worker_execution']=True\n"
                "metrics['truth']['fixture_metrics_are_not_gpu_training']=True\n"
                f"Path({str(out_path)!r}).write_text(json.dumps(metrics), encoding='utf-8')\n"
            )
            try:
                completed = subprocess.run(  # noqa: S603 — argv list, shell=False
                    [python, "-c", code],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    shell=False,
                    cwd=str(Path(__file__).resolve().parents[3]),
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"neuro recipe worker timed out after {self.timeout_seconds}s") from exc
            if completed.returncode != 0:
                err = (completed.stderr or completed.stdout or "worker failed").strip()
                raise RuntimeError(f"neuro recipe worker failed: {err[:500]}")
            if not out_path.exists():
                raise RuntimeError("neuro recipe worker produced no metrics file")
            metrics = json.loads(out_path.read_text(encoding="utf-8"))
            if not isinstance(metrics, dict) or not metrics:
                raise RuntimeError("neuro recipe worker returned empty metrics — refusing fabricated COMPLETED")
            metrics.setdefault("worker", "ephemeral_subprocess")
            truth = dict(metrics.get("truth") or {})
            truth["external_worker_execution"] = True
            metrics["truth"] = truth
            return metrics


def build_neuro_recipe_trainer(*, real_worker: bool = False) -> FixtureRecipeTrainer | EphemeralRecipeWorkerTrainer:
    """Select in-process fixture trainer or EXTERNAL-FIRST ephemeral worker."""
    if real_worker:
        return EphemeralRecipeWorkerTrainer()
    return FixtureRecipeTrainer()
