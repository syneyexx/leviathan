from __future__ import annotations

from Data.backend.config import Settings

from .types import IsolationEffective, IsolationMode, IsolationReport, IsolationRequest


class IsolationGuard:
    """Compute effective isolation from settings + request.

    Invariant: requested isolation ≠ effective isolation unless proven.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def baseline_effective(self) -> tuple[IsolationMode, ...]:
        modes: list[IsolationMode] = [IsolationMode.PROCESS]
        if not self.settings.network.allow_outbound:
            modes.append(IsolationMode.NETWORK_DENY)
        # Workspace rooting is always intended for local-first LEVIATHAN.
        modes.append(IsolationMode.WORKSPACE)
        return tuple(modes)

    def evaluate(self, request: IsolationRequest | None = None) -> IsolationReport:
        effective = self.baseline_effective()
        req = request or IsolationRequest(requested=())
        requested = set(req.requested)
        eff_set = set(effective)
        notes: list[str] = []
        if IsolationMode.NONE in requested and len(requested) > 1:
            notes.append("NONE cannot combine with other modes; ignored in match check")
            requested.discard(IsolationMode.NONE)
        matched = requested.issubset(eff_set) if requested else False
        if not requested:
            notes.append("No isolation requested — reporting baseline effective only")
        elif not matched:
            missing = sorted(m.value for m in requested - eff_set)
            notes.append(f"Requested modes not effective: {missing}")
        else:
            notes.append("All requested modes are present in effective set")
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
            },
        )
