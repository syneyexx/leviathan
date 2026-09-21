"""Structured failure normalization for coding verification logs.

Deterministic parsers — the model should receive compact failure objects, not raw dumps.
Complete logs may be stored as artifacts separately.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

FAILURE_TYPES = (
    "python_traceback",
    "pytest",
    "unittest",
    "typescript",
    "eslint",
    "npm_vite",
    "cmake",
    "msvc",
    "gcc_clang",
    "linker",
    "javac",
    "rustc",
    "generic_subprocess",
)

_PY_FILE_LINE = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<sym>\S+))?')
_PYTEST = re.compile(r"(?P<file>[\w./\\-]+\.py):(?P<line>\d+):(?:\s*(?P<msg>.+))?")
_UNITTEST = re.compile(r"^(?P<kind>FAIL|ERROR):\s+(?P<test>.+)$", re.M)
_TS = re.compile(
    r"(?P<file>[\w./\\-]+\.(?:ts|tsx|js|jsx))\((?P<line>\d+),(?P<col>\d+)\):\s*error\s+(?P<code>TS\d+):\s*(?P<msg>.+)",
    re.I,
)
_ESLINT = re.compile(
    r"(?P<file>[\w./\\-]+\.(?:ts|tsx|js|jsx|mjs)): line (?P<line>\d+), col \d+, (?:Error|error) - (?P<msg>.+)"
)
_ESLINT_STYLISH = re.compile(r"^\s*(?P<line>\d+):(?P<col>\d+)\s+error\s+(?P<msg>.+)$", re.M)
_VITE = re.compile(r"(?:ERROR|error)(?:\s+in)?\s+(?P<file>[\w./\\-]+\.(?:ts|tsx|js|jsx|vue))")
_CMAKE = re.compile(r"CMake (?:Error|Warning)(?: at (?P<file>[^:]+):(?P<line>\d+))?", re.I)
_MSVC = re.compile(
    r"(?P<file>[\w./\\-]+\.(?:c|cc|cpp|cxx|h|hpp))\((?P<line>\d+)(?:,(?P<col>\d+))?\)\s*:\s*(?:error|fatal error)\s+(?P<code>C\d+):\s*(?P<msg>.+)",
    re.I,
)
_GCC = re.compile(
    r"(?P<file>[\w./\\-]+\.(?:c|cc|cpp|cxx|h|hpp|rs)):(?P<line>\d+)(?::(?P<col>\d+))?:\s*(?:fatal )?error:\s*(?P<msg>.+)"
)
_LINKER = re.compile(r"(?:undefined reference to|unresolved external symbol|ld:|LINK : fatal error)\s*(?P<msg>.+)", re.I)
_JAVAC = re.compile(r"(?P<file>[\w./\\-]+\.java):(?P<line>\d+):\s*error:\s*(?P<msg>.+)")
_RUSTC = re.compile(r"error(?:\[(?P<code>E\d+)\])?: (?P<msg>.+)\n\s+--> (?P<file>[^:]+):(?P<line>\d+):", re.S)
_ASSERT = re.compile(r"AssertionError:?\s*(?P<msg>.+)")
_NAME = re.compile(r"NameError:\s*name '(?P<name>[^']+)'")


@dataclass
class StructuredFailure:
    tool: str
    command: list[str] = field(default_factory=list)
    exit_code: int | None = None
    failure_type: str = "generic_subprocess"
    file: str | None = None
    line: int | None = None
    symbol: str | None = None
    message: str = ""
    stack: list[str] = field(default_factory=list)
    probable_owner: str | None = None
    related_changes: list[str] = field(default_factory=list)
    raw_excerpt: str = ""
    compacted: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compact_log(text: str, *, limit: int = 4000) -> str:
    """Keep failure summary, stack frames, assertions, and command metadata."""
    blob = text or ""
    if len(blob) <= limit:
        return blob
    lines = blob.splitlines()
    keep: list[str] = []
    keywords = (
        "error",
        "fail",
        "traceback",
        "assert",
        "undefined",
        "exception",
        "fatal",
        "panic",
        "not found",
        "cannot",
        "failed",
    )
    for line in lines:
        lower = line.lower()
        if any(k in lower for k in keywords) or line.startswith("  File ") or line.startswith("E   "):
            keep.append(line)
    if not keep:
        keep = lines[-80:]
    # Always retain head metadata and tail.
    head = lines[:12]
    tail = lines[-20:]
    merged: list[str] = []
    seen: set[str] = set()
    for line in head + keep + tail:
        if line in seen:
            continue
        seen.add(line)
        merged.append(line)
    out = "\n".join(merged)
    return out[:limit]


def normalize_failure(
    *,
    logs: str = "",
    command: list[str] | None = None,
    exit_code: int | None = None,
    tool: str | None = None,
    related_changes: list[str] | None = None,
) -> StructuredFailure:
    text = logs or ""
    cmd = list(command or [])
    inferred_tool = tool or _infer_tool(cmd, text)
    failure_type, file_name, line, symbol, message, stack = _parse(text, inferred_tool)
    owner = _probable_owner(file_name, related_changes or [])
    compacted = compact_log(text)
    excerpt = text[-1500:]
    return StructuredFailure(
        tool=inferred_tool,
        command=cmd,
        exit_code=exit_code,
        failure_type=failure_type,
        file=file_name,
        line=line,
        symbol=symbol,
        message=(message or compacted.splitlines()[-1] if compacted else "")[:800],
        stack=stack[:30],
        probable_owner=owner,
        related_changes=list(related_changes or []),
        raw_excerpt=excerpt,
        compacted=compacted,
    )


def normalize_test_result(test: dict[str, Any], *, related_changes: list[str] | None = None) -> StructuredFailure:
    logs = f"{test.get('stdout') or ''}\n{test.get('stderr') or ''}"
    return normalize_failure(
        logs=logs,
        command=list(test.get("command") or []),
        exit_code=test.get("exit_code"),
        tool=str(test.get("suite") or ""),
        related_changes=related_changes,
    )


def _infer_tool(command: list[str], text: str) -> str:
    blob = " ".join(command).lower() + "\n" + (text[:500].lower())
    if "pytest" in blob:
        return "pytest"
    if "unittest" in blob:
        return "unittest"
    if "tsc" in blob or "error ts" in blob:
        return "tsc"
    if "eslint" in blob:
        return "eslint"
    if "vite" in blob or "npm" in blob:
        return "npm"
    if "cmake" in blob:
        return "cmake"
    if "cl.exe" in blob or " error c" in blob:
        return "msvc"
    if "javac" in blob:
        return "javac"
    if "rustc" in blob or "cargo" in blob:
        return "rustc"
    if "gcc" in blob or "clang" in blob or ": error:" in blob:
        return "gcc_clang"
    return "subprocess"


def _parse(text: str, tool: str) -> tuple[str, str | None, int | None, str | None, str, list[str]]:
    stack = [m.group(0) for m in _PY_FILE_LINE.finditer(text)][:20]
    if _RUSTC.search(text):
        match = _RUSTC.search(text)
        assert match is not None
        return "rustc", _norm(match.group("file")), int(match.group("line")), None, match.group("msg").strip(), stack
    if _MSVC.search(text):
        match = _MSVC.search(text)
        assert match is not None
        return "msvc", _norm(match.group("file")), int(match.group("line")), None, f"{match.group('code')}: {match.group('msg').strip()}", stack
    if _JAVAC.search(text):
        match = _JAVAC.search(text)
        assert match is not None
        return "javac", _norm(match.group("file")), int(match.group("line")), None, match.group("msg").strip(), stack
    if _TS.search(text):
        match = _TS.search(text)
        assert match is not None
        return "typescript", _norm(match.group("file")), int(match.group("line")), None, f"{match.group('code')}: {match.group('msg').strip()}", stack
    if _GCC.search(text) and ("error:" in text.lower()):
        match = _GCC.search(text)
        assert match is not None
        ftype = "linker" if _LINKER.search(text) and "undefined" in text.lower() else "gcc_clang"
        return ftype, _norm(match.group("file")), int(match.group("line")), None, match.group("msg").strip(), stack
    if _LINKER.search(text) and not _PY_FILE_LINE.search(text):
        match = _LINKER.search(text)
        assert match is not None
        return "linker", None, None, None, match.group("msg").strip()[:400], stack
    if _CMAKE.search(text) and "CMake" in text:
        match = _CMAKE.search(text)
        assert match is not None
        line = int(match.group("line")) if match.group("line") else None
        return "cmake", _norm(match.group("file")) if match.group("file") else None, line, None, match.group(0)[:400], stack
    if _ESLINT.search(text) or (tool == "eslint"):
        match = _ESLINT.search(text)
        if match:
            return "eslint", _norm(match.group("file")), int(match.group("line")), None, match.group("msg").strip(), stack
    if "vite" in text.lower() or "failed to compile" in text.lower():
        match = _VITE.search(text)
        path = _norm(match.group("file")) if match else None
        return "npm_vite", path, None, None, compact_log(text, limit=400), stack
    py_frames = list(_PY_FILE_LINE.finditer(text))
    if py_frames or "Traceback (most recent call last)" in text:
        last = py_frames[-1] if py_frames else None
        assert_msg = _ASSERT.search(text)
        name_err = _NAME.search(text)
        symbol = last.group("sym") if last else (name_err.group("name") if name_err else None)
        msg = assert_msg.group(0).strip() if assert_msg else (name_err.group(0) if name_err else "python exception")
        path = _norm(last.group("file")) if last else None
        line = int(last.group("line")) if last else None
        ftype = "pytest" if "pytest" in text.lower() or tool == "pytest" else (
            "unittest" if tool == "unittest" or _UNITTEST.search(text) else "python_traceback"
        )
        return ftype, path, line, symbol, msg[:800], stack
    if _PYTEST.search(text) and tool in {"pytest", "subprocess", "unittest", ""}:
        match = _PYTEST.search(text)
        assert match is not None
        return "pytest", _norm(match.group("file")), int(match.group("line")), None, (match.group("msg") or "").strip(), stack
    fail = _UNITTEST.search(text)
    if fail:
        return "unittest", None, None, fail.group("test").strip(), fail.group(0), stack
    msg = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "subprocess failed")
    return "generic_subprocess", None, None, None, msg[:800], stack


def _norm(path: str | None) -> str | None:
    if not path:
        return None
    return path.replace("\\", "/")


def _probable_owner(file_name: str | None, related: list[str]) -> str | None:
    if not file_name:
        return related[0] if related else None
    base = file_name.split("/")[-1]
    for rel in related:
        if rel.endswith(base) or base in rel:
            return rel
    return file_name
