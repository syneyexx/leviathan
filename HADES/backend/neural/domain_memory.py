"""Phase 13: domain-scoped Neural Memory banks.

HADES Neural Brain
  |
  +-- General Memory
  +-- Coding Memory
  +-- Research Memory
  +-- Trading Memory (isolated; never auto-queried with others)

Domain routing selects relevant memory. It does NOT control permissions,
authentication, filesystem, or tool authorization.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from neural.errors import NeuralDomainMismatch, NeuralError


class DomainMemoryError(NeuralError):
    code = "neural_domain_memory_error"


class NeuralDomain(str, Enum):
    GENERAL = "general"
    CODING = "coding"
    RESEARCH = "research"
    TRADING = "trading"


_CODING_RE = re.compile(
    r"(?i)\b(code|coding|pytest|unittest|lint|typecheck|compiler|patch|bug|refactor|"
    r"repository|pull request|stack trace|syntax|typescript|python|javascript)\b"
)
_RESEARCH_RE = re.compile(
    r"(?i)\b(research|evidence|citation|claim|source|paper|hypothesis|contradiction|"
    r"knowledge vault|literature)\b"
)
_TRADING_RE = re.compile(
    r"(?i)\b(trading|portfolio|ticker|backtest|order|position|market|pnl|equity)\b"
)


@dataclass
class DomainBankState:
    domain: NeuralDomain
    version: int = 0
    enabled: bool = True
    checkpoint_id: str | None = None
    candidate_checkpoint_id: str | None = None
    known_good_checkpoint_id: str | None = None
    last_promotion: str | None = None
    last_rollback: str | None = None
    write_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["domain"] = self.domain.value
        return payload


@dataclass
class DomainRouteDecision:
    primary: NeuralDomain
    include_general: bool
    domains: list[NeuralDomain]
    reason: str
    inspectable: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.value,
            "include_general": self.include_general,
            "domains": [d.value for d in self.domains],
            "reason": self.reason,
            "inspectable": dict(self.inspectable),
        }


def route_domains(
    task_text: str,
    *,
    allow_trading: bool = False,
    force_domain: NeuralDomain | None = None,
) -> DomainRouteDecision:
    """Deterministic, inspectable domain selection (not an authority gate)."""
    text = task_text or ""
    if force_domain is not None:
        domains = [force_domain]
        if force_domain is not NeuralDomain.GENERAL:
            domains = [NeuralDomain.GENERAL, force_domain]
        if force_domain is NeuralDomain.TRADING and not allow_trading:
            raise DomainMemoryError(
                "trading domain routing disabled",
                detail={"allow_trading": False},
            )
        return DomainRouteDecision(
            primary=force_domain,
            include_general=NeuralDomain.GENERAL in domains,
            domains=domains,
            reason="forced_domain",
            inspectable={"force_domain": force_domain.value},
        )

    hits = {
        NeuralDomain.CODING: bool(_CODING_RE.search(text)),
        NeuralDomain.RESEARCH: bool(_RESEARCH_RE.search(text)),
        NeuralDomain.TRADING: bool(_TRADING_RE.search(text)),
    }
    if hits[NeuralDomain.TRADING] and not allow_trading:
        hits[NeuralDomain.TRADING] = False

    matched = [d for d, ok in hits.items() if ok]
    if not matched:
        return DomainRouteDecision(
            primary=NeuralDomain.GENERAL,
            include_general=True,
            domains=[NeuralDomain.GENERAL],
            reason="default_general",
            inspectable={"hits": {k.value: v for k, v in hits.items()}},
        )
    # Prefer first stable priority: coding > research > trading.
    priority = [NeuralDomain.CODING, NeuralDomain.RESEARCH, NeuralDomain.TRADING]
    primary = next(d for d in priority if d in matched)
    domains = [NeuralDomain.GENERAL, primary]
    # Never auto-mix trading with other specialty domains.
    if primary is NeuralDomain.TRADING:
        domains = [NeuralDomain.TRADING]
    return DomainRouteDecision(
        primary=primary,
        include_general=NeuralDomain.GENERAL in domains,
        domains=domains,
        reason=f"matched_{primary.value}",
        inspectable={"hits": {k.value: v for k, v in hits.items()}},
    )


class DomainMemoryRegistry:
    """Independent domain banks with bounded fusion for READ."""

    def __init__(
        self,
        *,
        max_fused_domains: int = 2,
        enabled: Mapping[str, bool] | None = None,
    ) -> None:
        enabled = dict(enabled or {})
        self.max_fused_domains = max(1, int(max_fused_domains))
        self._banks: dict[NeuralDomain, DomainBankState] = {
            domain: DomainBankState(
                domain=domain,
                enabled=bool(enabled.get(domain.value, True if domain is not NeuralDomain.TRADING else False)),
            )
            for domain in NeuralDomain
        }

    def bank(self, domain: NeuralDomain | str) -> DomainBankState:
        key = NeuralDomain(domain) if isinstance(domain, str) else domain
        return self._banks[key]

    def set_enabled(self, domain: NeuralDomain | str, enabled: bool) -> DomainBankState:
        bank = self.bank(domain)
        bank.enabled = bool(enabled)
        return bank

    def bump_version(self, domain: NeuralDomain | str, *, checkpoint_id: str | None = None) -> DomainBankState:
        bank = self.bank(domain)
        if not bank.enabled:
            raise DomainMemoryError(
                "cannot update disabled domain memory",
                detail={"domain": bank.domain.value},
            )
        bank.version += 1
        bank.write_count += 1
        if checkpoint_id:
            bank.checkpoint_id = checkpoint_id
            bank.known_good_checkpoint_id = checkpoint_id
            bank.last_promotion = checkpoint_id
        return bank

    def record_candidate(self, domain: NeuralDomain | str, checkpoint_id: str) -> DomainBankState:
        bank = self.bank(domain)
        bank.candidate_checkpoint_id = checkpoint_id
        return bank

    def record_rollback(self, domain: NeuralDomain | str, checkpoint_id: str) -> DomainBankState:
        bank = self.bank(domain)
        bank.last_rollback = checkpoint_id
        bank.candidate_checkpoint_id = None
        if bank.known_good_checkpoint_id:
            bank.checkpoint_id = bank.known_good_checkpoint_id
        return bank

    def assert_domain_checkpoint(self, domain: NeuralDomain | str, checkpoint_id: str) -> None:
        bank = self.bank(domain)
        if not bank.enabled:
            raise NeuralDomainMismatch(
                "domain memory disabled",
                detail={"domain": bank.domain.value, "checkpoint_id": checkpoint_id},
            )
        expected = bank.checkpoint_id or bank.known_good_checkpoint_id
        if expected and checkpoint_id and checkpoint_id != expected and checkpoint_id != bank.candidate_checkpoint_id:
            raise NeuralDomainMismatch(
                "checkpoint does not belong to domain bank",
                detail={
                    "domain": bank.domain.value,
                    "expected": expected,
                    "candidate": bank.candidate_checkpoint_id,
                    "got": checkpoint_id,
                },
            )

    def select_for_task(self, task_text: str, *, allow_trading: bool = False) -> DomainRouteDecision:
        decision = route_domains(task_text, allow_trading=allow_trading)
        usable = [d for d in decision.domains if self._banks[d].enabled]
        if not usable:
            usable = [NeuralDomain.GENERAL] if self._banks[NeuralDomain.GENERAL].enabled else []
        if not usable:
            raise DomainMemoryError("no domain memory banks enabled")
        # Bound fusion: never query all banks by default.
        usable = usable[: self.max_fused_domains]
        primary = usable[0] if decision.primary not in usable else decision.primary
        return DomainRouteDecision(
            primary=primary,
            include_general=NeuralDomain.GENERAL in usable,
            domains=usable,
            reason=decision.reason,
            inspectable={**decision.inspectable, "enabled_filter": [d.value for d in usable]},
        )

    def preserve_other_domains(
        self,
        updated: NeuralDomain | str,
        *,
        before: Mapping[str, DomainBankState] | None = None,
    ) -> dict[str, bool]:
        """Return whether each other domain version is unchanged after an update."""
        updated_key = NeuralDomain(updated) if isinstance(updated, str) else updated
        snapshot = before or {d.value: DomainBankState(domain=d, version=self._banks[d].version) for d in NeuralDomain}
        result: dict[str, bool] = {}
        for domain, bank in self._banks.items():
            if domain is updated_key:
                continue
            prior = snapshot.get(domain.value)
            prior_version = prior.version if prior else 0
            result[domain.value] = bank.version == prior_version
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_fused_domains": self.max_fused_domains,
            "banks": {d.value: b.to_dict() for d, b in self._banks.items()},
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DomainMemoryRegistry":
        reg = cls(max_fused_domains=int(raw.get("max_fused_domains") or 2))
        for key, payload in dict(raw.get("banks") or {}).items():
            domain = NeuralDomain(key)
            bank = reg._banks[domain]
            bank.version = int(payload.get("version") or 0)
            bank.enabled = bool(payload.get("enabled", bank.enabled))
            bank.checkpoint_id = payload.get("checkpoint_id")
            bank.candidate_checkpoint_id = payload.get("candidate_checkpoint_id")
            bank.known_good_checkpoint_id = payload.get("known_good_checkpoint_id")
            bank.last_promotion = payload.get("last_promotion")
            bank.last_rollback = payload.get("last_rollback")
            bank.write_count = int(payload.get("write_count") or 0)
        return reg


def abstract_cross_domain_lesson(domain: NeuralDomain, lesson: str) -> str | None:
    """Only deliberate abstractions may transfer into General Memory."""
    text = (lesson or "").strip()
    if not text:
        return None
    if domain is NeuralDomain.CODING and re.search(r"(?i)test|verify|rollback|patch", text):
        return "durable changes should require independent verification before promotion"
    if domain is NeuralDomain.RESEARCH and re.search(r"(?i)evidence|source|claim", text):
        return "prefer evidence over unsupported assumption"
    return None
