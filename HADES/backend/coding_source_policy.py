"""Centralized text-source candidate policy for Coding Agent discovery.

All Coding modules that decide what counts as a relevant textual project file
should use this module rather than maintaining divergent suffix lists.
Binary files are never accepted as candidates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    ".tox",
    "dist",
    "build",
    ".next",
    "target",
    ".cache",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
}

# Programming + markup + config suffixes safe to treat as text candidates.
TEXT_SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".json",
        ".md",
        ".mdx",
        ".txt",
        ".rst",
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
        ".h",
        ".hpp",
        ".hxx",
        ".java",
        ".kt",
        ".kts",
        ".rs",
        ".go",
        ".toml",
        ".cmake",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".html",
        ".htm",
        ".vue",
        ".svelte",
        ".yaml",
        ".yml",
        ".sql",
        ".graphql",
        ".gql",
        ".xml",
        ".ini",
        ".cfg",
        ".conf",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".bat",
        ".cmd",
        ".gradle",
        ".properties",
        ".env",
        ".svg",
        ".cs",
        ".fs",
        ".rb",
        ".php",
        ".swift",
        ".r",
        ".lua",
        ".pl",
        ".pm",
    }
)

# Exact basenames (case-insensitive) treated as text source candidates.
TEXT_SOURCE_BASENAMES: frozenset[str] = frozenset(
    {
        "dockerfile",
        "containerfile",
        "makefile",
        "gnumakefile",
        "cmakelists.txt",
        "rakefile",
        "gemfile",
        "procfile",
        "vagrantfile",
        "jenkinsfile",
        ".env.example",
        ".env.sample",
        ".editorconfig",
        ".gitignore",
        ".gitattributes",
        ".npmrc",
        ".nvmrc",
        "package.json",
        "tsconfig.json",
        "jsconfig.json",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "requirements.txt",
        "cargo.toml",
        "go.mod",
        "go.sum",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
    }
)

# Suffixes that are almost always binary / non-source for Coding discovery.
BINARY_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".7z",
        ".rar",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".o",
        ".a",
        ".obj",
        ".pyc",
        ".pyo",
        ".pyd",
        ".class",
        ".jar",
        ".war",
        ".whl",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
        ".webm",
        ".sqlite",
        ".db",
        ".lock",
    }
)

# Backward-compatible alias used by coding_agent historically.
SOURCE_SUFFIXES = set(TEXT_SOURCE_SUFFIXES)

_NULL_BYTE = b"\x00"
_MAX_SNIFF = 4096


def is_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS


def path_in_skip_dirs(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def is_text_source_basename(name: str) -> bool:
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    if lowered in TEXT_SOURCE_BASENAMES:
        return True
    # Dockerfile.* / Makefile.* variants
    if lowered.startswith("dockerfile") or lowered.startswith("containerfile"):
        return True
    if lowered.startswith("makefile") or lowered.startswith("gnumakefile"):
        return True
    if lowered.endswith(".env.example") or lowered.endswith(".env.sample"):
        return True
    return False


def looks_binary_bytes(sample: bytes) -> bool:
    if not sample:
        return False
    if _NULL_BYTE in sample:
        return True
    # High ratio of non-text control bytes → binary.
    control = sum(1 for b in sample if b < 9 or (13 < b < 32 and b != 27))
    return (control / max(1, len(sample))) > 0.30


def looks_binary_path(path: Path, *, sniff: bool = True) -> bool:
    suffix = path.suffix.lower()
    if suffix in BINARY_SUFFIXES:
        return True
    if not sniff:
        return False
    try:
        with path.open("rb") as handle:
            sample = handle.read(_MAX_SNIFF)
        return looks_binary_bytes(sample)
    except OSError:
        return True


def is_text_source_candidate(
    path: Path | str,
    *,
    root: Path | None = None,
    sniff_binary: bool = True,
) -> bool:
    """Return True when path is a safe textual project-file candidate."""
    p = Path(path)
    if path_in_skip_dirs(p):
        return False
    name = p.name
    suffix = p.suffix.lower()
    if suffix in BINARY_SUFFIXES:
        return False
    accepted = suffix in TEXT_SOURCE_SUFFIXES or is_text_source_basename(name)
    if not accepted:
        return False
    if sniff_binary and p.is_file():
        if looks_binary_path(p, sniff=True):
            return False
    if root is not None:
        try:
            from path_boundary import path_within_root

            if not path_within_root(p if p.is_absolute() else (root / p), root):
                return False
        except Exception:
            pass
    return True


def iter_text_source_files(
    root: Path,
    *,
    limit: int = 2000,
    prefer_tokens: Iterable[str] | None = None,
    exact_paths: Iterable[str] | None = None,
) -> list[Path]:
    """Bounded adaptive discovery of text source candidates.

    Prefer exact paths / token filename matches before alphabetical fill so large
    repositories can still locate late-tree targets (e.g. deep CSS files).
    """
    root = Path(root).expanduser().resolve()
    tokens = [t.lower() for t in (prefer_tokens or []) if t]
    preferred: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        if len(preferred) >= limit:
            return
        try:
            key = path.resolve().as_posix()
        except OSError:
            key = str(path)
        if key in seen:
            return
        if not path.is_file():
            return
        if not is_text_source_candidate(path, root=root, sniff_binary=True):
            return
        seen.add(key)
        preferred.append(path)

    for raw in exact_paths or []:
        rel = str(raw or "").strip().replace("\\", "/")
        if not rel:
            continue
        cand = root / rel
        if cand.is_file():
            _add(cand)

    # Pass 1: filename / path token matches (adaptive, not alphabetical-first).
    if tokens:
        try:
            for path in root.rglob("*"):
                if len(preferred) >= limit:
                    break
                if not path.is_file() or path_in_skip_dirs(path):
                    continue
                rel = path.relative_to(root).as_posix().lower()
                name = path.name.lower()
                if any(tok in name or tok in rel for tok in tokens):
                    _add(path)
        except OSError:
            pass

    # Pass 2: fill remaining budget with sorted walk (deterministic).
    if len(preferred) < limit:
        try:
            for path in sorted(root.rglob("*")):
                if len(preferred) >= limit:
                    break
                if not path.is_file() or path_in_skip_dirs(path):
                    continue
                _add(path)
        except OSError:
            pass

    return preferred[:limit]


def extract_path_hints(goal: str) -> list[str]:
    """Pull likely relative paths from a natural-language goal."""
    import re

    text = goal or ""
    hints: list[str] = []
    # Match path-like tokens with extensions or common separators.
    for match in re.finditer(
        r"(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]+|(?:[\w.-]+\\)+[\w.-]+\.[A-Za-z0-9]+|"
        r"[\w.-]+\.(?:css|scss|sass|less|tsx?|jsx?|py|html?|vue|svelte|ya?ml|sql|"
        r"graphql|gql|xml|ini|cfg|sh|ps1|bat|cmd|gradle|properties|toml|json|md)",
        text,
        re.I,
    ):
        hint = match.group(0).replace("\\", "/").strip(".,;:()[]{}\"'")
        if hint and hint not in hints:
            hints.append(hint)
    return hints


def policy_snapshot() -> dict[str, Any]:
    return {
        "suffix_count": len(TEXT_SOURCE_SUFFIXES),
        "basename_count": len(TEXT_SOURCE_BASENAMES),
        "skip_dirs": sorted(SKIP_DIRS),
        "includes_css": ".css" in TEXT_SOURCE_SUFFIXES,
        "includes_dockerfile": "dockerfile" in TEXT_SOURCE_BASENAMES,
    }
