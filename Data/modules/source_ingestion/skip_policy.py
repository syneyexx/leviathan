"""Configurable skip policy for codebase / archive members."""

from __future__ import annotations

from pathlib import PurePosixPath

DEFAULT_SKIP_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".next",
        ".nuxt",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "coverage",
        "target",
        ".cache",
        ".tox",
        ".eggs",
        ".idea",
        ".vscode",
        "eggs",
        ".sass-cache",
    }
)

DEFAULT_SKIP_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".o",
        ".obj",
        ".class",
        ".pyc",
        ".pyo",
        ".pdb",
        ".a",
        ".lib",
        ".wasm",
        ".bin",
        ".dat",
        ".pak",
        ".dmg",
        ".iso",
        ".img",
        ".apk",
        ".ipa",
    }
)


def normalize_rel_path(path: str) -> str:
    text = (path or "").replace("\\", "/").strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def path_parts(relative_path: str) -> list[str]:
    rel = normalize_rel_path(relative_path)
    if not rel:
        return []
    return list(PurePosixPath(rel).parts)


def should_skip_path(
    relative_path: str,
    *,
    skip_directories: frozenset[str] | set[str] | None = None,
    skip_extensions: frozenset[str] | set[str] | None = None,
    enabled: bool = True,
) -> tuple[bool, str | None]:
    if not enabled:
        return False, None
    dirs = skip_directories if skip_directories is not None else DEFAULT_SKIP_DIRECTORIES
    exts = skip_extensions if skip_extensions is not None else DEFAULT_SKIP_EXTENSIONS
    parts = path_parts(relative_path)
    for part in parts[:-1] if parts else []:
        if part in dirs:
            return True, f"generated_directory:{part}"
    if parts and parts[-1] in dirs:
        return True, f"generated_directory:{parts[-1]}"
    name = parts[-1] if parts else ""
    ext = PurePosixPath(name).suffix.lower()
    if ext in exts:
        return True, f"binary:{ext}"
    return False, None
