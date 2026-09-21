"""Model profile validation and persistence helpers."""

from __future__ import annotations

from typing import Any

from Data.modules.models.contracts import ModelProfile
from Data.modules.models.errors import VALIDATION_ERROR, ModelControlError
from Data.modules.models.store import ModelStore, utc_now


DEFAULT_PROFILE = {
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "max_tokens": 2048,
    "repeat_penalty": 1.05,
    "seed": -1,
    "system_prompt": "",
}


def validate_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def require_number(name: str, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ModelControlError(
                code=VALIDATION_ERROR,
                message=f"{name} must be a number",
                http_status=422,
            )
        return float(value)

    temperature = require_number("temperature", payload.get("temperature", DEFAULT_PROFILE["temperature"]))
    if not 0.0 <= temperature <= 2.0:
        raise ModelControlError(code=VALIDATION_ERROR, message="temperature must be 0–2", http_status=422)

    top_p = require_number("topP", payload.get("topP", payload.get("top_p", DEFAULT_PROFILE["top_p"])))
    if not 0.0 < top_p <= 1.0:
        raise ModelControlError(code=VALIDATION_ERROR, message="topP must be >0 and ≤1", http_status=422)

    top_k_raw = payload.get("topK", payload.get("top_k", DEFAULT_PROFILE["top_k"]))
    if isinstance(top_k_raw, bool) or not isinstance(top_k_raw, int):
        raise ModelControlError(code=VALIDATION_ERROR, message="topK must be an integer", http_status=422)
    top_k = int(top_k_raw)
    if not 0 <= top_k <= 500:
        raise ModelControlError(code=VALIDATION_ERROR, message="topK must be 0–500", http_status=422)

    max_tokens_raw = payload.get("maxTokens", payload.get("max_tokens", DEFAULT_PROFILE["max_tokens"]))
    if isinstance(max_tokens_raw, bool) or not isinstance(max_tokens_raw, int):
        raise ModelControlError(code=VALIDATION_ERROR, message="maxTokens must be an integer", http_status=422)
    max_tokens = int(max_tokens_raw)
    if not 1 <= max_tokens <= 131072:
        raise ModelControlError(code=VALIDATION_ERROR, message="maxTokens must be 1–131072", http_status=422)

    repeat = require_number(
        "repeatPenalty",
        payload.get("repeatPenalty", payload.get("repeat_penalty", DEFAULT_PROFILE["repeat_penalty"])),
    )
    if not 0.5 <= repeat <= 2.0:
        raise ModelControlError(code=VALIDATION_ERROR, message="repeatPenalty must be 0.5–2", http_status=422)

    seed_raw = payload.get("seed", DEFAULT_PROFILE["seed"])
    if isinstance(seed_raw, bool) or not isinstance(seed_raw, int):
        raise ModelControlError(code=VALIDATION_ERROR, message="seed must be an integer", http_status=422)
    seed = int(seed_raw)
    if not -1 <= seed <= 2147483647:
        raise ModelControlError(code=VALIDATION_ERROR, message="seed must be -1–2147483647", http_status=422)

    system_prompt = payload.get("systemPrompt", payload.get("system_prompt", ""))
    if system_prompt is None:
        system_prompt = ""
    if not isinstance(system_prompt, str):
        raise ModelControlError(code=VALIDATION_ERROR, message="systemPrompt must be a string", http_status=422)
    if len(system_prompt) > 500_000:
        raise ModelControlError(
            code=VALIDATION_ERROR,
            message="systemPrompt exceeds 500,000 character storage ceiling",
            http_status=422,
        )

    return {
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "max_tokens": max_tokens,
        "repeat_penalty": repeat,
        "seed": seed,
        "system_prompt": system_prompt,
    }


class ProfileService:
    def __init__(self, store: ModelStore) -> None:
        self.store = store

    def get_or_default(self, model_id: str) -> ModelProfile:
        row = self.store.get_profile(model_id)
        if not row:
            return ModelProfile(model_id=model_id, **DEFAULT_PROFILE)  # type: ignore[arg-type]
        return ModelProfile(
            model_id=model_id,
            temperature=float(row["temperature"]),
            top_p=float(row["top_p"]),
            top_k=int(row["top_k"]),
            max_tokens=int(row["max_tokens"]),
            repeat_penalty=float(row["repeat_penalty"]),
            seed=int(row["seed"]),
            system_prompt=str(row["system_prompt"] or ""),
            active=bool(row["active"]),
            updated_at=row["updated_at"],
        )

    def save(self, model_id: str, payload: dict[str, Any], *, activate: bool = False) -> ModelProfile:
        validated = validate_profile_payload(payload)
        if activate:
            self.store.clear_active_profiles()
        record = {
            "model_id": model_id,
            **validated,
            "active": activate,
        }
        self.store.upsert_profile(record)
        profile = self.get_or_default(model_id)
        profile.updated_at = utc_now()
        return profile
