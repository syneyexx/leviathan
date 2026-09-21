"""Final provider-request budget checks (messages + tools + output reserve).

Token estimates use ``reasoning.token_estimate`` (calibrated for NL/code). Character
counts remain available for legacy callers. Exact LM Studio tokenizer IDs stay
model-specific; when capacity is exceeded, callers must surface an honest error
instead of silently clipping protected content.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .context import estimate_chars
from .token_estimate import estimate_tokens, tokens_to_chars

# Conservative estimate when provider capacity is unknown.
DEFAULT_ESTIMATED_CONTEXT_CHARS = 32_000
CHARS_PER_TOKEN_ESTIMATE = 4  # legacy fallback; prefer token_estimate.estimate_tokens


@dataclass(slots=True)
class ProviderBudgetDecision:
    ok: bool
    used_chars: int
    max_chars: int
    reserve_output_chars: int
    capacity_source: str  # model_reported | profile | conservative_estimate
    overflow: bool = False
    truncated: bool = False
    notes: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    used_tokens_est: int | None = None
    max_tokens_est: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Avoid dumping full message bodies into telemetry by default callers.
        data["message_count"] = len(self.messages)
        data.pop("messages", None)
        return data


def tokens_to_reserve_chars(token_budget: int | None, *, cap: int = 8_000, floor: int = 512) -> int:
    """Convert a token output budget into a character reserve with explicit units."""
    if token_budget is None:
        return cap
    chars = tokens_to_chars(int(token_budget), domain="mixed")
    return min(cap, max(floor, chars))


def estimate_tools_chars(tools: list[dict[str, Any]] | None) -> int:
    if not tools:
        return 0
    try:
        return estimate_chars(json.dumps(tools, ensure_ascii=False)) + 64
    except Exception:
        return 256 * len(tools)


def estimate_text_tokens(text: str) -> int:
    """Public helper for callers that need token (not char) estimates."""
    return estimate_tokens(text).tokens


def _estimate_message_chars(message: dict[str, Any]) -> int:
    """Estimate the complete provider-facing message, including tool protocol fields."""
    try:
        return estimate_chars(json.dumps(message, ensure_ascii=False, separators=(",", ":"))) + 24
    except Exception:
        # Fail conservatively when an unusual provider value is not JSON serializable.
        return estimate_chars(str(message)) + 128


def estimate_payload_chars(payload: dict[str, Any]) -> int:
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    msg_chars = sum(_estimate_message_chars(item) for item in messages if isinstance(item, dict))
    tools_chars = estimate_tools_chars(payload.get("tools") if isinstance(payload.get("tools"), list) else None)
    # Protocol / framing overhead not represented directly in JSON bodies.
    overhead = 256 + 24 * len(messages)
    return msg_chars + tools_chars + overhead


def _assistant_tool_call_ids(message: dict[str, Any]) -> set[str]:
    if str(message.get("role") or "") != "assistant":
        return set()
    calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
    return {
        str(item.get("id") or "")
        for item in calls
        if isinstance(item, dict) and str(item.get("id") or "")
    }


def _tool_exchange_group(messages: list[dict[str, Any]], index: int) -> set[int]:
    """Return indices that must be dropped together to keep tool protocol valid."""
    item = messages[index]
    call_ids = _assistant_tool_call_ids(item)
    assistant_index: int | None = index if call_ids else None

    if str(item.get("role") or "") == "tool":
        tool_call_id = str(item.get("tool_call_id") or "")
        if tool_call_id:
            for candidate_index in range(index - 1, -1, -1):
                candidate_ids = _assistant_tool_call_ids(messages[candidate_index])
                if tool_call_id in candidate_ids:
                    assistant_index = candidate_index
                    call_ids = candidate_ids
                    break

    if assistant_index is None or not call_ids:
        return {index}

    group = {assistant_index}
    for candidate_index, candidate in enumerate(messages):
        if str(candidate.get("role") or "") != "tool":
            continue
        if str(candidate.get("tool_call_id") or "") in call_ids:
            group.add(candidate_index)
    return group


def resolve_context_capacity_chars(
    *,
    profile_context_chars: int | None,
    model_context_chars: int | None = None,
) -> tuple[int, str]:
    """Pick the tightest known capacity. Unlimited profile → still bound by model or estimate."""
    if model_context_chars is not None and int(model_context_chars) > 0:
        model_cap = int(model_context_chars)
        if profile_context_chars is None:
            return model_cap, "model_reported"
        return min(int(profile_context_chars), model_cap), "profile_and_model"
    if profile_context_chars is None:
        return DEFAULT_ESTIMATED_CONTEXT_CHARS, "conservative_estimate"
    return int(profile_context_chars), "profile"


def enforce_provider_payload_budget(
    payload: dict[str, Any],
    *,
    max_chars: int,
    reserve_output_chars: int,
    capacity_source: str,
    protect_roles: frozenset[str] = frozenset({"system"}),
    allow_truncate: bool = True,
) -> ProviderBudgetDecision:
    """Ensure a final provider payload fits capacity + output reserve, or report overflow.

    Older non-protected context may be dropped. Protected messages — especially the
    explicit system prompt — are never shortened or silently rewritten. Native tool
    call assistant messages and their ``role=tool`` responses are atomic protocol
    groups: trimming never leaves an orphaned half-exchange.

    If mandatory content cannot fit the provider/model capacity, ``ok=False`` is
    returned so the caller can surface an honest capacity error instead of changing
    user instructions.

    ``allow_truncate`` is retained for API compatibility; this function deliberately
    does not truncate protected message content.
    """
    _ = allow_truncate
    body = {**payload, "messages": [dict(item) for item in (payload.get("messages") or [])]}
    capacity = max(0, int(max_chars))
    reserve = max(0, int(reserve_output_chars))
    usable = max(0, capacity - reserve)
    notes: list[str] = []
    if reserve >= capacity:
        notes.append("output_reserve_exhausts_capacity")
    truncated = False

    def _used() -> int:
        return estimate_payload_chars(body)

    # Drop oldest removable history first. Tool call/result exchanges are atomic.
    while _used() > usable and len(body["messages"]) > 2:
        drop_indices: set[int] | None = None
        messages = body["messages"]
        last_index = len(messages) - 1
        for index, item in enumerate(messages):
            role = str(item.get("role") or "")
            if role in protect_roles or index == last_index:
                continue
            group = _tool_exchange_group(messages, index)
            if last_index in group:
                continue
            if any(str(messages[group_index].get("role") or "") in protect_roles for group_index in group):
                continue
            drop_indices = group
            break
        if not drop_indices:
            break
        dropped_roles = [str(messages[index].get("role") or "") for index in sorted(drop_indices)]
        for index in sorted(drop_indices, reverse=True):
            messages.pop(index)
        for role in dropped_roles:
            notes.append(f"dropped_message_role:{role}")
        if len(drop_indices) > 1:
            notes.append("dropped_tool_exchange_atomically")
        truncated = True

    used = _used()
    used_tokens = estimate_tokens(json.dumps(body.get("messages") or [], ensure_ascii=False)).tokens
    max_tokens_est = max(1, int(round(capacity / CHARS_PER_TOKEN_ESTIMATE))) if capacity else 0
    if used > usable:
        notes.append("provider_request_overflow")
        notes.append(f"token_estimate_used:{used_tokens}")
        notes.append("context_limit_exceeded_explicit")
        if any(str(item.get("role") or "") in protect_roles for item in body["messages"]):
            notes.append("protected_prompt_preserved")
        return ProviderBudgetDecision(
            ok=False,
            used_chars=used,
            max_chars=int(max_chars),
            reserve_output_chars=int(reserve_output_chars),
            capacity_source=capacity_source,
            overflow=True,
            truncated=truncated,
            notes=notes,
            messages=body["messages"],
            used_tokens_est=used_tokens,
            max_tokens_est=max_tokens_est,
        )
    if truncated:
        notes.append("provider_request_trimmed")
    return ProviderBudgetDecision(
        ok=True,
        used_chars=used,
        max_chars=int(max_chars),
        reserve_output_chars=int(reserve_output_chars),
        capacity_source=capacity_source,
        overflow=False,
        truncated=truncated,
        notes=notes,
        messages=body["messages"],
        used_tokens_est=used_tokens,
        max_tokens_est=max_tokens_est,
    )


def estimate_chat_payload_system_chars(profile: dict[str, Any], reasoning: str = "standard") -> int:
    """Estimate chars that chat_payload will prepend (profile/override + reasoning note)."""
    settings_prompt = str(profile.get("_conversation_system_prompt") or profile.get("system_prompt") or "")
    # Approximate the reasoning note length (stable upper bound).
    reasoning_note_chars = 420 if reasoning == "maximum" else 180
    return estimate_chars(settings_prompt) + reasoning_note_chars + 64
