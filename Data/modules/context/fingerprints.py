"""Versioned context / stable-prefix fingerprints.

Distinct from Brain identity and canonical history IDs.
Never include timestamps that destroy reuse unless they change semantics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from Data.modules.common.hashing import sha256_text

FINGERPRINT_VERSION = "ctxfp-v1"
CONTEXT_COMPILER_VERSION = "context-compiler-v1"


def _digest(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, str):
        return sha256_text(obj)
    if isinstance(obj, (bytes, bytearray)):
        return sha256_text(obj.decode("utf-8", errors="replace"))
    return sha256_text(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False))


@dataclass(frozen=True)
class StablePrefixInputs:
    model_id: str | None = None
    model_revision: str | None = None
    tokenizer_id: str | None = None
    tokenizer_revision: str | None = None
    chat_template_id: str | None = None
    chat_template_revision: str | None = None
    behavior_profile_version: str | None = None
    behavior_profile_digest: str | None = None
    system_policy_digest: str | None = None
    operator_instruction_digest: str | None = None
    project_instruction_digest: str | None = None
    domain_overlay_digest: str | None = None
    tool_schema_digest: str | None = None
    stable_prefix_content_digest: str | None = None
    context_compiler_version: str = CONTEXT_COMPILER_VERSION

    def fingerprint(self) -> str:
        payload = {
            "v": FINGERPRINT_VERSION,
            "kind": "stable_prefix",
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
            "chat_template_id": self.chat_template_id,
            "chat_template_revision": self.chat_template_revision,
            "behavior_profile_version": self.behavior_profile_version,
            "behavior_profile_digest": self.behavior_profile_digest,
            "system_policy_digest": self.system_policy_digest,
            "operator_instruction_digest": self.operator_instruction_digest,
            "project_instruction_digest": self.project_instruction_digest,
            "domain_overlay_digest": self.domain_overlay_digest,
            "tool_schema_digest": self.tool_schema_digest,
            "stable_prefix_content_digest": self.stable_prefix_content_digest,
            "context_compiler_version": self.context_compiler_version,
        }
        return f"spf:{sha256_text(json.dumps(payload, sort_keys=True))[:40]}"


@dataclass(frozen=True)
class ContextFingerprintInputs:
    stable_prefix_fingerprint: str
    conversation_selection_digest: str | None = None
    retrieval_result_digest: str | None = None
    memory_selection_digest: str | None = None
    evidence_selection_digest: str | None = None
    compaction_artifact_digest: str | None = None
    dynamic_suffix_digest: str | None = None
    security_scope: str | None = None
    project_scope: str | None = None

    def fingerprint(self) -> str:
        payload = {
            "v": FINGERPRINT_VERSION,
            "kind": "full_context",
            "stable": self.stable_prefix_fingerprint,
            "conversation": self.conversation_selection_digest,
            "retrieval": self.retrieval_result_digest,
            "memory": self.memory_selection_digest,
            "evidence": self.evidence_selection_digest,
            "compaction": self.compaction_artifact_digest,
            "dynamic": self.dynamic_suffix_digest,
            "security_scope": self.security_scope,
            "project_scope": self.project_scope,
        }
        return f"cfp:{sha256_text(json.dumps(payload, sort_keys=True))[:40]}"


@dataclass
class CompiledPrefixParts:
    """Deterministic stable prefix vs dynamic suffix split."""

    stable_system: str
    stable_constraints: str
    dynamic_messages: tuple[dict[str, str], ...]
    digests: dict[str, str] = field(default_factory=dict)

    @property
    def stable_text(self) -> str:
        parts = [self.stable_system]
        if self.stable_constraints:
            parts.append(self.stable_constraints)
        return "\n\n".join(p for p in parts if p)

    def stable_content_digest(self) -> str:
        return _digest(self.stable_text)


def digest_text(text: str | None) -> str | None:
    if text is None:
        return None
    return _digest(text)


def digest_messages(messages: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    return _digest([{"role": m.get("role"), "content": m.get("content")} for m in messages])


def digest_items(items: list[Any] | tuple[Any, ...] | None) -> str | None:
    if items is None:
        return None
    return _digest(items)


def build_stable_prefix_fingerprint(
    *,
    model_id: str | None = None,
    model_revision: str | None = None,
    tokenizer_id: str | None = None,
    tokenizer_revision: str | None = None,
    chat_template_id: str | None = None,
    chat_template_revision: str | None = None,
    behavior_profile_prompt: str | None = None,
    behavior_profile_version: str | None = None,
    system_core: str | None = None,
    constraints: str | None = None,
    domain_overlay: str | None = None,
    tool_schema: Any | None = None,
    operator_instructions: str | None = None,
    project_instructions: str | None = None,
) -> tuple[str, StablePrefixInputs]:
    inputs = StablePrefixInputs(
        model_id=model_id,
        model_revision=model_revision,
        tokenizer_id=tokenizer_id,
        tokenizer_revision=tokenizer_revision,
        chat_template_id=chat_template_id,
        chat_template_revision=chat_template_revision,
        behavior_profile_version=behavior_profile_version,
        behavior_profile_digest=digest_text(behavior_profile_prompt),
        system_policy_digest=digest_text(system_core),
        operator_instruction_digest=digest_text(operator_instructions),
        project_instruction_digest=digest_text(project_instructions),
        domain_overlay_digest=digest_text(domain_overlay),
        tool_schema_digest=_digest(tool_schema) if tool_schema is not None else None,
        stable_prefix_content_digest=_digest(
            "\n\n".join(
                p
                for p in (
                    system_core or "",
                    constraints or "",
                    domain_overlay or "",
                )
                if p
            )
        ),
    )
    return inputs.fingerprint(), inputs
