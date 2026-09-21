"""Immutable constraints that must never be user-overridable.

Every entry must document ID, reason, threat/correctness rationale,
enforcement location, regression test, and why configurability is undesirable.
"""

from __future__ import annotations

from .types import ImmutableConstraint


IMMUTABLE_CONSTRAINTS: list[ImmutableConstraint] = [
    ImmutableConstraint(
        id="security.terminal.metacharacters_blocked",
        label="Terminal shell metacharacters blocked",
        value=True,
        reason="Prevents shell injection; commands must be argv arrays without | & ; `",
        enforcement_location="backend/terminal_tool.py:_validate_argv",
        source="hades",
        category="terminal",
        threat_or_correctness_rationale="Shell metacharacters enable command chaining and injection even with argv-looking inputs.",
        test_location="backend/tests/test_api.py (terminal metacharacter rejection)",
        why_not_configurable="Allowing users to disable this would reintroduce shell injection into a local agent with file/network tools.",
    ),
    ImmutableConstraint(
        id="security.terminal.cwd_jail",
        label="Terminal CWD jail",
        value="data_root",
        reason="Terminal working directories must stay inside the HADES data root.",
        enforcement_location="backend/terminal_tool.py:_resolve_cwd",
        source="hades",
        category="terminal",
        threat_or_correctness_rationale="Unjailed CWD would let tools read/write arbitrary host paths outside the workspace.",
        test_location="backend/tests/test_api.py (terminal cwd jail)",
        why_not_configurable="Escape from the data-root jail is a host-compromise class failure, not a preference.",
    ),
    ImmutableConstraint(
        id="security.network.non_loopback_when_blocked",
        label="Non-loopback blocked when network_policy=block",
        value=True,
        reason="Offline-first isolation: block mode must refuse non-local network egress.",
        enforcement_location="backend/main.py (network policy helpers)",
        source="hades",
        category="network",
        threat_or_correctness_rationale="Block mode that still allows egress would silently violate offline-first guarantees.",
        test_location="backend/tests/test_world_class_capabilities.py / network policy tests",
        why_not_configurable="network_policy itself is configurable; the meaning of 'block' is not.",
    ),
    ImmutableConstraint(
        id="security.subprocess.shell_false",
        label="subprocess shell=False",
        value=True,
        reason="HADES never launches subprocesses with shell=True.",
        enforcement_location="platform_services_core / plugin runtimes",
        source="hades",
        category="security",
        threat_or_correctness_rationale="shell=True interpolates strings through a shell and is a classic injection primitive.",
        test_location="backend/tests/test_hardcoded_limit_detector.py (immutable registry) + plugin invoke tests",
        why_not_configurable="No legitimate agent workload requires shell=True; argv arrays are sufficient.",
    ),
    ImmutableConstraint(
        id="runtime.schedules.max_catchup",
        label="Schedule catch-up limit",
        value=1,
        reason="After downtime, at most one missed schedule occurrence fires to avoid stampede.",
        enforcement_location="backend/schedules.py:MAX_CATCHUP",
        source="hades",
        category="scheduler",
        threat_or_correctness_rationale="Unbounded catch-up after downtime can stampede local models, disk, and network.",
        test_location="backend/tests/test_hardcoded_limit_detector.py",
        why_not_configurable="Raising catch-up under user control recreates the stampede failure mode this invariant exists to prevent.",
    ),
    ImmutableConstraint(
        id="api.chat.message_max_length",
        label="Chat message max length",
        value=100_000,
        reason="Hard API payload bound to protect request parsing memory; not an agent iteration limit.",
        enforcement_location="backend/main.py MessageInput",
        source="hades",
        category="api",
        threat_or_correctness_rationale="Unbounded request bodies can OOM the API process during parse before any agent budget applies.",
        test_location="backend/tests/test_api.py / pydantic rejection paths",
        why_not_configurable="This is a process-safety ceiling, distinct from configurable retrieval/tool budgets.",
    ),
    ImmutableConstraint(
        id="security.secrets.not_in_frontend_settings",
        label="Secrets excluded from non-secret settings export",
        value=True,
        reason="API keys and credentials must not be dumped into generic settings export without redaction.",
        enforcement_location="backend/control/service.py:export_config",
        source="hades",
        category="security",
        threat_or_correctness_rationale="Leaking secrets to the browser/settings export breaks the local trust boundary.",
        test_location="backend/tests (control export / settings contract)",
        why_not_configurable="Secret redaction is a hard privacy invariant, not a UX preference.",
    ),
    ImmutableConstraint(
        id="trading.paper_only",
        label="Trading remains PAPER-only",
        value=True,
        reason="No live broker code path; paper fills only.",
        enforcement_location="backend/trading_service.py",
        source="hades",
        category="trading",
        threat_or_correctness_rationale="Accidental live order routing would create real financial side effects.",
        test_location="backend/tests/test_platform.py / trading tests",
        why_not_configurable="Live brokerage is out of scope; configurability here would be a safety bypass.",
    ),
]


def public_immutable() -> list[dict]:
    return [item.to_public() for item in IMMUTABLE_CONSTRAINTS]
