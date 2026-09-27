"""Normalize external tool outputs into CapabilityResult-friendly structures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .types import ExternalFailureCode, ResultSpec, normalize_capability_parts


def parse_cli_result(
    *,
    stdout: str,
    stderr: str,
    exit_code: int,
    spec: ResultSpec,
    cwd: Path | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any], ExternalFailureCode | None]:
    """Return (status, output, failure_code)."""
    failure: ExternalFailureCode | None = None
    if spec.treat_nonzero_as_failure and exit_code != 0:
        failure = ExternalFailureCode.EXIT_NONZERO

    structured: Any = None
    raw_text = stdout
    sources: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []

    if spec.parse_stdout_json and stdout.strip():
        try:
            structured = json.loads(stdout)
        except json.JSONDecodeError:
            # Try JSONL
            if spec.format.value in {"JSONL", "MIXED"}:
                rows: list[Any] = []
                for line in stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        rows = []
                        break
                if rows:
                    structured = {"items": rows}

    if isinstance(structured, dict):
        maybe_sources = structured.get("sources") or structured.get("results") or structured.get("items")
        if isinstance(maybe_sources, list):
            for item in maybe_sources[:200]:
                if isinstance(item, Mapping):
                    sources.append(_normalize_source(item))
                elif isinstance(item, str):
                    sources.append({"title": item, "url": None})

    if cwd is not None and spec.artifact_globs:
        for pattern in spec.artifact_globs:
            for path in sorted(cwd.glob(pattern))[:100]:
                if path.is_file():
                    files.append({"path": str(path), "name": path.name, "size": path.stat().st_size})

    summary = None
    if isinstance(structured, dict) and structured.get("summary"):
        summary = str(structured["summary"])
    elif stdout.strip():
        summary = stdout.strip().splitlines()[0][:240]
    elif failure:
        summary = f"exit {exit_code}"
        if stderr.strip():
            summary = f"exit {exit_code}: {stderr.strip().splitlines()[0][:200]}"

    # Bound inline payloads.
    if len(stdout.encode("utf-8")) > spec.max_inline_bytes:
        raw_text = stdout[: spec.max_inline_bytes] + "\n…[truncated — see stdout artifact]"

    output = normalize_capability_parts(
        summary=summary,
        structured_data=structured if _bounded_struct(structured, spec.max_inline_bytes) else None,
        sources=sources or None,
        artifacts=artifact_refs,
        files=files or None,
        raw_text=None if structured is not None else raw_text[:8000],
        error=(
            {"code": failure.value, "exit_code": exit_code, "stderr_excerpt": stderr[:2000]}
            if failure
            else None
        ),
        metadata={"exit_code": exit_code, "result_format": spec.format.value},
    )
    # Always retain truncated stdout/stderr excerpts in metadata, never giant inline.
    output["stdout_excerpt"] = stdout[:4000]
    output["stderr_excerpt"] = stderr[:4000]
    status = "FAILED" if failure else "COMPLETED"
    return status, output, failure


def _bounded_struct(value: Any, max_bytes: int) -> bool:
    if value is None:
        return True
    try:
        encoded = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return False
    return len(encoded.encode("utf-8")) <= max_bytes


def _normalize_source(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "query": item.get("query"),
        "source": item.get("source") or item.get("provider") or item.get("site"),
        "result_type": item.get("result_type") or item.get("type"),
        "title": item.get("title") or item.get("name"),
        "identifier": item.get("identifier") or item.get("id"),
        "url": item.get("url") or item.get("link") or item.get("href"),
        "timestamp": item.get("timestamp") or item.get("published_at") or item.get("retrieved_at"),
        "summary": item.get("summary") or item.get("snippet") or item.get("description"),
        "structured": {
            k: v
            for k, v in item.items()
            if k
            not in {
                "query",
                "source",
                "provider",
                "site",
                "result_type",
                "type",
                "title",
                "name",
                "identifier",
                "id",
                "url",
                "link",
                "href",
                "timestamp",
                "published_at",
                "retrieved_at",
                "summary",
                "snippet",
                "description",
            }
        }
        or None,
        "raw_artifact_ref": item.get("raw_artifact_ref") or item.get("artifact_id"),
    }


def normalize_osint_items(items: list[Any], *, query: str | None = None, provider: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Mapping):
            normalized = _normalize_source(item)
            if query and not normalized.get("query"):
                normalized["query"] = query
            if provider and not normalized.get("source"):
                normalized["source"] = provider
            out.append(normalized)
        elif isinstance(item, str):
            out.append({"query": query, "source": provider, "title": item, "url": None})
    return out
