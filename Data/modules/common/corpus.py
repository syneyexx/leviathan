"""Resolve durable corpus roots for datasets / training / research."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from Data.backend.config import BACKEND_ROOT, PROJECT_ROOT, Settings
from Data.modules.common.atomic import ensure_dir


@dataclass(frozen=True)
class CorpusLayout:
    root: Path
    datasets: Path
    datasets_raw: Path
    datasets_materialized: Path
    datasets_processed: Path
    datasets_exports: Path
    datasets_manifests: Path
    training: Path
    training_jobs: Path
    training_runs: Path
    training_checkpoints: Path
    training_adapters: Path
    training_exports: Path
    training_logs: Path
    research: Path
    research_projects: Path
    research_sources: Path
    research_snapshots: Path
    research_reports: Path
    research_exports: Path
    models_artifacts: Path
    models_cache: Path
    hf_cache: Path

    def ensure(self) -> "CorpusLayout":
        for path in (
            self.root,
            self.datasets_raw,
            self.datasets_materialized,
            self.datasets_processed,
            self.datasets_exports,
            self.datasets_manifests,
            self.training_jobs,
            self.training_runs,
            self.training_checkpoints,
            self.training_adapters,
            self.training_exports,
            self.training_logs,
            self.research_projects,
            self.research_sources,
            self.research_snapshots,
            self.research_reports,
            self.research_exports,
            self.models_artifacts,
            self.models_cache,
            self.hf_cache,
        ):
            ensure_dir(path)
        return self


def _writable_dir(path: Path) -> bool:
    try:
        ensure_dir(path)
        probe = path / ".leviathan_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def resolve_corpus_root(settings: Settings) -> Path:
    """Pick a writable corpus root without inventing remote storage."""
    import os

    override = (settings.research_integration.corpus_root or "").strip()
    if not override:
        override = (os.getenv("LEVIATHAN_CORPUS_ROOT") or "").strip()
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if _writable_dir(path):
            return path.resolve()

    data_root = Path(settings.knowledge.data_root)
    # Prefer operator bulk root when it exists / is creatable.
    candidate = data_root / "leviathan"
    if _writable_dir(candidate):
        return candidate.resolve()

    fallback = BACKEND_ROOT / "data" / "corpora"
    ensure_dir(fallback)
    return fallback.resolve()


def build_corpus_layout(settings: Settings) -> CorpusLayout:
    root = resolve_corpus_root(settings)
    layout = CorpusLayout(
        root=root,
        datasets=root / "datasets",
        datasets_raw=root / "datasets" / "raw",
        datasets_materialized=root / "datasets" / "materialized",
        datasets_processed=root / "datasets" / "processed",
        datasets_exports=root / "datasets" / "exports",
        datasets_manifests=root / "datasets" / "manifests",
        training=root / "training",
        training_jobs=root / "training" / "jobs",
        training_runs=root / "training" / "runs",
        training_checkpoints=root / "training" / "checkpoints",
        training_adapters=root / "training" / "adapters",
        training_exports=root / "training" / "exports",
        training_logs=root / "training" / "logs",
        research=root / "research",
        research_projects=root / "research" / "projects",
        research_sources=root / "research" / "sources",
        research_snapshots=root / "research" / "snapshots",
        research_reports=root / "research" / "reports",
        research_exports=root / "research" / "exports",
        models_artifacts=root / "models" / "artifacts",
        models_cache=root / "models" / "cache",
        hf_cache=root / "hf_cache",
    )
    return layout.ensure()
