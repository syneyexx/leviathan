"""Phase 6: verified HADES experiences → neural-memory learning signals.

Reuses ``gen2.verified_experience`` admission rules instead of inventing a
parallel store. Experiences are data-only: no hidden chain-of-thought, no
permission/policy authority.

Reward signals are explicit deterministic outcomes (tests/verification/status),
not model self-scores.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from neural.encoding import SlowMemoryExample
from neural.errors import NeuralError
from neural.samples import HIDDEN_RECORD_KEYS, redact_sample_text, strip_hidden_fields

# Conservative personal-data heuristics for Slow Memory consolidation.
# Exact Memory remains the place for user-specific durable facts.
_PERSONAL_DATA_RE = re.compile(
    r"(?i)\b("
    r"ssn|social\s*security|"
    r"passport\s*(no|number|#)?|"
    r"date\s*of\s*birth|dob|"
    r"home\s*address|street\s*address|"
    r"phone\s*number|mobile\s*number|"
    r"credit\s*card|iban|bank\s*account|"
    r"my\s+email\s+is|personal\s+email"
    r")\b"
)


class NeuralExperienceError(NeuralError):
    code = "neural_experience_error"


class ExperienceOutcome(str, Enum):
    """Outcome classes for verified-experience learning.

    Prefer these semantic buckets over collapsing everything into one scalar.
    ``PARTIAL`` / ``REJECTED`` extend earlier Phase 6 values without renaming
    existing verified_* members (call sites and checkpoints stay compatible).
    """

    VERIFIED_SUCCESS = "verified_success"  # SUCCESS with external verification
    VERIFIED_FAILURE = "verified_failure"  # FAILURE with external verification
    UNVERIFIED_SUCCESS = "unverified_success"
    PARTIAL = "partial"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"  # legacy alias-adjacent to PARTIAL
    UNKNOWN = "unknown"


class RewardLabel(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True)
class ExperienceReward:
    """Inspectable reward derived from deterministic HADES outcome signals."""

    label: RewardLabel
    score: float  # [-1, 1]
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["label"] = self.label.value
        return payload


@dataclass(frozen=True)
class NeuralExperience:
    """Externally meaningful execution experience for neural memory experiments."""

    experience_id: str
    outcome: ExperienceOutcome
    reward: ExperienceReward
    problem_class: str
    strategy: str
    verification: str
    result_summary: str
    tools: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    run_id: str = ""
    source: str = "verified_experience"
    verified: bool = False
    contains_chain_of_thought: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "outcome": self.outcome.value,
            "reward": self.reward.to_dict(),
            "problem_class": self.problem_class,
            "strategy": self.strategy,
            "verification": self.verification,
            "result_summary": self.result_summary,
            "tools": list(self.tools),
            "files": list(self.files),
            "run_id": self.run_id,
            "source": self.source,
            "verified": self.verified,
            "contains_chain_of_thought": self.contains_chain_of_thought,
            "metadata": dict(self.metadata),
        }


def _clip(text: str, limit: int = 400) -> str:
    value = " ".join(str(text or "").split())
    if len(value) > limit:
        return value[: max(32, limit - 1)].rstrip() + "…"
    return value


def reward_from_signals(
    *,
    tests_passed: bool | None = None,
    tests_failed: bool | None = None,
    verification_accepted: bool | None = None,
    verification_rejected: bool | None = None,
    regression_detected: bool | None = None,
    tool_action_blocked: bool | None = None,
    patch_applied: bool | None = None,
    patch_reverted: bool | None = None,
    task_completed: bool | None = None,
    task_incomplete: bool | None = None,
    terminal_status: str | None = None,
) -> ExperienceReward:
    """Map explicit outcome flags to a bounded reward.

    Prefer false negatives for learning eligibility: missing verification → ineligible.
    """
    signals = {
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "verification_accepted": verification_accepted,
        "verification_rejected": verification_rejected,
        "regression_detected": regression_detected,
        "tool_action_blocked": tool_action_blocked,
        "patch_applied": patch_applied,
        "patch_reverted": patch_reverted,
        "task_completed": task_completed,
        "task_incomplete": task_incomplete,
        "terminal_status": terminal_status,
    }
    if tool_action_blocked or regression_detected or patch_reverted or verification_rejected or tests_failed:
        return ExperienceReward(label=RewardLabel.NEGATIVE, score=-1.0, signals=signals)
    if verification_accepted and (
        tests_passed or task_completed or str(terminal_status or "").lower() in {"completed", "success", "passed"}
    ):
        score = 1.0 if tests_passed else 0.8
        return ExperienceReward(label=RewardLabel.POSITIVE, score=score, signals=signals)
    if verification_accepted is None and (task_completed or tests_passed):
        # Completed without verification evidence → not eligible for durable learning.
        return ExperienceReward(label=RewardLabel.INELIGIBLE, score=0.0, signals=signals)
    if task_incomplete or str(terminal_status or "").lower() in {"cancelled", "canceled", "incomplete"}:
        return ExperienceReward(label=RewardLabel.NEUTRAL, score=0.0, signals=signals)
    return ExperienceReward(label=RewardLabel.INELIGIBLE, score=0.0, signals=signals)


def _outcome_from_verified_metadata(outcome: str) -> ExperienceOutcome:
    value = str(outcome or "").strip().lower()
    if value in {"verified_success", "success", "completed"}:
        return ExperienceOutcome.VERIFIED_SUCCESS
    if value in {"verified_failure", "failure", "failed"}:
        return ExperienceOutcome.VERIFIED_FAILURE
    if value in {"partial"}:
        return ExperienceOutcome.PARTIAL
    if value in {"rejected"}:
        return ExperienceOutcome.REJECTED
    if value in {"blocked"}:
        return ExperienceOutcome.BLOCKED
    if value in {"cancelled", "canceled"}:
        return ExperienceOutcome.CANCELLED
    if value in {"incomplete"}:
        return ExperienceOutcome.INCOMPLETE
    return ExperienceOutcome.UNKNOWN


def _parse_context_content(content: str) -> dict[str, str]:
    fields = {
        "task": "",
        "summary": "",
        "verification": "",
        "tools": "",
        "files": "",
        "outcome": "",
    }
    for line in str(content or "").splitlines():
        lower = line.lower()
        if lower.startswith("task:"):
            fields["task"] = line.split(":", 1)[1].strip()
        elif lower.startswith("observed result:"):
            fields["summary"] = line.split(":", 1)[1].strip()
        elif lower.startswith("verification:"):
            fields["verification"] = line.split(":", 1)[1].strip()
        elif lower.startswith("tools:"):
            fields["tools"] = line.split(":", 1)[1].strip()
        elif lower.startswith("files/artifacts:") or lower.startswith("files:"):
            fields["files"] = line.split(":", 1)[1].strip()
        elif lower.startswith("outcome:"):
            fields["outcome"] = line.split(":", 1)[1].strip()
    return fields


def _assert_no_hidden_keys(payload: Mapping[str, Any], *, path: str = "") -> None:
    for key, value in payload.items():
        key_l = str(key).lower()
        if key_l in HIDDEN_RECORD_KEYS:
            raise NeuralExperienceError(
                "hidden reasoning key present in experience payload",
                detail={"key": key, "path": path},
            )
        if isinstance(value, dict):
            _assert_no_hidden_keys(value, path=f"{path}.{key}" if path else str(key))


def neural_experience_from_verified_item(item: Mapping[str, Any]) -> NeuralExperience:
    """Convert a ``VerifiedExperience.to_context_item()`` payload into a neural experience."""
    from gen2.verified_experience import training_record_from_experience

    safe_item = strip_hidden_fields(dict(item))
    _assert_no_hidden_keys(safe_item)
    meta = dict(safe_item.get("metadata") or {})
    if meta.get("hidden_reasoning_stored"):
        raise NeuralExperienceError("experience claims hidden reasoning was stored")

    record = training_record_from_experience(safe_item)
    if record.get("contains_chain_of_thought"):
        raise NeuralExperienceError("verified experience unexpectedly marked as containing CoT")

    parsed = _parse_context_content(str(safe_item.get("content") or ""))
    outcome = _outcome_from_verified_metadata(str(meta.get("outcome") or record.get("outcome") or parsed["outcome"]))
    # Externally verified outcomes (success *or* failure/blocked) count as verified
    # for learning gates; only VERIFIED_SUCCESS is positive success memory.
    externally_verified = outcome in {
        ExperienceOutcome.VERIFIED_SUCCESS,
        ExperienceOutcome.VERIFIED_FAILURE,
        ExperienceOutcome.BLOCKED,
    }
    verification_text = _clip(parsed["verification"])
    tests_passed = None
    if outcome is ExperienceOutcome.VERIFIED_SUCCESS:
        tests_passed = bool(re.search(r"\bpass(ed|ing)?\b", verification_text, re.I)) or True
    reward = reward_from_signals(
        verification_accepted=True if outcome is ExperienceOutcome.VERIFIED_SUCCESS else None,
        verification_rejected=True if outcome is ExperienceOutcome.VERIFIED_FAILURE else None,
        tool_action_blocked=True if outcome is ExperienceOutcome.BLOCKED else None,
        task_completed=outcome is ExperienceOutcome.VERIFIED_SUCCESS,
        tests_passed=tests_passed if outcome is ExperienceOutcome.VERIFIED_SUCCESS else None,
        tests_failed=True if outcome is ExperienceOutcome.VERIFIED_FAILURE else None,
        terminal_status="completed" if outcome is ExperienceOutcome.VERIFIED_SUCCESS else str(meta.get("outcome") or ""),
    )
    if not externally_verified:
        reward = ExperienceReward(label=RewardLabel.INELIGIBLE, score=0.0, signals=reward.signals)
    # Verified failures / blocked must retain NEGATIVE reward (never collapse to ineligible).
    if outcome in {ExperienceOutcome.VERIFIED_FAILURE, ExperienceOutcome.BLOCKED} and reward.label is not RewardLabel.NEGATIVE:
        reward = ExperienceReward(label=RewardLabel.NEGATIVE, score=-1.0, signals=reward.signals)

    tools = tuple(part.strip() for part in parsed["tools"].split(",") if part.strip())[:16]
    files = tuple(part.strip() for part in parsed["files"].split(",") if part.strip())[:16]
    problem = _clip(parsed["task"] or "unspecified_task")
    strategy = _clip(
        f"tools={','.join(tools)}; files={','.join(files)}" if (tools or files) else "strategy_unspecified"
    )
    result_summary = _clip(parsed["summary"])
    run_id = str(meta.get("run_id") or record.get("run_id") or "")
    experience_id = str(safe_item.get("item_id") or f"experience:{run_id}")

    # Belt-and-suspenders: never persist CoT-looking blobs in public fields.
    public_blob = " ".join([problem, strategy, verification_text, result_summary]).lower()
    for banned in ("chain_of_thought", "scratchpad", "internal_reasoning"):
        if banned in public_blob:
            raise NeuralExperienceError("forbidden reasoning marker leaked into experience text")

    return NeuralExperience(
        experience_id=experience_id,
        outcome=outcome,
        reward=reward,
        problem_class=problem,
        strategy=strategy,
        verification=verification_text,
        result_summary=result_summary,
        tools=tools,
        files=files,
        run_id=run_id,
        source="verified_experience",
        verified=externally_verified,
        contains_chain_of_thought=False,
        metadata={
            "failure_taxonomy": meta.get("failure_taxonomy"),
            "components": list(meta.get("components") or []),
            "instruction_authority": False,
            "data_only": True,
            "provenance": str(safe_item.get("provenance") or ""),
            "failure_memory": outcome in {
                ExperienceOutcome.VERIFIED_FAILURE,
                ExperienceOutcome.BLOCKED,
            },
        },
    )


def experience_text_blob(experience: NeuralExperience) -> str:
    """Flatten experience fields used by secret / personal-data gates."""
    parts = [
        experience.problem_class,
        experience.strategy,
        experience.verification,
        experience.result_summary,
        " ".join(experience.tools),
        " ".join(experience.files),
    ]
    meta = experience.metadata or {}
    for key in ("content", "notes", "summary", "user_text"):
        if key in meta:
            parts.append(str(meta.get(key) or ""))
    return "\n".join(p for p in parts if p)


def contains_secret_material(text: str) -> bool:
    """True when Dataset Brain redaction would change the text."""
    raw = text or ""
    redacted = redact_sample_text(raw)
    return redacted != raw


def contains_personal_data(text: str) -> bool:
    return bool(_PERSONAL_DATA_RE.search(text or ""))


def experience_to_slow_example(experience: NeuralExperience) -> SlowMemoryExample | None:
    """Map a verified positive experience to a slow-memory key/value pair."""
    if not experience.verified or experience.reward.label is not RewardLabel.POSITIVE:
        return None
    if experience.contains_chain_of_thought:
        return None
    blob = experience_text_blob(experience)
    if contains_secret_material(blob) or contains_personal_data(blob):
        return None
    key = experience.problem_class
    value = _clip(
        f"strategy: {experience.strategy} | result: {experience.result_summary} | verification: {experience.verification}",
        limit=600,
    )
    if not key or not value:
        return None
    return SlowMemoryExample(
        example_id=f"exp-slow:{experience.experience_id}",
        key_text=key,
        value_text=value,
        split="train",
        source_sample_id=experience.experience_id,
        sample_type="verified_experience",
    )


def experience_to_negative_slow_example(experience: NeuralExperience) -> SlowMemoryExample | None:
    """Map a verified failure / blocked execution to a *negative* Slow sample.

    Negative samples must never be treated as positive success memory. The value
    text is an avoidance signal (what failed), not a recommended strategy.
    """
    if experience.contains_chain_of_thought:
        return None
    if experience.reward.label is not RewardLabel.NEGATIVE:
        return None
    if experience.outcome not in {
        ExperienceOutcome.VERIFIED_FAILURE,
        ExperienceOutcome.BLOCKED,
        ExperienceOutcome.REJECTED,
    }:
        return None
    # Failures are externally verified outcomes even when not "success".
    if experience.outcome is ExperienceOutcome.VERIFIED_FAILURE and not experience.verified:
        return None
    blob = experience_text_blob(experience)
    if contains_secret_material(blob) or contains_personal_data(blob):
        return None
    key = experience.problem_class
    value = _clip(
        f"AVOID: strategy={experience.strategy} | failed_result={experience.result_summary} | "
        f"verification={experience.verification}",
        limit=600,
    )
    if not key or not value:
        return None
    return SlowMemoryExample(
        example_id=f"exp-slow-neg:{experience.experience_id}",
        key_text=key,
        value_text=value,
        split="train",
        source_sample_id=experience.experience_id,
        sample_type="verified_failure_avoidance",
    )


def experience_eligible_for_fast_memory(experience: NeuralExperience) -> bool:
    """Conservative gate: only verified positive experiences may propose fast writes."""
    return bool(
        experience.verified
        and experience.reward.label is RewardLabel.POSITIVE
        and not experience.contains_chain_of_thought
        and experience.reward.score > 0
        and experience.outcome is ExperienceOutcome.VERIFIED_SUCCESS
    )


def experiences_from_store(store: Any, query: str, *, limit: int = 8) -> list[NeuralExperience]:
    """Retrieve verified experiences and project them into neural experience records."""
    from gen2.verified_experience import retrieve_verified_experiences

    items = retrieve_verified_experiences(store, query, limit=limit)
    out: list[NeuralExperience] = []
    for item in items:
        try:
            out.append(neural_experience_from_verified_item(item))
        except NeuralExperienceError:
            continue
    return out


def apply_experience_to_fast_session(
    session: Any,
    experience: NeuralExperience,
    *,
    key_vector: Any,
    value_vector: Any,
    source_reliability: float = 0.8,
) -> Any:
    """Offer one experience to a FastMemorySession (vectors pre-encoded by caller)."""
    verified = experience_eligible_for_fast_memory(experience)
    return session.consider_write(
        key_vector,
        value_vector,
        verified=verified,
        source_reliability=source_reliability if verified else 0.0,
        sample_id=experience.experience_id,
    )
