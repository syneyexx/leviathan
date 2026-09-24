"""BehaviorSettingsResolver — persistent settings -> immutable BehaviorSnapshot.

A chat turn receives one immutable snapshot. No component may invent identity defaults.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .behavior import DEFAULT_BEHAVIOR_PROFILE, BehaviorProfile
from .seed import SEED_LANGUAGE_FALLBACK, SEED_SYSTEM_PROMPT

_NL_MARKERS = re.compile(
    r"\b(wat|hoe|waar|wanneer|waarom|wie|jou|jij|je|het|een|van|met|"
    r"antwoord|alleen|exact|goedemorgen|goedenavond|alsjeblieft|bedankt|"
    r"nederlands|hallo|dag|naam)\b",
    re.IGNORECASE,
)
_EN_MARKERS = re.compile(
    r"\b(what|how|where|when|why|who|your|you|the|a|an|with|from|"
    r"answer|only|exactly|please|thanks|hello|hi|name|english)\b",
    re.IGNORECASE,
)
_EXPLICIT_LANG = re.compile(
    r"(?:answer|reply|respond|schrijf|antwoord)\s+(?:in|op)\s+"
    r"(english|dutch|nederlands|duits|german|french|français|spanish|español)",
    re.IGNORECASE,
)
_NOW_ENGLISH = re.compile(
    r"(?i)\b(now\s+answer\s+in\s+english|antwoord\s+(?:nu\s+)?in\s+(?:het\s+)?engels)\b"
)


@dataclass(frozen=True)
class LanguageDecision:
    mode: str
    response_language: str
    source: str
    reason: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "response_language": self.response_language,
            "source": self.source,
            "reason": self.reason,
        }

    def instruction(self) -> str:
        lang = self.response_language
        if not lang or lang in {"auto", "und"}:
            return (
                "Reply in the language of the latest user message. "
                "Internal English configuration must not force English output."
            )
        names = {"en": "English", "nl": "Dutch", "de": "German", "fr": "French", "es": "Spanish"}
        label = names.get(lang, lang)
        return (
            f"Reply in {label}. "
            "Internal English configuration must not force a different output language."
        )


@dataclass(frozen=True)
class BehaviorSnapshot:
    """Immutable effective behavior for one chat turn / operation."""

    profile: BehaviorProfile
    settings_hash: str
    version: str
    language: LanguageDecision
    system_prompt: str
    resolved_at: str = ""
    source: str = "behavior_store"

    def public_dict(self, *, include_prompt: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "settings_hash": self.settings_hash,
            "version": self.version,
            "language": self.language.public_dict(),
            "assistant_display_name": self.profile.assistant_display_name,
            "source": self.source,
            "resolved_at": self.resolved_at,
            "truth": {
                "behavior_is_not_authority": True,
                "snapshot_is_immutable": True,
                "identity_from_settings_only": True,
            },
        }
        if include_prompt:
            data["system_prompt"] = self.system_prompt
            data["profile"] = self.profile.public_dict(include_prompt=True)
        return data


def detect_message_language(text: str) -> tuple[str, str]:
    """Return (lang_code, reason) for a user message."""
    raw = (text or "").strip()
    if not raw:
        return "und", "empty"
    if _NOW_ENGLISH.search(raw):
        return "en", "explicit_user_request"
    explicit = _EXPLICIT_LANG.search(raw)
    if explicit:
        token = explicit.group(1).lower()
        mapping = {
            "english": "en",
            "dutch": "nl",
            "nederlands": "nl",
            "german": "de",
            "duits": "de",
            "french": "fr",
            "français": "fr",
            "spanish": "es",
            "español": "es",
        }
        return mapping.get(token, token[:2]), "explicit_user_request"
    nl = len(_NL_MARKERS.findall(raw))
    en = len(_EN_MARKERS.findall(raw))
    if any(ch in raw.lower() for ch in "ëïöüáéíóúàè"):
        nl += 1
    if nl > en and nl > 0:
        return "nl", "marker_score"
    if en > nl and en > 0:
        return "en", "marker_score"
    if nl == en and nl > 0:
        if re.search(r"\b(jou|jij|hoe gaat|wat is)\b", raw, re.IGNORECASE):
            return "nl", "dutch_pronoun_tiebreak"
        return "en", "english_tiebreak"
    return "und", "ambiguous"


def resolve_language(
    profile: BehaviorProfile,
    *,
    latest_user_message: str,
    recent_user_messages: list[str] | None = None,
) -> LanguageDecision:
    mode = (profile.language_mode or "auto_follow_user").strip()
    if mode == "explicit":
        lang = (profile.language_explicit or profile.language_fallback or SEED_LANGUAGE_FALLBACK).strip()
        return LanguageDecision(mode=mode, response_language=lang, source="settings", reason="explicit_configured")

    detected, reason = detect_message_language(latest_user_message)
    if reason == "explicit_user_request":
        return LanguageDecision(
            mode=mode if mode in {"auto_follow_user", "custom"} else "auto_follow_user",
            response_language=detected,
            source="user_override",
            reason=reason,
        )
    if detected != "und":
        return LanguageDecision(
            mode=mode if mode in {"auto_follow_user", "custom"} else "auto_follow_user",
            response_language=detected,
            source="latest_user",
            reason=reason,
        )
    if profile.language_follow_latest_user:
        for prev in reversed(recent_user_messages or []):
            detected, reason = detect_message_language(prev)
            if detected != "und":
                return LanguageDecision(
                    mode="auto_follow_user",
                    response_language=detected,
                    source="recent_conversation",
                    reason=reason,
                )
    fb = profile.language_fallback or SEED_LANGUAGE_FALLBACK
    return LanguageDecision(mode="auto_follow_user", response_language=fb, source="fallback", reason="ambiguous_fallback")


class BehaviorSettingsResolver:
    """Resolve persistent BehaviorProfile into an immutable per-turn snapshot."""

    def __init__(self, behavior_store: Any | None = None) -> None:
        self._store = behavior_store
        self._lock = threading.RLock()
        self._cache_hash: str | None = None
        self._cache_profile: BehaviorProfile | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._cache_hash = None
            self._cache_profile = None

    def bind_store(self, behavior_store: Any) -> None:
        with self._lock:
            self._store = behavior_store
            self._cache_hash = None
            self._cache_profile = None

    def get_profile(self) -> BehaviorProfile:
        with self._lock:
            if self._store is None:
                return DEFAULT_BEHAVIOR_PROFILE
            profile = self._store.get_effective()
            if not isinstance(profile, BehaviorProfile):
                return DEFAULT_BEHAVIOR_PROFILE
            hashed = profile if profile.hash else profile.with_hash()
            if self._cache_hash == hashed.hash and self._cache_profile is not None:
                return self._cache_profile
            self._cache_hash = hashed.hash
            self._cache_profile = hashed
            return hashed

    def resolve(
        self,
        *,
        latest_user_message: str = "",
        recent_user_messages: list[str] | None = None,
        overlays: list[str] | None = None,
    ) -> BehaviorSnapshot:
        profile = self.get_profile()
        language = resolve_language(
            profile,
            latest_user_message=latest_user_message,
            recent_user_messages=recent_user_messages,
        )
        parts: list[str] = [profile.composed_system_prompt()]
        if profile.project_identity.strip():
            parts.append(f"Project/organization identity: {profile.project_identity.strip()}")
        if profile.describe_as_local_ai:
            parts.append("You may describe yourself as a local AI control-plane assistant when asked.")
        if profile.greeting_behavior:
            parts.append(f"Greeting behavior: {profile.greeting_behavior}.")
        if profile.self_description_behavior:
            parts.append(f"Self-description behavior: {profile.self_description_behavior}.")
        if profile.project_prompt_overlays:
            parts.append("Project overlays:\n" + "\n".join(profile.project_prompt_overlays))
        if profile.task_prompt_overlays:
            parts.append("Task overlays:\n" + "\n".join(profile.task_prompt_overlays))
        if overlays:
            parts.extend(o.strip() for o in overlays if o and o.strip())
        if language.mode == "custom" and profile.language_custom_policy.strip():
            parts.append(f"Language policy: {profile.language_custom_policy.strip()}")
        parts.append(language.instruction())
        system_prompt = "\n\n".join(p for p in parts if p and str(p).strip())
        return BehaviorSnapshot(
            profile=profile,
            settings_hash=profile.hash or profile.compute_hash(),
            version=str(profile.version),
            language=language,
            system_prompt=system_prompt or SEED_SYSTEM_PROMPT,
            resolved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source="behavior_store" if self._store is not None else "seed",
        )


def snapshot_hash(snapshot: BehaviorSnapshot) -> str:
    blob = json.dumps(
        {
            "settings_hash": snapshot.settings_hash,
            "language": snapshot.language.public_dict(),
            "system_prompt_sha": hashlib.sha256(snapshot.system_prompt.encode("utf-8")).hexdigest(),
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
