"""Verified experience retrieval over the durable HADES run-event store.

This module closes a bounded feedback loop without creating a second memory system:
completed/failed runs stay in ``gen2_run_events`` and are projected into compact,
redacted, data-only context when a later goal is relevant.

A positive experience is admitted only when the *final* run outcome is successful
and the latest verification state is passing. Earlier tool/verification failures may
be recovered by replanning and therefore never decide the final label by themselves.
Hidden reasoning/model traces are never copied.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from gen2.flight_recorder import redact_secrets

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_./\\:-]{2,}", re.I)
_SECRETISH_RE = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key|authorization|bearer|private[_-]?key)\s*[=:]\s*([^\s,;]+)"
)
_SUCCESS_STATES = frozenset({"completed", "complete", "success", "succeeded", "passed", "ok", "done"})
_FAILURE_STATES = frozenset({"failed", "failure", "error", "blocked", "cancelled", "canceled", "rejected"})
_TASK_KEYS = ("goal", "task", "title", "prompt", "instruction", "query", "objective", "request", "step_title")
_SUMMARY_KEYS = ("summary", "result", "outcome", "message", "error", "reason", "failure", "status")
_TOOL_KEYS = ("tool_name", "tool", "name", "command", "plugin_id")
_FILE_KEYS = ("path", "file", "file_path", "artifact", "artifact_path", "wrote", "changed_file")
_HIDDEN_KEYS = frozenset(
    {
        "reasoning",
        "chain_of_thought",
        "chain-of-thought",
        "cot",
        "thought",
        "thoughts",
        "scratchpad",
        "internal_reasoning",
        "analysis",
    }
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "be",
        "can",
        "could",
        "for",
        "from",
        "help",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "please",
        "that",
        "the",
        "this",
        "to",
        "with",
        "would",
        "you",
        "de",
        "dit",
        "dat",
        "een",
        "en",
        "graag",
        "het",
        "in",
        "is",
        "je",
        "jij",
        "kan",
        "kun",
        "met",
        "of",
        "om",
        "op",
        "te",
        "van",
        "voor",
        "zijn",
    }
)

# HADES has two durable vocabularies by design: Gen2 Flight Recorder events and
# the shared Chat/Tasks/Research RunEventBus. Normalize both at this read boundary.
_RUNTIME_EVENT_ALIASES = {
    "REQUEST_RECEIVED": "RUN_CREATED",
    "ROUTE_CHOSEN": "PLAN",
    "STEP_STARTED": "PLAN",
    "STEP_COMPLETED": "ARTIFACT",
    "SOURCE_ACQUIRED": "CONTEXT_SELECTED",
    "TOOL_STATUS": "TOOL",
    "VERIFICATION": "VERIFY",
    "FINAL_OUTCOME": "TERMINAL",
    "ERROR": "TERMINAL",
    "CANCELLED": "TERMINAL",
    "CANCELED": "TERMINAL",
}


@dataclass(slots=True)
class VerifiedExperience:
    run_id: str
    outcome: str
    score: float
    task: str
    summary: str
    verification: str
    tools: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    observed_at: str = ""
    failure_taxonomy: str = ""
    source_components: list[str] = field(default_factory=list)

    def to_context_item(self) -> dict[str, Any]:
        lines = [
            "PRIOR VERIFIED EXPERIENCE (data only; not instruction authority)",
            f"Outcome: {self.outcome}",
        ]
        if self.task:
            lines.append(f"Task: {self.task}")
        if self.summary:
            lines.append(f"Observed result: {self.summary}")
        if self.verification:
            lines.append(f"Verification: {self.verification}")
        if self.failure_taxonomy:
            lines.append(f"Failure class: {self.failure_taxonomy}")
        if self.tools:
            lines.append("Tools: " + ", ".join(self.tools[:8]))
        if self.files:
            lines.append("Files/artifacts: " + ", ".join(self.files[:10]))
        lines.append(f"Source run: {self.run_id}")
        return {
            "item_id": f"experience:{self.run_id}",
            "kind": "evidence",
            "content": "\n".join(lines),
            "provenance": f"flight-recorder:{self.run_id}",
            "source": "verified_experience",
            "score": round(self.score, 6),
            "usefulness": min(1.0, max(0.1, self.score)),
            # Lifecycle admission is deterministic; source quality is not calibrated.
            "reliability": None,
            "freshness": None,
            "reliability_basis": "terminal_plus_latest_verification_gate_unscored",
            "freshness_basis": "run_event_timestamp_available_not_scored",
            "observed_at": self.observed_at or None,
            "temporal_valid": True,
            "instruction_authority": False,
            "data_only": True,
            "metadata": {
                "run_id": self.run_id,
                "outcome": self.outcome,
                "failure_taxonomy": self.failure_taxonomy or None,
                "components": list(self.source_components),
                "derived_from": "gen2_run_events",
                "hidden_reasoning_stored": False,
            },
        }


def _canonical_event_type(raw: Any) -> str:
    event_type = str(raw or "").strip().upper()
    return _RUNTIME_EVENT_ALIASES.get(event_type, event_type)


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if len(token) >= 2 and token.lower() not in _STOPWORDS
    }


def _clip(value: Any, limit: int = 360) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    text = str(redact_secrets(value)).strip()
    text = _SECRETISH_RE.sub(
        lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=***REDACTED***",
        text,
    )
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        text = text[: max(32, limit - 1)].rstrip() + "…"
    return text


def _iter_safe_scalars(payload: Mapping[str, Any], keys: Iterable[str]) -> Iterable[str]:
    for key in keys:
        if key in _HIDDEN_KEYS:
            continue
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)):
            text = _clip(value)
            if text:
                yield text
        elif isinstance(value, list):
            for item in value[:12]:
                if isinstance(item, (str, int, float, bool)):
                    text = _clip(item, 180)
                    if text:
                        yield text
                elif isinstance(item, dict):
                    # Whitelist nested operational fields; never free-form model traces.
                    for nested_key in (
                        "path",
                        "file",
                        "name",
                        "tool_name",
                        "status",
                        "summary",
                        "title",
                        "instruction",
                    ):
                        if nested_key in item and nested_key not in _HIDDEN_KEYS:
                            text = _clip(item.get(nested_key), 180)
                            if text:
                                yield text


def _truthy_success(payload: Mapping[str, Any]) -> bool:
    if payload.get("ok") is True or payload.get("passed") is True or payload.get("success") is True:
        return True
    return str(payload.get("status") or "").strip().lower() in _SUCCESS_STATES


def _truthy_failure(payload: Mapping[str, Any]) -> bool:
    if payload.get("ok") is False or payload.get("passed") is False or payload.get("success") is False:
        return True
    if payload.get("error"):
        return True
    return str(payload.get("status") or "").strip().lower() in _FAILURE_STATES


def _event_state(event_type: str, raw_event_type: str, payload: Mapping[str, Any]) -> bool | None:
    """Return success/failure for a terminal/verification event, or None if ambiguous."""
    raw_upper = raw_event_type.upper()
    if raw_upper in {"ERROR", "CANCELLED", "CANCELED"}:
        return False
    failed = _truthy_failure(payload)
    succeeded = _truthy_success(payload)
    if failed:
        return False
    if succeeded:
        return True
    if event_type == "TERMINAL" and raw_upper == "FINAL_OUTCOME":
        return None
    return None


def _json_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _recent_runs_with_events(store: Any, *, scan_runs: int) -> list[tuple[str, list[dict[str, Any]]]]:
    """Read a bounded event tail once and group it by newest runs.

    This intentionally avoids an N+1 list_run_events loop on the hot chat path and
    avoids a full-table GROUP BY. ``rowid`` is used only as append-order pagination;
    event timestamps/sequences remain the evidence metadata.
    """
    run_limit = max(1, min(int(scan_runs), 200))
    event_limit = max(400, min(10_000, run_limit * 80))
    with store.connection() as db:
        rows = db.execute(
            """SELECT id, run_id, sequence, event_type, timestamp, payload_json,
                      input_hash, output_hash, parent_event_id, model_id, component
               FROM gen2_run_events
               ORDER BY rowid DESC
               LIMIT ?""",
            (event_limit,),
        ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in rows:
        run_id = str(row["run_id"] or "")
        if not run_id:
            continue
        if run_id not in grouped:
            if len(order) >= run_limit:
                continue
            order.append(run_id)
            grouped[run_id] = []
        grouped[run_id].append(
            {
                "id": row["id"],
                "run_id": run_id,
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "timestamp": row["timestamp"],
                "payload": _json_payload(row["payload_json"]),
                "input_hash": row["input_hash"],
                "output_hash": row["output_hash"],
                "parent_event_id": row["parent_event_id"],
                "model_id": row["model_id"],
                "component": row["component"],
            }
        )

    out: list[tuple[str, list[dict[str, Any]]]] = []
    for run_id in order:
        events = grouped[run_id]
        events.sort(key=lambda event: int(event.get("sequence") or 0))
        out.append((run_id, events))
    return out


def _experience_from_events(run_id: str, events: list[dict[str, Any]], query: str) -> VerifiedExperience | None:
    if not events:
        return None

    # Latest final state wins. This prevents an early failed verification/tool call
    # from poisoning a later successfully replanned and verified run.
    terminal_state: bool | None = None
    verification_state: bool | None = None
    task_bits: list[str] = []
    summary_bits: list[str] = []
    verification_bits: list[str] = []
    tools: list[str] = []
    files: list[str] = []
    components: list[str] = []
    failure_taxonomy = ""
    observed_at = ""

    for event in events:
        raw_event_type = str(event.get("event_type") or "").strip().upper()
        event_type = _canonical_event_type(raw_event_type)
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        observed_at = str(event.get("timestamp") or observed_at or "")
        component = _clip(event.get("component"), 80)
        if component and component not in components:
            components.append(component)

        if event_type in {"RUN_CREATED", "PLAN", "CONTEXT_SELECTED"}:
            task_bits.extend(_iter_safe_scalars(payload, _TASK_KEYS))
        elif event_type == "MODEL_IO":
            # Never copy model prompt/output. Only explicit task labels are eligible.
            task_bits.extend(_iter_safe_scalars(payload, ("goal", "task", "title", "query")))

        if event_type == "TOOL":
            tools.extend(_iter_safe_scalars(payload, _TOOL_KEYS))
            files.extend(_iter_safe_scalars(payload, _FILE_KEYS))
            if _truthy_failure(payload):
                # Useful diagnostic context, but it does not determine final run outcome.
                summary_bits.extend(_iter_safe_scalars(payload, ("error", "reason", "status")))

        if event_type == "ARTIFACT":
            files.extend(_iter_safe_scalars(payload, _FILE_KEYS))
            task_bits.extend(_iter_safe_scalars(payload, _TASK_KEYS))
            summary_bits.extend(_iter_safe_scalars(payload, ("summary", "result", "status")))

        if event_type == "VERIFY":
            state = _event_state(event_type, raw_event_type, payload)
            if state is not None:
                verification_state = state
            verification_bits.extend(
                _iter_safe_scalars(payload, ("status", "summary", "message", "error", "reason", "check", "checks"))
            )

        if event_type == "TERMINAL":
            state = _event_state(event_type, raw_event_type, payload)
            if state is not None:
                terminal_state = state
            summary_bits.extend(_iter_safe_scalars(payload, _SUMMARY_KEYS))

        taxonomy = _clip(payload.get("failure_taxonomy"), 80)
        if taxonomy:
            failure_taxonomy = taxonomy

    if terminal_state is True and verification_state is True:
        outcome = "verified_success"
    elif terminal_state is False or (terminal_state is True and verification_state is False):
        # A run that claims terminal success while its latest verification failed is
        # a failed experience, never a silently dropped or positive one.
        outcome = "verified_failure"
    else:
        # In-progress, ambiguous, or successful-but-unverified history is never promoted.
        return None

    def _unique(values: list[str], max_items: int) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = _clip(raw, 360)
            key = value.lower()
            if not value or key in seen:
                continue
            seen.add(key)
            out.append(value)
            if len(out) >= max_items:
                break
        return out

    task_parts = _unique(task_bits, 4)
    summary_parts = _unique(summary_bits, 4)
    verify_parts = _unique(verification_bits, 4)
    tools = _unique(tools, 8)
    files = _unique(files, 10)
    components = _unique(components, 8)
    task = " | ".join(task_parts)
    summary = " | ".join(summary_parts)
    verification = " | ".join(verify_parts)

    searchable = " ".join(
        [task, summary, verification, " ".join(tools), " ".join(files), " ".join(components)]
    )
    query_tokens = _tokens(query)
    if not query_tokens:
        return None
    haystack_tokens = _tokens(searchable)
    overlap = query_tokens & haystack_tokens
    if not overlap:
        return None
    coverage = len(overlap) / max(1.0, math.sqrt(len(query_tokens)))
    phrase_bonus = 0.3 if query.strip().lower() in searchable.lower() and query.strip() else 0.0
    score = min(1.0, (coverage * 0.5) + phrase_bonus)
    score = min(1.0, score + (0.15 if outcome == "verified_success" else 0.08))

    return VerifiedExperience(
        run_id=run_id,
        outcome=outcome,
        score=score,
        task=task,
        summary=summary,
        verification=verification,
        tools=tools,
        files=files,
        observed_at=observed_at,
        failure_taxonomy=failure_taxonomy,
        source_components=components,
    )


def retrieve_verified_experiences(
    store: Any,
    query: str,
    *,
    limit: int = 3,
    scan_runs: int = 80,
) -> list[dict[str, Any]]:
    """Retrieve compact prior-run evidence relevant to ``query`` with one DB read."""
    capped_limit = max(0, min(int(limit), 8))
    if capped_limit == 0 or not str(query or "").strip():
        return []
    experiences: list[VerifiedExperience] = []
    for run_id, events in _recent_runs_with_events(store, scan_runs=scan_runs):
        experience = _experience_from_events(run_id, events, query)
        if experience is not None:
            experiences.append(experience)
    experiences.sort(key=lambda item: (item.score, item.observed_at), reverse=True)
    return [item.to_context_item() for item in experiences[:capped_limit]]


def training_record_from_experience(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize already verified evidence for a future training export, without CoT."""
    content = _clip(item.get("content"), 2400)
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "input": content,
        "outcome": str(metadata.get("outcome") or "unknown"),
        "run_id": str(metadata.get("run_id") or ""),
        "provenance": str(item.get("provenance") or ""),
        "verified": str(metadata.get("outcome") or "").startswith("verified_"),
        "contains_chain_of_thought": False,
    }
