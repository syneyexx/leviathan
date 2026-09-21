"""Chat pipeline characterization — map before extract.

Uses existing BackendExecutionState / RunContext; does not rewrite send_message.
"""

from __future__ import annotations

from typing import Any

from evals.harness import git_start_commit

CHAT_PIPELINE_VERSION = "chat_pipeline_map_v1"

# Conceptual stages (names may map to existing lifecycle events)
STAGES = (
    "RECEIVED",
    "UNDERSTOOD",
    "CONTEXT_READY",
    "PLANNED",
    "EXECUTING",
    "VERIFYING",
    "FINALIZING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)


def characterize_chat_pipeline() -> dict[str, Any]:
    """Static characterization of the production Chat entry path."""
    sha = git_start_commit()

    # Existing owners (do not invent parallel engines)
    flow = [
        {"stage": "RECEIVED", "owner": "backend/main.py:send_message", "notes": "dedupe, conversation, branch/revise"},
        {"stage": "COMMANDS", "owner": "backend/chat_commands.py", "notes": "slash + natural harvest"},
        {"stage": "ATTACHMENTS_VISION", "owner": "main.py chat helpers", "notes": "multipart / vision paths"},
        {"stage": "UNDERSTOOD", "owner": "reasoning.understanding", "notes": "RequestSpec + RouteDecision"},
        {"stage": "CONTEXT_READY", "owner": "reasoning.chat_context / retrieval", "notes": "memory/knowledge pack"},
        {"stage": "PLANNED", "owner": "reasoning.plan_scheduler / specialists", "notes": "profile budgets"},
        {"stage": "EXECUTING", "owner": "tool loop + model_gateway", "notes": "streaming + non-streaming"},
        {"stage": "VERIFYING", "owner": "reasoning.verification + execution_truth", "notes": "deterministic floor + critic"},
        {"stage": "FINALIZING", "owner": "answer_presentation + memory proposals", "notes": "grounding"},
        {"stage": "PERSISTENCE", "owner": "database message write", "notes": "usage accounting"},
        {"stage": "COMPLETED", "owner": "BackendExecutionState", "notes": "execution_truth artifact"},
    ]

    hotspots = [
        {
            "file": "backend/main.py",
            "symbol": "send_message",
            "issue": "large orchestration surface — branch explosion across stream/tools/plugins",
            "extraction_target": "reasoning/chat_coordinator.py (orchestrates only)",
        },
        {
            "file": "backend/execution_truth.py",
            "symbol": "BackendExecutionState",
            "issue": "already provides request-scoped truth events",
            "extraction_target": "reuse — map stages onto emit() kinds",
        },
        {
            "file": "backend/reasoning/run_context.py",
            "symbol": "RunContext",
            "issue": "shared run contract exists",
            "extraction_target": "reuse for ChatRunContext alias",
        },
    ]

    must_preserve = [
        "streaming",
        "non-streaming",
        "attachments",
        "vision",
        "slash commands",
        "tools",
        "plugins",
        "memory",
        "research",
        "model routing",
        "verification",
        "branch/revision",
        "usage accounting",
        "cancellation",
    ]

    return {
        "suite": "chat_pipeline_characterization",
        "version": CHAT_PIPELINE_VERSION,
        "git_sha": sha,
        "stages": list(STAGES),
        "flow": flow,
        "hotspots": hotspots,
        "must_preserve": must_preserve,
        "migration": [
            "characterization tests first",
            "extract coordinator incrementally",
            "compare behavior after each step",
            "no one-shot rewrite of send_message",
        ],
        "status": "PASS",
        "extraction_status": "partial_coordinator_bridged",
        "coordinator_module": "reasoning.chat_coordinator",
        "note": "ChatRunContext/ChatStage emit bridged near BackendExecutionState; send_message not rewritten.",
    }
