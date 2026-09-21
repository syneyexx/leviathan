"""Model-driven InvestigateAction selector (additive beside deterministic strategy).

The model may only choose from allowed actions; arguments are validated before
the existing InteractiveCodingInvestigator dispatcher executes them.

Uses the shared Coding model runtime so async chat_fn callables are awaited
with timeout + cancellation — never left as un-awaited coroutines.
"""

from __future__ import annotations

import json
import re
from typing import Any


ALLOWED_KINDS = {
    "search_code",
    "read_file",
    "read_span",
    "find_definition",
    "find_references",
    "read_diagnostics",
    "run_test",
    "gather_missing_context",
    "prepare_edit",
    "verify_result",
}


class InvestigateSelectorCancelled(Exception):
    """Selector model call was cancelled — must not trigger heuristic fallback."""

    def __init__(self, message: str = "investigate_selector_cancelled", *, run_id: str | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.kind = "cancelled"


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def propose_investigate_action(
    *,
    goal: str,
    observations: list[dict[str, Any]],
    open_questions: list[dict[str, Any]],
    allowed: list[dict[str, Any]],
    chat_fn: Any,
    model_id: str | None = None,
    run_id: str | None = None,
    timeout_s: float | None = None,
    cancel_check: Any | None = None,
) -> dict[str, Any] | None:
    """Ask the model for the next allowed action.

    Returns None on genuine model/parse failure → caller may fall back.
    Raises InvestigateSelectorCancelled when the run was cancelled — callers
    must NOT treat that as ordinary parse failure / heuristic fallback.
    """
    from coding_model_resolve import coding_lm_timeout_seconds
    from coding_model_runtime import CodingModelCancelled, invoke_coding_chat_fn

    allowed_kinds = sorted({str(a.get("kind")) for a in allowed if a.get("kind") in ALLOWED_KINDS})
    if not allowed_kinds:
        return None
    prompt = {
        "role": "user",
        "content": (
            "You select the next coding investigation action for HADES.\n"
            "Return ONLY JSON: {\"kind\": string, \"args\": object, \"rationale\": string}.\n"
            f"Allowed kinds: {allowed_kinds}\n"
            f"Goal: {goal}\n"
            f"Open questions: {json.dumps(open_questions[:6], ensure_ascii=False)}\n"
            f"Recent observations: {json.dumps(observations[-6:], ensure_ascii=False)[:4000]}\n"
            "Pick the action that best resolves an open question or distinguishes hypotheses.\n"
            "Do not invent tools. Do not propose edits content here — use prepare_edit only when evidence is enough."
        ),
    }
    payload: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": "You are a coding investigation action selector. JSON only."},
            prompt,
        ],
        "temperature": 0,
    }
    if model_id:
        payload["model"] = model_id

    effective_timeout = coding_lm_timeout_seconds() if timeout_s is None else float(timeout_s)
    try:
        outcome = invoke_coding_chat_fn(
            chat_fn,
            payload,
            run_id=run_id,
            timeout_s=effective_timeout,
            phase="investigate_select",
            cancel_check=cancel_check,
        )
    except CodingModelCancelled as exc:
        raise InvestigateSelectorCancelled(run_id=run_id) from exc

    if outcome.kind == "cancelled":
        raise InvestigateSelectorCancelled(run_id=run_id)
    if outcome.kind in {"timeout", "error"} or outcome.response is None:
        # Genuine failure / unavailable — deterministic fallback is allowed.
        return _heuristic_from_observations(observations, allowed_kinds, allowed)

    response = outcome.response
    content = ""
    if isinstance(response, dict):
        choices = response.get("choices") or []
        if choices:
            content = str((choices[0].get("message") or {}).get("content") or "")
        else:
            content = str(response.get("content") or response.get("text") or "")
    else:
        content = str(response or "")
    data = _extract_json(content)
    if not data:
        return _heuristic_from_observations(observations, allowed_kinds, allowed)
    kind = str(data.get("kind") or "")
    if kind not in allowed_kinds:
        return _heuristic_from_observations(observations, allowed_kinds, allowed)
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    return {"kind": kind, "args": args, "rationale": str(data.get("rationale") or "model")}


def _heuristic_from_observations(
    observations: list[dict[str, Any]],
    allowed_kinds: list[str],
    allowed: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Two different failure shapes → different next steps (acceptance for selector)."""
    blob = json.dumps(observations[-8:], ensure_ascii=False).lower()
    template = {a["kind"]: a for a in allowed}

    def pick(kind: str, **args: Any) -> dict[str, Any] | None:
        if kind not in allowed_kinds:
            return None
        base = dict((template.get(kind) or {}).get("args") or {})
        base.update(args)
        return {"kind": kind, "args": base, "rationale": "selector_heuristic"}

    if "importerror" in blob or "modulenotfound" in blob:
        return pick("gather_missing_context") or pick("search_code", query="import module")
    if "typeerror" in blob or "typescript" in blob or "ts(" in blob:
        return pick("find_definition") or pick("read_diagnostics")
    if "assertionerror" in blob or "assert" in blob:
        return pick("gather_missing_context") or pick("read_file")
    if "timeout" in blob or "race" in blob or "async" in blob:
        return pick("read_diagnostics") or pick("search_code", query="async await race lock")
    if not observations:
        return pick("run_test") or pick("search_code", query="test")
    return pick("read_diagnostics") or pick("gather_missing_context")
