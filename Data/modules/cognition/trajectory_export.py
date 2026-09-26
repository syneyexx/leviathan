"""Public training trajectory export — no private chain-of-thought (W11)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


_PRIVATE_KEYS = frozenset(
    {
        "private_cot",
        "hidden_reasoning",
        "chain_of_thought",
        "scratchpad",
        "raw_logits",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "api_key",
        "password",
    }
)


def _strip_private(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            k = str(key)
            if k.lower() in _PRIVATE_KEYS or k.lower().startswith("private_"):
                continue
            out[k] = _strip_private(value)
        return out
    if isinstance(obj, list):
        return [_strip_private(x) for x in obj]
    return obj


def export_training_trajectory(
    *,
    run_id: str,
    public_states: Sequence[Mapping[str, Any]] | None = None,
    messages: Sequence[Mapping[str, Any]] | None = None,
    selected_answer: str | None = None,
    verified_result: Mapping[str, Any] | None = None,
    tool_receipts: Sequence[Mapping[str, Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a dataset-ready public trajectory record.

    Includes only public states, user/tool messages, selected answer, and
    verified result. Never requires or persists private CoT.
    """
    safe_messages: list[dict[str, Any]] = []
    for msg in messages or []:
        role = str(msg.get("role") or "user")
        if role not in {"user", "assistant", "tool", "system"}:
            role = "user"
        # System messages in trajectories are behavior/meta only if explicitly marked public.
        if role == "system" and not msg.get("public"):
            continue
        safe_messages.append(
            {
                "role": role,
                "content": str(msg.get("content") or "")[:8000],
            }
        )
    record = {
        "run_id": run_id,
        "public_states": [_strip_private(dict(s)) for s in (public_states or [])],
        "messages": safe_messages,
        "selected_answer": (selected_answer or "")[:8000],
        "verified_result": _strip_private(dict(verified_result or {})),
        "tool_receipts": [_strip_private(dict(t)) for t in (tool_receipts or [])],
        "metadata": _strip_private(dict(metadata or {})),
        "truth": {
            "no_private_cot_required": True,
            "export_is_not_promotion": True,
            "unverified_is_not_training_truth": True,
        },
    }
    return record


def trajectories_to_dataset_rows(trajectories: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Flatten public trajectories into SFT-shaped rows (prompt/completion)."""
    rows: list[dict[str, Any]] = []
    for traj in trajectories:
        msgs = list(traj.get("messages") or [])
        prompt_parts = [
            str(m.get("content") or "")
            for m in msgs
            if m.get("role") in {"user", "tool"}
        ]
        answer = str(traj.get("selected_answer") or "")
        if not answer:
            for m in reversed(msgs):
                if m.get("role") == "assistant":
                    answer = str(m.get("content") or "")
                    break
        verified = traj.get("verified_result") or {}
        if not verified.get("passed") and not verified.get("status") in {
            "PASSED",
            "COMPLETED_VERIFIED",
            "verified",
        }:
            # Do not emit unverified answers as training truth.
            continue
        rows.append(
            {
                "prompt": "\n".join(prompt_parts)[:8000],
                "completion": answer[:8000],
                "run_id": traj.get("run_id"),
                "source": "verified_trajectory",
                "metadata": {
                    "tool_receipt_count": len(list(traj.get("tool_receipts") or [])),
                    "lifecycle": "CANDIDATE",
                },
            }
        )
    return rows
