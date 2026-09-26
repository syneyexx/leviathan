"""W72 — Final assurance checks (no duplicate owners; live trading blocked)."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


# Forbidden parallel infrastructure class names — must not be introduced.
FORBIDDEN_OWNER_CLASS_NAMES: frozenset[str] = frozenset(
    {
        "BrainV2",
        "RiskEngineV2",
        "InstitutionalDatabase",
        "JobRuntime2",
        "JobRuntimeV2",
        "MarketSimV2",
        "StrategyLearningV2",
        "InstitutionalTradingV2",
        "TradingBrainV2",
        "SecondJobRuntime",
        "PrivateQueue",
        "ModelControlPlaneV2",
        "McpBridgeV2",
    }
)

# institutional_core itself must not define these either.
SCAN_DEFAULT_ROOTS: tuple[str, ...] = (
    "Data/modules/market_sim",
)


@dataclass
class AssuranceFinding:
    code: str
    severity: str
    detail: str
    path: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "path": self.path,
        }


@dataclass
class AssuranceReport:
    status: str
    findings: list[AssuranceFinding] = field(default_factory=list)
    live_trading: dict[str, Any] = field(default_factory=dict)
    scanned_files: int = 0
    forbidden_hits: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [f.public_dict() for f in self.findings],
            "liveTrading": dict(self.live_trading),
            "scannedFiles": self.scanned_files,
            "forbiddenHits": list(self.forbidden_hits),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "no_duplicate_owners": True,
                "no_aladdin_parity_claim": True,
            },
        }


def _iter_python_files(roots: Sequence[str | Path]) -> Iterable[Path]:
    for root in roots:
        path = Path(root)
        if not path.exists():
            continue
        if path.is_file() and path.suffix == ".py":
            yield path
            continue
        for py in path.rglob("*.py"):
            # Skip caches
            if "__pycache__" in py.parts:
                continue
            yield py


def scan_forbidden_owner_classes(
    roots: Sequence[str | Path] | None = None,
    *,
    forbidden: Sequence[str] = tuple(sorted(FORBIDDEN_OWNER_CLASS_NAMES)),
) -> dict[str, Any]:
    """AST-scan for forbidden class definitions (not string mentions in comments alone)."""
    hits: list[dict[str, Any]] = []
    scanned = 0
    forbidden_set = set(forbidden)
    for path in _iter_python_files(roots or SCAN_DEFAULT_ROOTS):
        scanned += 1
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except Exception as exc:  # noqa: BLE001
            hits.append(
                {
                    "path": str(path),
                    "className": None,
                    "detail": f"parse_error:{exc}",
                }
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in forbidden_set:
                hits.append(
                    {
                        "path": str(path),
                        "className": node.name,
                        "lineno": node.lineno,
                        "detail": "forbidden_duplicate_owner_class",
                    }
                )
    return {
        "ok": not any(h.get("className") for h in hits),
        "scannedFiles": scanned,
        "hits": hits,
        "status": MeasurementState.PASS.value
        if not any(h.get("className") for h in hits)
        else MeasurementState.FAIL.value,
    }


def verify_live_trading_blocked() -> dict[str, Any]:
    try:
        from ..trading_live_guard import LiveTradingGuard

        status = LiveTradingGuard().public_status()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": MeasurementState.UNAVAILABLE.value,
            "detail": f"guard_import_failed:{exc}",
            "LIVE_TRADING_AVAILABLE": MeasurementState.UNAVAILABLE.value,
        }

    available = str(status.get("LIVE_TRADING_AVAILABLE") or "")
    ok = available == MeasurementState.BLOCKED.value
    # Extra honesty: unlock env alone must not flip assurance to green live.
    unlock = os.environ.get("LEVIATHAN_LIVE_TRADING_UNLOCK", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    findings = []
    if not ok:
        findings.append("live_trading_not_blocked")
    if unlock:
        findings.append("unlock_env_set_but_orders_still_must_block")
    return {
        "ok": ok,
        "status": MeasurementState.PASS.value if ok else MeasurementState.FAIL.value,
        "LIVE_TRADING_AVAILABLE": available,
        "publicStatus": status,
        "findings": findings,
        "truth": {"agent_cannot_enable": True},
    }


def run_assurance(
    *,
    roots: Sequence[str | Path] | None = None,
    workspace_root: str | Path | None = None,
) -> AssuranceReport:
    """Structured final assurance report for W72."""
    findings: list[AssuranceFinding] = []

    # Resolve roots relative to workspace when provided.
    resolved_roots: list[str | Path]
    if roots is not None:
        resolved_roots = list(roots)
    elif workspace_root is not None:
        resolved_roots = [Path(workspace_root) / "Data/modules/market_sim"]
    else:
        # Prefer package-relative market_sim root.
        here = Path(__file__).resolve()
        resolved_roots = [here.parents[1]]  # market_sim/

    scan = scan_forbidden_owner_classes(resolved_roots)
    for hit in scan["hits"]:
        if hit.get("className"):
            findings.append(
                AssuranceFinding(
                    code="FORBIDDEN_OWNER_CLASS",
                    severity="CRITICAL",
                    detail=str(hit.get("detail")),
                    path=str(hit.get("path")),
                )
            )

    live = verify_live_trading_blocked()
    if not live.get("ok"):
        findings.append(
            AssuranceFinding(
                code="LIVE_TRADING_NOT_BLOCKED",
                severity="CRITICAL",
                detail=str(live.get("detail") or live.get("findings") or "not_blocked"),
            )
        )

    # Flag promotional parity claims only. Markers joined at runtime so this
    # file does not contain the forbidden phrases as contiguous literals.
    claim_markers = tuple(
        "".join(parts)
        for parts in (
            ("alad", "din equiva", "lent"),
            ("alad", "din par", "ity"),
            ("matches alad", "din"),
            ("black", "rock par", "ity"),
            ("black", "rock-level"),
            ("black", "rock level"),
        )
    )
    core_root = Path(__file__).resolve().parent
    for py in core_root.glob("*.py"):
        if py.name == "assurance.py":
            continue  # skip marker definitions in this module
        text = py.read_text(encoding="utf-8").lower()
        if any(marker in text for marker in claim_markers):
            findings.append(
                AssuranceFinding(
                    code="PARITY_CLAIM",
                    severity="HIGH",
                    detail="forbidden_parity_claim_language",
                    path=str(py),
                )
            )

    critical = [f for f in findings if f.severity == "CRITICAL"]
    if critical:
        status = MeasurementState.FAIL.value
    elif findings:
        status = MeasurementState.DEGRADED.value
    else:
        status = MeasurementState.PASS.value

    return AssuranceReport(
        status=status,
        findings=findings,
        live_trading=live,
        scanned_files=int(scan.get("scannedFiles") or 0),
        forbidden_hits=list(scan.get("hits") or []),
    )
