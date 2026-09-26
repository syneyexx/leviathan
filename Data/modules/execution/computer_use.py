"""Computer-use architecture — action proposal → authority → execution → observation → verification (W19).

Model text must NEVER directly control the OS. All side effects pass ExecutionGateway /
CapabilityCatalog. Browser content remains untrusted data (not system instruction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
import uuid


class ComputerUsePhase(str, Enum):
    PROPOSE = "PROPOSE"
    AUTHORIZE = "AUTHORIZE"
    EXECUTE = "EXECUTE"
    OBSERVE = "OBSERVE"
    VERIFY = "VERIFY"


@dataclass
class ComputerUseAction:
    action_id: str
    kind: str  # navigate | click | type | scroll | keypress | screenshot | ...
    target: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "kind": self.kind,
            "target": self.target,
            "args": dict(self.args),
            "rationale": self.rationale,
        }


@dataclass
class ComputerUseStepResult:
    phase: ComputerUsePhase
    ok: bool
    detail: str
    observation: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    status: str = "MEASURED"  # MEASURED | BLOCKED | UNAVAILABLE | NOT_CONFIGURED

    def public_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "ok": self.ok,
            "detail": self.detail,
            "observation": dict(self.observation),
            "verification": dict(self.verification),
            "status": self.status,
        }


@dataclass
class ComputerUseLoop:
    """Governed computer-use loop — proposal alone is never execution authority."""

    loop_id: str
    actions: list[ComputerUseAction] = field(default_factory=list)
    results: list[ComputerUseStepResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "actions": [a.public_dict() for a in self.actions],
            "results": [r.public_dict() for r in self.results],
            "metadata": dict(self.metadata),
            "truth": {
                "model_text_cannot_directly_control_os": True,
                "requires_authority_gate": True,
                "click_success_is_not_task_completion": True,
                "browser_content_untrusted": True,
            },
        }


def propose_actions_from_model_text(text: str) -> list[ComputerUseAction]:
    """Parse *structured* action proposals only — free-form OS commands are refused."""
    # Free-form shell/OS directives are never accepted as executable.
    lowered = (text or "").strip().lower()
    forbidden = ("rm -rf", "sudo ", "format c:", "shutdown", "powershell", "cmd.exe", "/bin/sh")
    if any(tok in lowered for tok in forbidden):
        return []
    # Expect lines like: ACTION kind=click target=#submit
    actions: list[ComputerUseAction] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.upper().startswith("ACTION "):
            continue
        parts = line.split()
        kind = "unknown"
        target = ""
        for part in parts[1:]:
            if part.startswith("kind="):
                kind = part.split("=", 1)[1]
            elif part.startswith("target="):
                target = part.split("=", 1)[1]
        if kind in {"shell", "os", "exec", "bash", "python_eval"}:
            continue
        actions.append(
            ComputerUseAction(
                action_id=str(uuid.uuid4()),
                kind=kind,
                target=target,
                rationale="structured_proposal",
            )
        )
    return actions


def run_computer_use_loop(
    *,
    proposals: list[ComputerUseAction],
    authorize: Callable[[ComputerUseAction], dict[str, Any]],
    execute: Callable[[ComputerUseAction], dict[str, Any]],
    observe: Callable[[ComputerUseAction, dict[str, Any]], dict[str, Any]],
    verify: Callable[[ComputerUseAction, dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> ComputerUseLoop:
    """Execute proposal→authority→execution→observation→verification for each action."""
    loop = ComputerUseLoop(loop_id=str(uuid.uuid4()), actions=list(proposals))
    for action in proposals:
        auth = authorize(action)
        if not auth.get("allowed"):
            loop.results.append(
                ComputerUseStepResult(
                    phase=ComputerUsePhase.AUTHORIZE,
                    ok=False,
                    detail=str(auth.get("reason") or "authority_denied"),
                    status=str(auth.get("status") or "BLOCKED"),
                )
            )
            continue
        loop.results.append(
            ComputerUseStepResult(
                phase=ComputerUsePhase.AUTHORIZE,
                ok=True,
                detail="authorized",
                observation={"capability": auth.get("capability")},
            )
        )
        try:
            exec_result = execute(action)
        except Exception as exc:  # noqa: BLE001
            loop.results.append(
                ComputerUseStepResult(
                    phase=ComputerUsePhase.EXECUTE,
                    ok=False,
                    detail=str(exc),
                    status="UNAVAILABLE",
                )
            )
            continue
        loop.results.append(
            ComputerUseStepResult(
                phase=ComputerUsePhase.EXECUTE,
                ok=bool(exec_result.get("ok", True)),
                detail=str(exec_result.get("detail") or "executed"),
                observation=dict(exec_result),
            )
        )
        obs = observe(action, exec_result)
        loop.results.append(
            ComputerUseStepResult(
                phase=ComputerUsePhase.OBSERVE,
                ok=True,
                detail="observed",
                observation=dict(obs),
            )
        )
        ver = verify(action, exec_result, obs)
        # Click/exec success alone is insufficient — verify resulting state.
        verified = bool(ver.get("passed")) and bool(ver.get("state_matches_goal"))
        loop.results.append(
            ComputerUseStepResult(
                phase=ComputerUsePhase.VERIFY,
                ok=verified,
                detail=str(ver.get("detail") or ("verified" if verified else "verification_failed")),
                verification=dict(ver),
                status="MEASURED" if "passed" in ver else "UNMEASURED",
            )
        )
    return loop
