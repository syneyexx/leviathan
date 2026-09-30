"""Resolve ``base_model_ref`` to local HF weights — trainers load with local_files_only."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_GGUF_TOKEN = re.compile(r"(^|[-_./\\])gguf($|[-_./\\])", re.IGNORECASE)
_WEIGHT_PATTERNS = ("*.safetensors", "*.bin", "*.pt", "*.pth")


def is_gguf_ref(ref: str | None) -> bool:
    text = (ref or "").strip()
    if not text:
        return False
    if text.lower().endswith(".gguf"):
        return True
    if _GGUF_TOKEN.search(text):
        return True
    path = Path(text).expanduser()
    try:
        if path.is_dir():
            has_gguf = any(path.glob("*.gguf"))
            has_hf = (path / "config.json").exists()
            return has_gguf and not has_hf
    except OSError:
        return False
    return False


@dataclass(frozen=True)
class ModelSource:
    ref: str
    kind: str  # local_dir | hf_cache | missing | gguf
    path: str | None = None
    has_config: bool = False
    has_weights: bool = False
    model_config: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.kind in {"local_dir", "hf_cache"} and self.has_config

    def public_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "kind": self.kind,
            "path": self.path,
            "hasConfig": self.has_config,
            "hasWeights": self.has_weights,
            "available": self.available,
            "modelType": self.model_config.get("model_type"),
            "notes": list(self.notes),
        }


def _hf_hub_cache_dirs() -> list[Path]:
    dirs: list[Path] = []
    for key in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        value = os.environ.get(key)
        if value:
            dirs.append(Path(value).expanduser())
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        dirs.append(Path(hf_home).expanduser() / "hub")
    dirs.append(Path.home() / ".cache" / "huggingface" / "hub")
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _has_weights(path: Path) -> bool:
    try:
        return any(any(path.glob(pattern)) for pattern in _WEIGHT_PATTERNS)
    except OSError:
        return False


def _read_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads((path / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_in_hf_cache(repo_id: str, revision: str | None) -> Path | None:
    if "/" not in repo_id or repo_id.startswith(("/", ".", "~")):
        return None
    folder = "models--" + repo_id.replace("/", "--")
    for cache in _hf_hub_cache_dirs():
        root = cache / folder
        snapshots = root / "snapshots"
        if not snapshots.is_dir():
            continue
        rev = revision or "main"
        ref_file = root / "refs" / rev
        candidates: list[Path] = []
        if ref_file.is_file():
            try:
                candidates.append(snapshots / ref_file.read_text(encoding="utf-8").strip())
            except OSError:
                pass
        if revision:
            candidates.append(snapshots / revision)
        else:
            try:
                candidates.extend(sorted(snapshots.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True))
            except OSError:
                pass
        for snap in candidates:
            if (snap / "config.json").exists():
                return snap
    return None


def resolve_model_source(ref: str | None, *, revision: str | None = None) -> ModelSource:
    text = (ref or "").strip()
    if is_gguf_ref(text):
        return ModelSource(
            ref=text,
            kind="gguf",
            notes=("GGUF is an inference format — training requires HF transformers weights",),
        )
    path = Path(text).expanduser()
    try:
        is_dir = bool(text) and path.is_dir()
    except OSError:
        is_dir = False
    if is_dir:
        cfg = _read_config(path)
        notes: list[str] = []
        if not cfg:
            notes.append("config.json missing or unreadable")
        weights = _has_weights(path)
        if not weights:
            notes.append("no *.safetensors / *.bin weights found")
        return ModelSource(
            ref=text,
            kind="local_dir",
            path=str(path),
            has_config=bool(cfg),
            has_weights=weights,
            model_config=cfg,
            notes=tuple(notes),
        )
    snap = _find_in_hf_cache(text, revision) if text else None
    if snap is not None:
        cfg = _read_config(snap)
        return ModelSource(
            ref=text,
            kind="hf_cache",
            path=str(snap),
            has_config=bool(cfg),
            has_weights=_has_weights(snap),
            model_config=cfg,
        )
    return ModelSource(
        ref=text,
        kind="missing",
        notes=("not a local directory and not present in the local Hugging Face cache",),
    )


def estimate_param_count(model_config: dict[str, Any]) -> int | None:
    """Rough decoder-only parameter estimate from config.json (labeled estimate)."""
    cfg = dict(model_config or {})
    if isinstance(cfg.get("text_config"), dict):
        cfg = {**cfg, **cfg["text_config"]}
    hidden = cfg.get("hidden_size") or cfg.get("n_embd") or cfg.get("d_model")
    layers = cfg.get("num_hidden_layers") or cfg.get("n_layer") or cfg.get("num_layers")
    vocab = cfg.get("vocab_size")
    if not (isinstance(hidden, int) and isinstance(layers, int) and isinstance(vocab, int)):
        return None
    inter = cfg.get("intermediate_size") or cfg.get("n_inner") or 4 * hidden
    heads = cfg.get("num_attention_heads") or cfg.get("n_head") or 1
    kv_heads = cfg.get("num_key_value_heads") or heads
    head_dim = hidden // max(1, int(heads))
    attn = hidden * hidden * 2 + 2 * hidden * head_dim * int(kv_heads)
    gated = str(cfg.get("hidden_act") or cfg.get("activation_function") or "").lower() in {"silu", "swiglu"}
    mlp = (3 if gated else 2) * hidden * int(inter)
    per_layer = attn + mlp + 4 * hidden
    embeddings = vocab * hidden * (1 if cfg.get("tie_word_embeddings", True) else 2)
    return int(layers * per_layer + embeddings)
