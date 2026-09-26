"""Skills — procedural reusable plans from repeated VERIFIED runs (W8).

No hidden CoT. Skill contains trigger, preconditions, capabilities, steps,
source run ids, measured success rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class Skill:
    skill_id: str
    name: str
    trigger: str
    preconditions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    source_run_ids: tuple[str, ...] = ()
    success_count: int = 0
    attempt_count: int = 0
    domain: str | None = None
    trust_state: str = "AGENT_PROPOSED"

    @property
    def measured_success_rate(self) -> float | None:
        if self.attempt_count <= 0:
            return None
        return round(self.success_count / self.attempt_count, 4)

    def public_dict(self) -> dict[str, Any]:
        rate = self.measured_success_rate
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "trigger": self.trigger,
            "preconditions": list(self.preconditions),
            "capabilities": list(self.capabilities),
            "steps": list(self.steps),
            "source_run_ids": list(self.source_run_ids),
            "success_count": self.success_count,
            "attempt_count": self.attempt_count,
            "measured_success_rate": rate,
            "domain": self.domain,
            "trust_state": self.trust_state,
            "truth": {
                "no_hidden_cot": True,
                "success_rate_is_measured": rate is not None,
                "unverified_skill_is_not_authority": self.trust_state != "VERIFIED",
            },
        }


class SkillLibrary:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def derive_from_verified_runs(
        self,
        runs: Sequence[dict[str, Any]],
        *,
        min_repeats: int = 2,
    ) -> list[Skill]:
        """Group VERIFIED successful runs by domain+goal fingerprint."""
        buckets: dict[str, list[dict[str, Any]]] = {}
        for run in runs:
            if str(run.get("verification_status") or run.get("status") or "").upper() not in {
                "VERIFIED",
                "COMPLETED_VERIFIED",
                "PASSED",
            }:
                continue
            domain = str(run.get("domain") or "general")
            goal = str(run.get("goal") or run.get("task_summary") or "")[:120]
            key = f"{domain}::{goal.lower()}"
            buckets.setdefault(key, []).append(run)

        derived: list[Skill] = []
        for key, group in buckets.items():
            if len(group) < min_repeats:
                continue
            domain, _, goal = key.partition("::")
            steps: list[str] = []
            caps: list[str] = []
            run_ids: list[str] = []
            successes = 0
            for run in group:
                run_ids.append(str(run.get("run_id") or ""))
                if run.get("success") is not False:
                    successes += 1
                for step in run.get("steps") or run.get("plan_steps") or []:
                    s = str(step)
                    if s and s not in steps:
                        steps.append(s)
                for cap in run.get("capabilities") or []:
                    c = str(cap)
                    if c and c not in caps:
                        caps.append(c)
            skill_id = f"skill:{abs(hash(key)) % 10_000_000:07d}"
            skill = Skill(
                skill_id=skill_id,
                name=f"{domain}:{goal[:40]}" if goal else domain,
                trigger=goal or domain,
                preconditions=tuple(str(p) for p in (group[0].get("preconditions") or [])),
                capabilities=tuple(caps),
                steps=tuple(steps[:12]),
                source_run_ids=tuple(r for r in run_ids if r),
                success_count=successes,
                attempt_count=len(group),
                domain=domain,
                trust_state="AGENT_PROPOSED",
            )
            # Only mark VERIFIED when measured rate is high and sample ≥ min_repeats.
            rate = skill.measured_success_rate or 0.0
            if rate >= 0.8 and skill.attempt_count >= min_repeats:
                skill.trust_state = "VERIFIED"
            self._skills[skill.skill_id] = skill
            derived.append(skill)
        return derived

    def list_skills(self, *, domain: str | None = None) -> list[Skill]:
        items = list(self._skills.values())
        if domain:
            items = [s for s in items if s.domain == domain]
        return items
