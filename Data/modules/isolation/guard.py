from __future__ import annotations

from Data.backend.config import Settings

from .types import IsolationEffective, IsolationMode, IsolationReport, IsolationRequest


class IsolationGuard:
    """Compute isolation posture from settings + request.

    Distinguishes:
      requested          — what the caller asked for
      application_intended — what LEVIATHAN config intends to enforce
      os_enforced        — what the OS actually enforces (measured)

    Invariant: configuration intent ≠ OS-enforced isolation unless proven.
    Never claim stronger isolation than is actually enforced.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def baseline_intended(self) -> tuple[IsolationMode, ...]:
        """Application-intended restrictions from configuration (not OS proof)."""
        modes: list[IsolationMode] = [IsolationMode.PROCESS]
        if not self.settings.network.allow_outbound:
            modes.append(IsolationMode.NETWORK_DENY)
        # Workspace rooting is always intended for local-first LEVIATHAN.
        modes.append(IsolationMode.WORKSPACE)
        return tuple(modes)

    def baseline_effective(self) -> tuple[IsolationMode, ...]:
        """Backward-compatible alias — returns application-intended modes."""
        return self.baseline_intended()

    def measured_os_enforced(self) -> tuple[IsolationMode, ...]:
        """Return only isolation modes proven at the OS level.

        LEVIATHAN does not currently attach Job Objects / seccomp / network
        namespaces for general workers. Process separation of the backend
        itself is not OS-enforced isolation of untrusted workloads.
        """
        # Honest empty set by default — probes may populate via probe_untrusted_execution.
        return ()

    def probe_untrusted_execution(self, workspace_root: str | None = None):
        """Run adversarial sandbox probes — results are measured, not config claims."""
        from pathlib import Path

        from .sandbox import run_workspace_sandbox_probes

        report = run_workspace_sandbox_probes(
            Path(workspace_root) if workspace_root else None,
            network_allow_outbound=bool(self.settings.network.allow_outbound),
        )
        return report

    def evaluate(self, request: IsolationRequest | None = None) -> IsolationReport:
        intended = self.baseline_intended()
        os_enforced = self.measured_os_enforced()
        # "effective" for match checks = application-intended (honestly labeled).
        effective = intended
        req = request or IsolationRequest(requested=())
        requested = set(req.requested)
        eff_set = set(effective)
        notes: list[str] = []
        if IsolationMode.NONE in requested and len(requested) > 1:
            notes.append("NONE cannot combine with other modes; ignored in match check")
            requested.discard(IsolationMode.NONE)
        matched = requested.issubset(eff_set) if requested else False
        if not requested:
            notes.append("No isolation requested — reporting baseline intended only")
        elif not matched:
            missing = sorted(m.value for m in requested - eff_set)
            notes.append(f"Requested modes not in application-intended set: {missing}")
        else:
            notes.append("All requested modes are present in application-intended set")
        if not os_enforced:
            notes.append(
                "OS-enforced isolation unmeasured — application intent is not OS proof"
            )
        return IsolationReport(
            request=req,
            effective=IsolationEffective(
                effective=effective,
                matched=matched,
                notes=tuple(notes),
            ),
            metadata={
                "network_allow_outbound": self.settings.network.allow_outbound,
                "loopback_only": self.settings.runtime.loopback_only,
                "application_intended": [m.value for m in intended],
                "os_enforced": [m.value for m in os_enforced],
                "os_enforcement_measured": False,
                "enforcement_class": "application_intended",
            },
        )
