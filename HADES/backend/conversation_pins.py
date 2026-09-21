"""Conversation pins with secret-path honesty (HADES-10 Phase 4).

Pin means: always consider this source — not dump entire files into every prompt.
Force-pin must not bypass blocked secret paths.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Obvious credential / secret filenames — force-pin cannot bypass these.
BLOCKED_PIN_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "credentials.json",
        "secrets.json",
        "id_rsa",
        "id_ed25519",
        "id_dsa",
        "private.key",
        "private-key.pem",
        "service-account.json",
    }
)

BLOCKED_PIN_SUFFIXES = (
    ".pem",
    ".p12",
    ".pfx",
    ".key",
)


def is_blocked_pin_path(path: str | Path, *, force: bool = False) -> tuple[bool, str]:
    """Return (blocked, reason). Force never bypasses security policy."""
    del force  # intentional: force cannot override
    raw = str(path or "").strip()
    if not raw:
        return True, "empty_path"
    name = Path(raw).name.lower()
    if name in {item.lower() for item in BLOCKED_PIN_NAMES}:
        return True, "blocked_secret_name"
    if name.startswith(".env.") or name == ".env":
        return True, "blocked_env_file"
    if any(name.endswith(suffix) for suffix in BLOCKED_PIN_SUFFIXES):
        return True, "blocked_key_material"
    lowered = raw.replace("\\", "/").lower()
    if "/.ssh/" in lowered or "\\ .ssh\\".replace(" ", "") in lowered.replace("/", "\\"):
        return True, "blocked_ssh_path"
    if any(token in name for token in ("password", "secret", "credential", "apikey", "api_key")):
        return True, "blocked_credential_name"
    return False, ""


def classify_pin_entry(path: str, *, exists: bool | None = None) -> dict[str, Any]:
    blocked, reason = is_blocked_pin_path(path)
    if blocked:
        return {"path": path, "status": "skipped", "reason": reason, "indexed": False}
    path_exists = Path(path).exists() if exists is None else bool(exists)
    if not path_exists:
        return {"path": path, "status": "stale", "reason": "missing", "indexed": False}
    if Path(path).is_dir():
        return {"path": path, "status": "indexed", "reason": "folder", "indexed": True, "kind": "folder"}
    return {"path": path, "status": "indexed", "reason": "file", "indexed": True, "kind": "file"}


def summarize_pins(entries: list[dict[str, Any]]) -> dict[str, Any]:
    indexed = sum(1 for item in entries if item.get("status") == "indexed")
    stale = sum(1 for item in entries if item.get("status") == "stale")
    skipped = sum(1 for item in entries if item.get("status") == "skipped")
    return {
        "indexed": indexed,
        "stale": stale,
        "skipped": skipped,
        "total": len(entries),
        "label": f"{indexed} indexed · {stale} stale · {skipped} skipped",
    }


def filter_pin_paths(paths: list[str], *, force: bool = False) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for raw in paths:
        path = os.path.expanduser(str(raw or "").strip())
        if not path:
            continue
        blocked, reason = is_blocked_pin_path(path, force=force)
        if blocked:
            skipped.append({"path": path, "reason": reason, "force_ignored": bool(force)})
            continue
        accepted.append(classify_pin_entry(path))
    summary = summarize_pins(accepted + [{"status": "skipped"} for _ in skipped])
    summary["skipped"] = len(skipped)
    summary["label"] = f"{summary['indexed']} indexed · {summary['stale']} stale · {len(skipped)} skipped"
    return {"accepted": accepted, "skipped": skipped, "summary": summary}


def pins_from_working_state(working_state: dict[str, Any] | None) -> dict[str, Any]:
    """Read persisted conversation pins from working_state."""
    state = working_state if isinstance(working_state, dict) else {}
    raw = state.get("pins") if isinstance(state.get("pins"), dict) else {}
    accepted = list(raw.get("accepted") or []) if isinstance(raw.get("accepted"), list) else []
    skipped = list(raw.get("skipped") or []) if isinstance(raw.get("skipped"), list) else []
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else summarize_pins(
        list(accepted) + [{"status": "skipped"} for _ in skipped]
    )
    return {"accepted": accepted, "skipped": skipped, "summary": summary}


def apply_pins_to_working_state(
    working_state: dict[str, Any] | None,
    *,
    paths: list[str],
    force: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Filter paths and merge into a working_state copy. Returns (state, pin_result)."""
    state = dict(working_state or {})
    result = filter_pin_paths(paths, force=force)
    state["pins"] = {
        "accepted": result["accepted"],
        "skipped": result["skipped"],
        "summary": result["summary"],
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    return state, result


def pin_context_snippets(
    pin_bundle: dict[str, Any] | None,
    *,
    max_files: int = 8,
    max_chars_per_file: int = 2_000,
) -> list[dict[str, Any]]:
    """Bounded snippets for pinned files — never dump whole sources into every prompt."""
    bundle = pin_bundle if isinstance(pin_bundle, dict) else {}
    accepted = bundle.get("accepted") if isinstance(bundle.get("accepted"), list) else []
    out: list[dict[str, Any]] = []
    for entry in accepted:
        if len(out) >= max_files:
            break
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "indexed":
            continue
        path = Path(str(entry.get("path") or ""))
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snippet = text[:max_chars_per_file]
        if len(text) > max_chars_per_file:
            snippet = snippet.rstrip() + "\n…[truncated; pin means consider, not paste entire file]"
        out.append(
            {
                "path": str(path),
                "kind": "file",
                "chars": len(snippet),
                "truncated": len(text) > max_chars_per_file,
                "content": snippet,
            }
        )
    return out
