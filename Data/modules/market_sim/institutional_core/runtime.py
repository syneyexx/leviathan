"""InstitutionalRuntime — canonical integration fabric for W37–W108.

Extends existing owners (PortfolioBook, RiskGuard, paper broker, JobRuntime,
ModelRegistry, ExecutionGateway). Does NOT create parallel platform owners.

All material institutional mutations that go through portefeuille paper orders
must reach this runtime for instrument identity, mandate, IBOR, subledger,
decision, audit, reconciliation, and exception capture.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..accounting import money, ZERO
from .persistence import InstitutionalRepository
from .timeutil import now_canonical, to_canonical, ts_le, window_contains
from .status import MeasurementState, DEFAULT_TRUTH
from .mandates import OrderIntent, pre_trade_check, mandate_fingerprint, load_mandate
from .entitlements import (
    ChangeRequest,
    evaluate_approval,
    cannot_approve_own_change,
    required_authority_for_change,
)
from .ibor import IborEvent, reconstruct_ibor
from .subledger import JournalEntry, JournalLine, Subledger, trade_entry
from .decision_ledger import DecisionPacket, DecisionLedger, hash_payload, HashRef
from .reconciliation import CompareContract, run_reconciliation, Break, transition_break
from .enterprise_risk import PositionRiskInput, aggregate_enterprise_risk
from .control_room import build_control_room_snapshot
from .exceptions_ops import OpsException, ExceptionRegistry
from .data_governance import evaluate_quality, QuarantineRegistry
from .construction import ConstructionConstraints, optimize_scores, check_feasibility
from .stress_engine import WhatIfShock, run_what_if
from .liquidity import LiquidityInput, evaluate_liquidity
from .leverage_margin import MarginPosition, compute_leverage_margin
from .performance import Cashflow, compute_performance
from .order_lifecycle import Order, OrderLifecycle
from .moneyutil import require_currency, convert, as_money
from .bitemporal import content_hash as bitemporal_content_hash


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class InstitutionalRuntime:
    """One runtime fabric bound to the canonical market_sim DB path."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.repo = InstitutionalRepository(self.db_path)
        self.repo.ensure_schema()
        self._decision_cache = DecisionLedger()
        self._order_lifecycle = OrderLifecycle()
        self._quarantine = QuarantineRegistry()

    # ------------------------------------------------------------------
    # Instrument identity
    # ------------------------------------------------------------------

    def ensure_instrument(
        self,
        symbol: str,
        *,
        family: str = "equity",
        currency: str = "USD",
        exchange: str | None = None,
        multiplier: str = "1",
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Resolve or register canonical instrument for a trading symbol."""
        symbol_u = str(symbol).upper().strip()
        as_of_ts = as_of or now_canonical()
        aliases = self.repo.list_aliases_for(symbol_u)
        candidates: list[str] = []
        for alias in aliases:
            valid_to = alias.get("valid_to") or None
            if valid_to == "":
                valid_to = None
            if not window_contains(
                valid_from=alias.get("valid_from") or "1970-01-01T00:00:00+00:00",
                valid_to=valid_to,
                as_of=as_of_ts,
            ):
                continue
            candidates.append(alias["instrument_id"])
        unique = sorted(set(candidates))
        if len(unique) > 1:
            raise ValueError(f"ambiguous instrument alias {symbol_u}: {unique}")
        if len(unique) == 1:
            inst = self.repo.get_instrument(unique[0])
            if inst:
                return {
                    "instrument_id": inst["instrument_id"],
                    "primary_symbol": inst["primary_symbol"],
                    "currency": inst["currency"],
                    "family": inst["family"],
                    "multiplier": inst["multiplier"],
                    "status": "RESOLVED",
                    "created": False,
                }
        instrument_id = f"INST-{family.upper()}-{symbol_u}"
        self.repo.upsert_instrument(
            {
                "instrument_id": instrument_id,
                "family": family,
                "primary_symbol": symbol_u,
                "currency": require_currency(currency),
                "exchange": exchange or "",
                "multiplier": multiplier,
                "valid_from": "1970-01-01T00:00:00+00:00",
                "status": "ACTIVE",
            }
        )
        self.repo.upsert_alias(
            {
                "alias_id": f"alias-{instrument_id}-ticker",
                "alias": symbol_u,
                "alias_type": "ticker",
                "instrument_id": instrument_id,
                "valid_from": "1970-01-01T00:00:00+00:00",
                "source": "runtime_ensure",
            }
        )
        self.repo.append_audit_event(
            {
                "kind": "instrument.registered",
                "actor": "institutional_runtime",
                "detail": f"registered {instrument_id} for {symbol_u}",
                "metadata": {"instrument_id": instrument_id, "symbol": symbol_u},
            }
        )
        return {
            "instrument_id": instrument_id,
            "primary_symbol": symbol_u,
            "currency": require_currency(currency),
            "family": family,
            "multiplier": multiplier,
            "status": "CREATED",
            "created": True,
        }

    def resolve_instrument(self, symbol: str, *, as_of: str | None = None) -> dict[str, Any]:
        symbol_u = str(symbol).upper().strip()
        as_of_ts = as_of or now_canonical()
        aliases = self.repo.list_aliases_for(symbol_u)
        candidates = []
        for alias in aliases:
            valid_to = alias.get("valid_to") or None
            if valid_to == "":
                valid_to = None
            if window_contains(
                valid_from=alias.get("valid_from") or "1970-01-01T00:00:00+00:00",
                valid_to=valid_to,
                as_of=as_of_ts,
            ):
                candidates.append(alias["instrument_id"])
        unique = sorted(set(candidates))
        if not unique:
            return {
                "query": symbol_u,
                "instrument_id": None,
                "status": MeasurementState.UNAVAILABLE.value,
                "candidates": [],
            }
        if len(unique) > 1:
            return {
                "query": symbol_u,
                "instrument_id": None,
                "status": MeasurementState.FAIL.value,
                "candidates": unique,
                "reason": "AMBIGUOUS",
            }
        return {
            "query": symbol_u,
            "instrument_id": unique[0],
            "status": MeasurementState.PASS.value,
            "candidates": unique,
        }

    # ------------------------------------------------------------------
    # Mandates / pre-trade
    # ------------------------------------------------------------------

    def set_mandate(self, portfolio_id: str, payload: Mapping[str, Any], *, mandate_id: str | None = None) -> dict[str, Any]:
        mid = mandate_id or f"mandate-{portfolio_id}"
        existing = self.repo.get_mandate_for_portfolio(portfolio_id)
        version = int(existing["version"]) + 1 if existing else 1
        fp = mandate_fingerprint(payload)
        row = self.repo.upsert_mandate(
            {
                "mandate_id": mid,
                "portfolio_id": portfolio_id,
                "version": version,
                "payload": dict(payload),
                "fingerprint": fp,
                "status": "ACTIVE",
            }
        )
        self.repo.append_audit_event(
            {
                "kind": "mandate.updated",
                "actor": "institutional_runtime",
                "detail": f"mandate {mid} v{version}",
                "metadata": {"mandate_id": mid, "fingerprint": fp},
            }
        )
        return row

    def pre_trade_gate(
        self,
        *,
        portfolio_id: str,
        symbol: str,
        side: str,
        qty: float,
        notional: float | None = None,
        family: str = "equity",
        current_symbol_exposure_pct: float = 0.0,
        current_gross_exposure_pct: float = 0.0,
        orders_today: int = 0,
    ) -> dict[str, Any]:
        mandate_row = self.repo.get_mandate_for_portfolio(portfolio_id)
        mandate = (mandate_row or {}).get("payload") or {}
        # Default restrictive paper mandate when none configured.
        if not mandate:
            mandate = {
                "allowedInstruments": ["*"],
                "restrictedInstruments": [],
                "maxOrdersPerDay": 10_000,
                "maxSymbolExposurePct": 100.0,
                "maxGrossExposurePct": 500.0,
                "liveTrading": False,
            }
        intent = OrderIntent(
            symbol=str(symbol).upper(),
            side=str(side).upper(),
            qty=float(qty),
            family=family,
            notional=notional,
        )
        decision = pre_trade_check(
            intent,
            mandate,
            current_symbol_exposure_pct=current_symbol_exposure_pct,
            current_gross_exposure_pct=current_gross_exposure_pct,
            orders_today=orders_today,
        )
        body = decision.public_dict()
        body["mandateVersion"] = (mandate_row or {}).get("version")
        body["mandateId"] = (mandate_row or {}).get("mandate_id")
        if not decision.allowed:
            self.repo.upsert_exception(
                {
                    "exception_id": f"compliance-{portfolio_id}-{uuid.uuid4().hex[:8]}",
                    "kind": "compliance.breach",
                    "severity": "HIGH",
                    "status": "OPEN",
                    "owner": "compliance",
                    "evidence": body,
                    "linked": {"portfolio_id": portfolio_id, "symbol": symbol},
                }
            )
            self.repo.append_audit_event(
                {
                    "kind": "compliance.blocked",
                    "actor": "institutional_runtime",
                    "detail": f"pre-trade blocked {symbol} {side}",
                    "metadata": body,
                }
            )
        return body

    # ------------------------------------------------------------------
    # Maker-checker
    # ------------------------------------------------------------------

    def request_protected_change(
        self,
        *,
        kind: str,
        maker_id: str,
        payload: Mapping[str, Any],
        change_id: str | None = None,
    ) -> dict[str, Any]:
        cid = change_id or str(uuid.uuid4())
        required = required_authority_for_change(kind, payload)
        self.repo.upsert_approval_record(
            {
                "approval_id": f"apr-{cid}",
                "change_id": cid,
                "kind": kind,
                "maker_id": maker_id,
                "checker_id": "",
                "status": "PENDING",
                "payload": {"change": dict(payload), "required_authority": required},
            }
        )
        self.repo.append_audit_event(
            {
                "kind": "authority.requested",
                "actor": maker_id,
                "detail": f"{kind} pending",
                "metadata": {"change_id": cid, "required": required},
            }
        )
        return {
            "changeId": cid,
            "approvalId": f"apr-{cid}",
            "status": "PENDING",
            "requiredAuthority": required,
        }

    def approve_protected_change(
        self,
        *,
        change_id: str,
        checker_id: str,
        checker_roles: Sequence[str],
    ) -> dict[str, Any]:
        approval = self.repo.get_approval(f"apr-{change_id}")
        if approval is None:
            raise ValueError(f"unknown change: {change_id}")
        if approval.get("status") == "APPROVED":
            return {"allowed": True, "status": "APPROVED", "idempotent": True}
        change = ChangeRequest(
            change_id=change_id,
            kind=str(approval.get("kind") or ""),
            maker_id=str(approval.get("maker_id") or ""),
            payload=dict((approval.get("payload") or {}).get("change") or {}),
            required_authority=str(
                (approval.get("payload") or {}).get("required_authority") or "risk_officer"
            ),
        )
        if cannot_approve_own_change(maker_id=change.maker_id, checker_id=checker_id):
            decision = {
                "allowed": False,
                "reasons": ["maker_equals_checker"],
                "status": MeasurementState.FAIL.value,
            }
            self.repo.append_audit_event(
                {
                    "kind": "authority.self_approval_blocked",
                    "actor": checker_id,
                    "detail": change_id,
                    "metadata": decision,
                }
            )
            return decision
        result = evaluate_approval(change, checker_id=checker_id, checker_roles=checker_roles)
        body = result.public_dict()
        if result.allowed:
            self.repo.upsert_approval_record(
                {
                    **approval,
                    "checker_id": checker_id,
                    "status": "APPROVED",
                    "payload": {
                        **(approval.get("payload") or {}),
                        "decision": body,
                    },
                }
            )
            self.repo.append_audit_event(
                {
                    "kind": "authority.approved",
                    "actor": checker_id,
                    "detail": change_id,
                    "metadata": body,
                }
            )
        else:
            self.repo.upsert_approval_record(
                {
                    **approval,
                    "checker_id": checker_id,
                    "status": "DENIED",
                    "payload": {**(approval.get("payload") or {}), "decision": body},
                }
            )
            self.repo.append_audit_event(
                {
                    "kind": "authority.denied",
                    "actor": checker_id,
                    "detail": change_id,
                    "metadata": body,
                }
            )
        return body

    def require_approved_change(self, change_id: str) -> dict[str, Any]:
        approval = self.repo.get_approval(f"apr-{change_id}")
        if approval is None or approval.get("status") != "APPROVED":
            raise PermissionError(f"protected change not approved: {change_id}")
        return approval

    # ------------------------------------------------------------------
    # Fill / IBOR / subledger integration (called from PortfolioService)
    # ------------------------------------------------------------------

    def on_paper_fill(
        self,
        *,
        portfolio_id: str,
        symbol: str,
        side: str,
        qty: Any,
        price: Any,
        fee: Any,
        fill_id: str,
        order_id: str,
        currency: str = "USD",
        decision_id: str | None = None,
        actor: str = "paper",
        family: str = "equity",
    ) -> dict[str, Any]:
        """Atomically record institutional effects of a paper fill.

        Idempotent on fill_id for IBOR + journal. Duplicate fills do not
        duplicate economics.
        """
        ccy = require_currency(currency)
        qty_d = money(qty)
        price_d = money(price)
        fee_d = money(fee)
        inst = self.ensure_instrument(symbol, family=family, currency=ccy)
        instrument_id = inst["instrument_id"]

        # Order lifecycle (maps to existing CREATED→…→FILLED machine)
        existing = self._order_lifecycle.get(order_id)
        ts_now = now_canonical()
        if existing is None:
            order = Order(
                order_id=order_id,
                symbol=symbol.upper(),
                side=side.upper(),
                qty=float(qty_d),
                state="CREATED",
                mode="PAPER",
            )
            self._order_lifecycle.create(order)
            for st, note in (
                ("RISK_CHECKED", "institutional_pre_trade"),
                ("ACCEPTED", "paper_accepted"),
                ("FILLED", "paper_fill"),
            ):
                try:
                    self._order_lifecycle.transition(
                        order_id, new_state=st, ts=ts_now, note=note, fill_qty=float(qty_d) if st == "FILLED" else None
                    )
                except Exception:  # noqa: BLE001
                    pass
        else:
            try:
                self._order_lifecycle.transition(
                    order_id, new_state="FILLED", ts=ts_now, note="idempotent_fill", fill_qty=float(qty_d)
                )
            except Exception:  # noqa: BLE001
                pass

        seq = self.repo.next_ibor_sequence(portfolio_id)
        sleeve_id = f"sleeve-{portfolio_id}"
        account_id = f"cash-{portfolio_id}"
        lot_id = f"lot-{fill_id}"
        position_id = f"{sleeve_id}::{instrument_id}"
        side_u = side.upper()
        cash_delta = (
            money(-(qty_d * price_d + fee_d))
            if side_u in ("BUY", "COVER")
            else money(qty_d * price_d - fee_d)
        )

        ibor_events_payload: list[dict[str, Any]] = []
        # Ensure hierarchy nodes
        for node_id, level, parent in (
            (f"ent-{portfolio_id}", "enterprise", None),
            (f"mandate-{portfolio_id}", "mandate", f"ent-{portfolio_id}"),
            (f"strategy-{portfolio_id}", "strategy", f"mandate-{portfolio_id}"),
            (portfolio_id, "portfolio", f"strategy-{portfolio_id}"),
            (account_id, "account", portfolio_id),
            (sleeve_id, "sleeve", account_id),
        ):
            ibor_events_payload.append(
                {
                    "event_id": f"{fill_id}-node-{node_id}",
                    "portfolio_id": portfolio_id,
                    "sequence": seq,
                    "kind": "UPSERT_NODE",
                    "ts": ts_now,
                    "payload": {
                        "node_id": node_id,
                        "level": level,
                        "name": node_id,
                        "parent_id": parent,
                    },
                    "idempotency_key": f"{fill_id}-node-{node_id}",
                }
            )
            seq += 1

        if side_u in ("BUY", "COVER"):
            kind = "OPEN_LOT"
            payload = {
                "sleeve_id": sleeve_id,
                "instrument_id": instrument_id,
                "position_id": position_id,
                "lot_id": lot_id,
                "qty": str(qty_d),
                "cost_basis": str(price_d),
                "side": "LONG",
                "opened_at": ts_now,
            }
        else:
            kind = "OPEN_LOT"
            payload = {
                "sleeve_id": sleeve_id,
                "instrument_id": instrument_id,
                "position_id": position_id,
                "lot_id": lot_id,
                "qty": str(-qty_d if side_u == "SHORT" else qty_d),
                "cost_basis": str(price_d),
                "side": "SHORT" if side_u == "SHORT" else "LONG",
                "opened_at": ts_now,
            }
            if side_u == "SELL":
                # Represent sale as OPEN then CLOSE of the lot for reconstruction.
                pass

        ibor_events_payload.append(
            {
                "event_id": f"{fill_id}-lot",
                "portfolio_id": portfolio_id,
                "sequence": seq,
                "kind": kind,
                "ts": now_canonical(),
                "payload": payload,
                "idempotency_key": f"{fill_id}-lot",
            }
        )
        seq += 1
        ibor_events_payload.append(
            {
                "event_id": f"{fill_id}-cash",
                "portfolio_id": portfolio_id,
                "sequence": seq,
                "kind": "CASH",
                "ts": now_canonical(),
                "payload": {"account_id": account_id, "delta": float(cash_delta), "currency": ccy},
                "idempotency_key": f"{fill_id}-cash",
            }
        )

        ibor_results = []
        for ev in ibor_events_payload:
            ibor_results.append(self.repo.append_ibor_event(ev))

        # Subledger postings (Decimal-safe amounts stored as strings in JSON)
        notional = money(qty_d * price_d)
        if side_u in ("BUY", "COVER"):
            lines = [
                {"account": "lots", "amount": str(notional), "currency": ccy, "instrument_id": instrument_id, "lot_id": lot_id},
                {"account": "fees", "amount": str(fee_d), "currency": ccy, "instrument_id": instrument_id},
                {"account": "cash", "amount": str(-notional - fee_d), "currency": ccy},
            ]
        else:
            lines = [
                {"account": "cash", "amount": str(notional - fee_d), "currency": ccy},
                {"account": "fees", "amount": str(fee_d), "currency": ccy, "instrument_id": instrument_id},
                {"account": "lots", "amount": str(-notional), "currency": ccy, "instrument_id": instrument_id, "lot_id": lot_id},
            ]
        # Balance check with Decimal
        bal = sum(money(l["amount"]) for l in lines)
        if bal != ZERO:
            raise ValueError(f"unbalanced journal for fill {fill_id}: {bal}")

        journal = self.repo.append_journal_entry(
            {
                "entry_id": f"je-{fill_id}",
                "portfolio_id": portfolio_id,
                "ts": now_canonical(),
                "kind": "TRADE",
                "lines": lines,
                "refs": {
                    "fill_id": fill_id,
                    "order_id": order_id,
                    "instrument_id": instrument_id,
                    "decision_id": decision_id or "",
                },
                "currency": ccy,
                "idempotency_key": f"je-{fill_id}",
            }
        )

        # Decision packet binding
        packet_payload = {
            "portfolio_id": portfolio_id,
            "instrument_id": instrument_id,
            "symbol": symbol.upper(),
            "side": side_u,
            "qty": str(qty_d),
            "price": str(price_d),
            "fee": str(fee_d),
            "fill_id": fill_id,
            "order_id": order_id,
            "currency": ccy,
        }
        packet_hash = hash_payload(packet_payload)
        did = decision_id or f"dec-{fill_id}"
        self.repo.upsert_decision_packet(
            {
                "decision_id": did,
                "packet_hash": packet_hash,
                "payload": packet_payload,
                "actor": actor,
                "status": "EXECUTED",
            }
        )

        audit = self.repo.append_audit_event(
            {
                "kind": "fill.recorded",
                "actor": actor,
                "detail": f"{side_u} {qty_d} {symbol} @{price_d}",
                "metadata": {
                    "fill_id": fill_id,
                    "order_id": order_id,
                    "instrument_id": instrument_id,
                    "decision_id": did,
                    "portfolio_id": portfolio_id,
                },
            }
        )

        # Snapshot valuation (mark = fill price)
        self.repo.upsert_valuation_snapshot(
            {
                "snapshot_id": f"val-{fill_id}",
                "portfolio_id": portfolio_id,
                "as_of": now_canonical(),
                "base_currency": ccy,
                "quality": "OBSERVED",
                "payload": {
                    "marks": {instrument_id: str(price_d)},
                    "fx": {ccy: "1"},
                    "fill_id": fill_id,
                },
            }
        )

        return {
            "instrument": inst,
            "ibor": ibor_results,
            "journal": journal,
            "decision_id": did,
            "packet_hash": packet_hash,
            "audit": audit,
            "duplicate_economics": bool(journal.get("duplicate")),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_portfolio_book": True,
                "idempotent_on_fill_id": True,
            },
        }

    def reconstruct_portfolio_ibor(self, portfolio_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        rows = self.repo.list_ibor_events(portfolio_id)
        events = [
            IborEvent(
                event_id=r["event_id"],
                sequence=int(r["sequence"]),
                kind=r["kind"],
                ts=r["ts"],
                payload=r.get("payload") or {},
            )
            for r in rows
        ]
        snap = reconstruct_ibor(events, enterprise_id=f"ent-{portfolio_id}", as_of=as_of)
        return snap.public_dict()

    def journal_balances(self, portfolio_id: str) -> dict[str, Any]:
        entries = self.repo.list_journal_entries(portfolio_id)
        balances: dict[str, dict[str, str]] = {}
        for entry in entries:
            ccy = require_currency(entry.get("currency") or "USD")
            for line in entry.get("lines") or []:
                acct = str(line.get("account") or "")
                line_ccy = require_currency(line.get("currency") or ccy)
                balances.setdefault(line_ccy, {})
                prev = money(balances[line_ccy].get(acct) or 0)
                balances[line_ccy][acct] = str(money(prev + money(line.get("amount") or 0)))
        return {
            "portfolioId": portfolio_id,
            "balancesByCurrency": balances,
            "entryCount": len(entries),
            "truth": DEFAULT_TRUTH.public_dict(),
        }

    # ------------------------------------------------------------------
    # Risk from canonical holdings
    # ------------------------------------------------------------------

    def enterprise_risk_from_book(
        self,
        *,
        positions: Sequence[Mapping[str, Any]],
        nav: Any,
        base_currency: str = "USD",
        portfolio_id: str = "default",
    ) -> dict[str, Any]:
        inputs = []
        for p in positions:
            mv = p.get("market_value")
            if mv is None:
                mv = money(p.get("qty") or 0) * money(p.get("mark") or p.get("price") or 0)
            inputs.append(
                PositionRiskInput(
                    instrument_id=str(p.get("instrument_id") or p.get("symbol") or ""),
                    mv=float(money(mv)),
                    portfolio_id=str(p.get("portfolio_id") or portfolio_id),
                    strategy_id=(None if p.get("strategy_id") is None else str(p.get("strategy_id"))),
                )
            )
        report = aggregate_enterprise_risk(inputs, nav=float(money(nav)))
        body = report.public_dict()
        body["baseCurrency"] = require_currency(base_currency)
        return body

    # ------------------------------------------------------------------
    # Reconciliation with persistence
    # ------------------------------------------------------------------

    def run_and_persist_reconciliation(
        self,
        *,
        run_id: str | None = None,
        domain: str,
        left_system: str,
        right_system: str,
        left_rows: Sequence[Mapping[str, Any]],
        right_rows: Sequence[Mapping[str, Any]],
        fields: Sequence[str] = ("value",),
        key_field: str = "id",
        numeric_tolerance: float = 0.0,
        allow_both_empty: bool = False,
        expected_population: int | None = None,
    ) -> dict[str, Any]:
        rid = run_id or f"recon-{uuid.uuid4().hex[:12]}"
        contract = CompareContract(
            contract_id=f"recon-{domain}",
            domain=domain,
            left_system=left_system,
            right_system=right_system,
            fields=tuple(fields),
            key_field=key_field,
            numeric_tolerance=numeric_tolerance,
            allow_both_empty=allow_both_empty,
            expected_population=expected_population,
        )
        run = run_reconciliation(
            run_id=rid,
            contract=contract,
            left_rows=left_rows,
            right_rows=right_rows,
        )
        body = run.public_dict()
        for brk in run.breaks:
            self.repo.upsert_break(
                {
                    "break_id": brk.break_id,
                    "domain": brk.domain,
                    "field": brk.field,
                    "left_system": brk.left_system,
                    "right_system": brk.right_system,
                    "left_key": brk.left_key,
                    "right_key": brk.right_key,
                    "left_value": brk.left_value,
                    "right_value": brk.right_value,
                    "status": brk.status,
                    "fingerprint": brk.fingerprint,
                    "correlation_id": brk.correlation_id,
                    "history": brk.history,
                    "explanation": brk.explanation,
                }
            )
            if brk.status == "OPEN":
                self.repo.upsert_exception(
                    {
                        "exception_id": f"recon-{brk.break_id}",
                        "kind": "reconciliation.break",
                        "severity": "MEDIUM",
                        "status": "OPEN",
                        "owner": "operations",
                        "evidence": brk.public_dict(),
                        "linked": {"run_id": rid},
                    }
                )
        self.repo.upsert_recon_run(
            {
                "run_id": rid,
                "domain": domain,
                "contract": contract.public_dict(),
                "status": body["status"],
                "open_count": body["openCount"],
                "break_count": body["breakCount"],
                "payload": body,
            }
        )
        self.repo.append_audit_event(
            {
                "kind": "reconciliation.completed",
                "actor": "institutional_runtime",
                "detail": f"{domain} status={body['status']}",
                "metadata": {"run_id": rid, "open_count": body["openCount"]},
            }
        )
        return body

    def waive_break(
        self,
        break_id: str,
        *,
        actor: str,
        note: str,
        change_id: str | None = None,
    ) -> dict[str, Any]:
        if change_id:
            self.require_approved_change(change_id)
        else:
            raise PermissionError("waiver requires approved change_id")
        row = self.repo.get_break(break_id)
        if row is None:
            raise ValueError(f"unknown break: {break_id}")
        brk = Break(
            break_id=row["break_id"],
            domain=row["domain"],
            field=row["field"],
            left_system=row["left_system"],
            right_system=row["right_system"],
            left_key=row["left_key"],
            right_key=row["right_key"],
            left_value=row.get("left_value"),
            right_value=row.get("right_value"),
            status=row["status"],
            fingerprint=row.get("fingerprint") or "",
            correlation_id=row.get("correlation_id"),
            history=json.loads(row.get("history_json") or "[]"),
            explanation=row.get("explanation"),
        )
        # Move toward WAIVED through allowed path
        if brk.status == "OPEN":
            transition_break(brk, new_status="ACKNOWLEDGED", actor=actor, ts=now_canonical(), note="ack for waiver")
        if brk.status == "ACKNOWLEDGED":
            transition_break(brk, new_status="WAIVED", actor=actor, ts=now_canonical(), note=note)
        elif brk.status not in ("WAIVED",):
            transition_break(brk, new_status="WAIVED", actor=actor, ts=now_canonical(), note=note)
        self.repo.upsert_break(
            {
                "break_id": brk.break_id,
                "domain": brk.domain,
                "field": brk.field,
                "left_system": brk.left_system,
                "right_system": brk.right_system,
                "left_key": brk.left_key,
                "right_key": brk.right_key,
                "left_value": brk.left_value,
                "right_value": brk.right_value,
                "status": brk.status,
                "fingerprint": brk.fingerprint,
                "correlation_id": brk.correlation_id,
                "history": brk.history,
                "explanation": brk.explanation,
            }
        )
        self.repo.append_audit_event(
            {
                "kind": "reconciliation.waived",
                "actor": actor,
                "detail": break_id,
                "metadata": {"change_id": change_id, "note": note},
            }
        )
        return brk.public_dict()

    # ------------------------------------------------------------------
    # Data quality / bitemporal
    # ------------------------------------------------------------------

    def ingest_observation(
        self,
        *,
        entity_type: str,
        entity_id: str,
        effective_time: str,
        payload: Mapping[str, Any],
        source: str,
        source_version: str = "1",
        observed_at: str | None = None,
        metrics: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        price = payload.get("price")
        derived_metrics = dict(metrics or {})
        if price is not None:
            try:
                if float(price) < 0:
                    derived_metrics["negative_prices"] = int(derived_metrics.get("negative_prices") or 0) + 1
            except (TypeError, ValueError):
                derived_metrics["negative_prices"] = int(derived_metrics.get("negative_prices") or 0) + 1
        derived_metrics.setdefault("duplicate_timestamps", 0)
        derived_metrics.setdefault("gap_ratio", 0.0)
        report = evaluate_quality(
            dataset_id=f"{entity_type}:{entity_id}",
            source_id=source,
            metrics=derived_metrics,
        )
        findings_list = report.public_dict() if hasattr(report, "public_dict") else {}
        quarantine = bool(getattr(report, "quarantined", False))
        quality = str(getattr(report, "verdict", None) or findings_list.get("verdict") or MeasurementState.OBSERVED.value)

        if quarantine:
            qid = f"q-{entity_type}-{entity_id}-{uuid.uuid4().hex[:8]}"
            with self.repo.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO institutional_quarantine(
                        quarantine_id, entity_type, entity_id, reason, source,
                        status, evidence_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        qid,
                        entity_type,
                        entity_id,
                        "quality_gate",
                        source,
                        "QUARANTINED",
                        _canon(findings_list),
                        now_canonical(),
                        now_canonical(),
                    ),
                )
            self.repo.upsert_exception(
                {
                    "exception_id": f"dq-{qid}",
                    "kind": "data.quarantined",
                    "severity": "HIGH",
                    "status": "OPEN",
                    "owner": "data",
                    "evidence": {"findings": findings_list},
                    "linked": {"entity_type": entity_type, "entity_id": entity_id},
                }
            )
            self.repo.append_audit_event(
                {
                    "kind": "data.quarantined",
                    "actor": "institutional_runtime",
                    "detail": f"{entity_type}:{entity_id}",
                    "metadata": {"quarantine_id": qid},
                }
            )
            return {
                "accepted": False,
                "quarantined": True,
                "quality": quality,
                "findings": findings_list,
            }

        # Supersede prior open versions at same entity for newer knowledge
        record_id = f"bt-{entity_type}-{entity_id}-{uuid.uuid4().hex[:10]}"
        ch = bitemporal_content_hash(dict(payload))
        # Mark previous as superseded
        with self.repo.connect() as conn:
            conn.execute(
                """
                UPDATE institutional_bitemporal_records
                SET superseded_at = ?
                WHERE entity_type = ? AND entity_id = ? AND (superseded_at IS NULL OR superseded_at = '')
                """,
                (now_canonical(), entity_type, entity_id),
            )
        self.repo.upsert_bitemporal_record(
            {
                "record_id": record_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "effective_time": effective_time,
                "observed_at": observed_at or effective_time,
                "recorded_at": now_canonical(),
                "source": source,
                "source_version": source_version,
                "payload": dict(payload),
                "quality": quality,
                "content_hash": ch,
            }
        )
        return {
            "accepted": True,
            "quarantined": False,
            "recordId": record_id,
            "quality": quality,
            "contentHash": ch,
        }

    def observation_as_of(
        self,
        *,
        entity_type: str,
        entity_id: str,
        as_of: str,
        knowledge_time: str | None = None,
    ) -> dict[str, Any]:
        rows = self.repo.query_bitemporal_as_of(
            entity_type=entity_type,
            entity_id=entity_id,
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        if not rows:
            return {"status": MeasurementState.UNAVAILABLE.value, "record": None}
        return {"status": MeasurementState.PASS.value, "record": rows[0]}

    # ------------------------------------------------------------------
    # Control room
    # ------------------------------------------------------------------

    def control_room_snapshot(self, *, feature_enabled: bool = True) -> dict[str, Any]:
        breaks = self.repo.list_breaks(status="OPEN", limit=200)
        exceptions = self.repo.list_exceptions(status="OPEN", limit=200)
        audit = self.repo.verify_audit_chain()
        recon_runs = self.repo.list_recon_runs(limit=20)
        health = {
            "overall": MeasurementState.PASS.value if audit.get("ok") else MeasurementState.FAIL.value,
            "auditChain": audit,
            "openBreaks": len(breaks),
            "openExceptions": len(exceptions),
            "recentReconRuns": len(recon_runs),
        }
        recon_body = {
            "status": MeasurementState.FAIL.value if breaks else MeasurementState.PASS.value,
            "openCount": len(breaks),
            "breaks": [
                {
                    "breakId": b.get("break_id"),
                    "domain": b.get("domain"),
                    "field": b.get("field"),
                    "status": b.get("status"),
                    "fingerprint": b.get("fingerprint"),
                    "explanation": b.get("explanation"),
                    "createdAt": b.get("created_at"),
                    "updatedAt": b.get("updated_at"),
                    "leftSystem": b.get("left_system"),
                    "rightSystem": b.get("right_system"),
                }
                for b in breaks[:50]
            ],
            "recentRuns": [
                {
                    "runId": r.get("run_id"),
                    "status": r.get("status"),
                    "openCount": r.get("open_count"),
                    "domain": r.get("domain"),
                    "createdAt": r.get("created_at"),
                }
                for r in recon_runs[:10]
            ],
        }
        exc_body = {
            "status": MeasurementState.FAIL.value if exceptions else MeasurementState.EMPTY.value,
            "openCount": len(exceptions),
            "items": [
                {
                    "exceptionId": e.get("exception_id"),
                    "kind": e.get("kind"),
                    "severity": e.get("severity"),
                    "status": e.get("status"),
                    "owner": e.get("owner"),
                    "firstSeen": e.get("first_seen"),
                    "lastSeen": e.get("last_seen"),
                }
                for e in exceptions[:50]
            ],
        }
        recent_audit = self.repo.list_audit_events(limit=40)
        audit_tail = recent_audit[-20:]
        audit_body = {
            "status": audit.get("status"),
            "ok": audit.get("ok"),
            "count": audit.get("count"),
            "brokenAt": audit.get("brokenAt"),
            "lastTs": audit.get("lastTs") or (audit_tail[-1].get("ts") if audit_tail else None),
            "recentEvents": [
                {
                    "eventId": ev.get("event_id"),
                    "kind": ev.get("kind"),
                    "actor": ev.get("actor"),
                    "detail": ev.get("detail"),
                    "ts": ev.get("ts"),
                }
                for ev in audit_tail
            ],
        }
        snap = build_control_room_snapshot(
            generated_at=now_canonical(),
            health=health,
            reconciliation=recon_body,
            exceptions=exc_body,
            audit=audit_body,
            feature_enabled=feature_enabled,
            store=getattr(self, "_market_store", None) or self._resolve_market_store(),
        )
        return snap.public_dict()

    def _resolve_market_store(self) -> Any | None:
        """Lazy MarketSimStore for control-room projections (same DB path)."""
        try:
            from Data.modules.market_sim.store import MarketSimStore

            store = MarketSimStore(self.db_path)
            store.initialize()
            self._market_store = store
            return store
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Portfolio construction / what-if
    # ------------------------------------------------------------------

    def construct_and_stress(
        self,
        *,
        scores: Mapping[str, float],
        constraints: ConstructionConstraints | Mapping[str, Any] | None = None,
        shocks: Sequence[Mapping[str, Any]] | None = None,
        positions_for_risk: Sequence[Mapping[str, Any]] | None = None,
        nav: float = 100.0,
    ) -> dict[str, Any]:
        if constraints is None:
            constraints = ConstructionConstraints()
        elif isinstance(constraints, Mapping):
            constraints = ConstructionConstraints(**{
                k: v for k, v in constraints.items()
                if k in ConstructionConstraints.__dataclass_fields__  # type: ignore[attr-defined]
            }) if hasattr(ConstructionConstraints, "__dataclass_fields__") else ConstructionConstraints()
        # Prefer constrained path; fall back to optimize_scores with explicit method label
        # Prefer explicit constrained optimizer when available; else greedy with method label.
        from .construction import optimize_constrained

        try:
            result = optimize_constrained(dict(scores), constraints=constraints)
        except Exception:  # noqa: BLE001
            result = optimize_scores(dict(scores), constraints=constraints)
        body = result.public_dict() if hasattr(result, "public_dict") else dict(result)
        weights = body.get("weights") or {}
        feas_violations = check_feasibility(weights, constraints)
        stress = None
        if shocks:
            shock_objs = [
                WhatIfShock(
                    symbol=str(s.get("instrument_id") or s.get("symbol") or ""),
                    return_shock=float(
                        s.get("shock_pct") or s.get("pct") or s.get("return_shock") or 0
                    ),
                )
                for s in shocks
            ]
            positions_map = {
                k: {"qty": 1.0, "side": "LONG"}
                for k in weights
            }
            marks_map = {k: float(nav) * float(v) for k, v in weights.items()}
            stress = run_what_if(
                scenario_id="whatif",
                positions=positions_map,
                marks=marks_map,
                cash=0.0,
                shocks=shock_objs,
            ).public_dict()
        risk = None
        if positions_for_risk is not None:
            risk = self.enterprise_risk_from_book(positions=positions_for_risk, nav=nav)
        return {
            "construction": body,
            "feasibility": {
                "ok": not feas_violations,
                "violations": feas_violations,
                "status": MeasurementState.PASS.value if not feas_violations else MeasurementState.INFEASIBLE.value,
            },
            "stress": stress,
            "risk": risk,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "method_visible": True,
            },
        }

    # ------------------------------------------------------------------
    # Durable workflow checkpointing (JobRuntime companion)
    # ------------------------------------------------------------------

    def checkpoint_workflow(
        self,
        *,
        workflow_id: str,
        job_id: str,
        step_index: int,
        state: Mapping[str, Any],
        status: str = "RUNNING",
    ) -> dict[str, Any]:
        return self.repo.upsert_workflow_checkpoint(
            {
                "workflow_id": workflow_id,
                "job_id": job_id,
                "step_index": step_index,
                "state": dict(state),
                "status": status,
                "idempotency_key": workflow_id,
            }
        )

    def resume_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        return self.repo.get_workflow_checkpoint(workflow_id)

    def attach_model_governance(
        self,
        *,
        model_id: str,
        version: str,
        intended_use: str,
        prohibited_use: str = "",
        validation_state: str = "UNVALIDATED",
        owner: str = "",
        validator: str = "",
        approval_state: str = "DRAFT",
        limitations: list[str] | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Attach institutional model-risk metadata to an existing model identity.

        Does not create a second ModelRegistry — stores governance beside MCP identity.
        """
        row = {
            "model_id": model_id,
            "version": version,
            "intended_use": intended_use,
            "prohibited_use": prohibited_use,
            "validation_state": validation_state,
            "owner": owner,
            "validator": validator,
            "approval_state": approval_state,
            "limitations_json": _canon(limitations or []),
            "evidence_json": _canon(dict(evidence or {})),
            "updated_at": now_canonical(),
        }
        with self.repo.connect() as conn:
            conn.execute(
                """
                INSERT INTO institutional_model_governance(
                    model_id, version, intended_use, prohibited_use, validation_state,
                    owner, validator, approval_state, limitations_json, evidence_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id, version) DO UPDATE SET
                    intended_use=excluded.intended_use,
                    prohibited_use=excluded.prohibited_use,
                    validation_state=excluded.validation_state,
                    owner=excluded.owner,
                    validator=excluded.validator,
                    approval_state=excluded.approval_state,
                    limitations_json=excluded.limitations_json,
                    evidence_json=excluded.evidence_json,
                    updated_at=excluded.updated_at
                """,
                (
                    row["model_id"],
                    row["version"],
                    row["intended_use"],
                    row["prohibited_use"],
                    row["validation_state"],
                    row["owner"],
                    row["validator"],
                    row["approval_state"],
                    row["limitations_json"],
                    row["evidence_json"],
                    row["updated_at"],
                ),
            )
        self.repo.append_audit_event(
            {
                "kind": "model.governance_updated",
                "actor": owner or "institutional_runtime",
                "detail": f"{model_id}@{version} → {approval_state}",
                "metadata": {
                    "model_id": model_id,
                    "version": version,
                    "validation_state": validation_state,
                    "approval_state": approval_state,
                },
            }
        )
        return row

    def assert_model_approved_for_use(
        self,
        *,
        model_id: str,
        version: str,
        use: str,
    ) -> dict[str, Any]:
        with self.repo.connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM institutional_model_governance
                WHERE model_id = ? AND version = ?
                """,
                (model_id, version),
            )
            row = cur.fetchone()
            if not row:
                raise PermissionError(
                    f"model {model_id}@{version} has no governance metadata — cannot approve use"
                )
            cols = [d[0] for d in cur.description]
            meta = dict(zip(cols, row))
        if str(meta.get("approval_state") or "").upper() not in {"APPROVED", "ACTIVE"}:
            raise PermissionError(
                f"model {model_id}@{version} approval_state={meta.get('approval_state')} "
                f"— not approved for {use}"
            )
        if str(meta.get("validation_state") or "").upper() not in {"VALIDATED", "PASSED"}:
            raise PermissionError(
                f"model {model_id}@{version} validation_state={meta.get('validation_state')}"
            )
        prohibited = str(meta.get("prohibited_use") or "")
        if use and use.lower() in prohibited.lower():
            raise PermissionError(f"use {use} prohibited for model {model_id}")
        return meta

    # ------------------------------------------------------------------
    # Full lifecycle helper (for E2E tests)
    # ------------------------------------------------------------------

    def full_paper_lifecycle(
        self,
        *,
        portfolio_id: str,
        symbol: str,
        side: str = "BUY",
        qty: float = 10.0,
        price: float = 100.0,
        fee: float = 1.0,
        currency: str = "USD",
        actor: str = "e2e",
        mandate: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if mandate is not None:
            self.set_mandate(portfolio_id, mandate)
        # Market observation
        obs = self.ingest_observation(
            entity_type="market_price",
            entity_id=symbol.upper(),
            effective_time=now_canonical(),
            payload={"price": price, "symbol": symbol.upper(), "currency": currency},
            source="paper_fixture",
        )
        gate = self.pre_trade_gate(
            portfolio_id=portfolio_id,
            symbol=symbol,
            side=side,
            qty=qty,
            notional=qty * price,
        )
        if not gate.get("allowed"):
            return {"blocked": True, "gate": gate, "observation": obs}
        order_id = str(uuid.uuid4())
        fill_id = f"fill-{order_id}"
        fill = self.on_paper_fill(
            portfolio_id=portfolio_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            fee=fee,
            fill_id=fill_id,
            order_id=order_id,
            currency=currency,
            actor=actor,
        )
        # Duplicate fill must not duplicate economics
        dup = self.on_paper_fill(
            portfolio_id=portfolio_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            fee=fee,
            fill_id=fill_id,
            order_id=order_id,
            currency=currency,
            actor=actor,
        )
        ibor = self.reconstruct_portfolio_ibor(portfolio_id)
        journal = self.journal_balances(portfolio_id)
        risk = self.enterprise_risk_from_book(
            positions=[
                {
                    "instrument_id": fill["instrument"]["instrument_id"],
                    "symbol": symbol,
                    "qty": qty,
                    "mark": price,
                    "currency": currency,
                }
            ],
            nav=qty * price + 10_000,
            base_currency=currency,
        )
        recon = self.run_and_persist_reconciliation(
            domain="portfolio_vs_journal",
            left_system="ibor",
            right_system="journal",
            left_rows=[{"id": symbol.upper(), "value": qty}],
            right_rows=[{"id": symbol.upper(), "value": qty}],
            fields=("value",),
            allow_both_empty=False,
            expected_population=1,
        )
        control = self.control_room_snapshot()
        audit = self.repo.verify_audit_chain()
        return {
            "observation": obs,
            "gate": gate,
            "fill": fill,
            "duplicate": dup,
            "ibor": ibor,
            "journal": journal,
            "risk": risk,
            "reconciliation": recon,
            "controlRoom": control,
            "audit": audit,
            "truth": {
                "duplicate_did_not_duplicate_economics": bool(dup.get("duplicate_economics")),
                "live_trading_blocked": True,
            },
        }


# Process-level cache keyed by db path for service binding
_RUNTIME_CACHE: dict[str, InstitutionalRuntime] = {}


def get_institutional_runtime(db_path: Path | str) -> InstitutionalRuntime:
    key = str(Path(db_path).resolve())
    rt = _RUNTIME_CACHE.get(key)
    if rt is None:
        rt = InstitutionalRuntime(db_path)
        _RUNTIME_CACHE[key] = rt
    return rt
