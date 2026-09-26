"""WAVES 37–72 — institutional_core unit coverage (deterministic, no network)."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from Data.modules.market_sim.institutional_core.ai_governance import (
    LlmUseCase,
    evaluate_llm_action,
    governance_inventory,
)
from Data.modules.market_sim.institutional_core.api_surface import (
    INSTITUTIONAL_API_CATALOG,
    api_catalog_public,
    check_institutional_api,
)
from Data.modules.market_sim.institutional_core.assurance import (
    run_assurance,
    verify_live_trading_blocked,
)
from Data.modules.market_sim.institutional_core.audit_integrity import (
    HashChainedAuditLog,
    detect_corruption,
)
from Data.modules.market_sim.institutional_core.bitemporal import (
    BitemporalStore,
    build_record,
)
from Data.modules.market_sim.institutional_core.construction import (
    ConstructionConstraints,
    WeightBound,
    optimize_scores,
)
from Data.modules.market_sim.institutional_core.control_room import (
    build_control_room_snapshot,
)
from Data.modules.market_sim.institutional_core.corporate_actions import (
    CorporateAction,
    apply_corporate_action,
)
from Data.modules.market_sim.institutional_core.data_governance import (
    GoldenSourceDeclaration,
    QuarantineRecord,
    QuarantineRegistry,
    evaluate_quality,
    prefer_source,
    source_rank,
)
from Data.modules.market_sim.institutional_core.decision_ledger import (
    DecisionLedger,
    DecisionPacket,
    hash_payload,
)
from Data.modules.market_sim.institutional_core.durable_workflows import (
    DurableWorkflow,
    WorkflowStep,
    advance_workflow,
    resume_from_checkpoint,
    start_workflow,
    workflow_progress,
)
from Data.modules.market_sim.institutional_core.enterprise_risk import (
    PositionRiskInput,
    aggregate_enterprise_risk,
)
from Data.modules.market_sim.institutional_core.entitlements import (
    ChangeRequest,
    cannot_approve_own_change,
    evaluate_approval,
)
from Data.modules.market_sim.institutional_core.events import (
    INSTITUTIONAL_EVENT_CATALOG,
    event_catalog_public,
    validate_event,
)
from Data.modules.market_sim.institutional_core.exceptions_ops import (
    ExceptionRegistry,
    OpsException,
)
from Data.modules.market_sim.institutional_core.gap_ledger import (
    build_capability_gap_matrix,
    open_gaps,
)
from Data.modules.market_sim.institutional_core.ibor import (
    IborEvent,
    reconstruct_ibor,
    validate_hierarchy,
)
from Data.modules.market_sim.institutional_core.illiquid import (
    IlliquidInstrument,
    IlliquidRegistry,
)
from Data.modules.market_sim.institutional_core.institutional_slo import (
    DEFAULT_SLOS,
    evaluate_slo,
    health_rollup,
    institutional_slo_snapshot,
)
from Data.modules.market_sim.institutional_core.instrument_master import (
    CanonicalInstrument,
    InstrumentAlias,
    InstrumentMaster,
    TemporalWindow,
)
from Data.modules.market_sim.institutional_core.leverage_margin import (
    CollateralHaircut,
    MarginPosition,
    compute_leverage_margin,
)
from Data.modules.market_sim.institutional_core.liquidity import (
    LiquidityInput,
    days_to_liquidate,
    evaluate_liquidity,
)
from Data.modules.market_sim.institutional_core.mandates import (
    OrderIntent,
    pre_trade_check,
)
from Data.modules.market_sim.institutional_core.model_risk import (
    ModelCard,
    ModelRiskRegistry,
)
from Data.modules.market_sim.institutional_core.multi_asset import (
    build_multi_asset_truth_pack,
    family_status,
)
from Data.modules.market_sim.institutional_core.order_lifecycle import (
    Order,
    OrderLifecycle,
)
from Data.modules.market_sim.institutional_core.performance import (
    Cashflow,
    money_weighted_return,
    time_weighted_return,
)
from Data.modules.market_sim.institutional_core.reconciliation import (
    Break,
    CompareContract,
    correlate_breaks,
    run_reconciliation,
    transition_break,
)
from Data.modules.market_sim.institutional_core.reporting import (
    build_governance_report_pack,
)
from Data.modules.market_sim.institutional_core.resilience import (
    build_backup_manifest,
    fault_inject,
    verify_restore,
)
from Data.modules.market_sim.institutional_core.scale_bench import (
    BenchCase,
    run_scale_bench,
)
from Data.modules.market_sim.institutional_core.security_hardening import (
    redact_secrets,
)
from Data.modules.market_sim.institutional_core.status import (
    MeasurementState,
    is_green_claim,
)
from Data.modules.market_sim.institutional_core.strategy_lifecycle import (
    StrategyLifecycle,
    StrategyLifecycleRecord,
)
from Data.modules.market_sim.institutional_core.stress_engine import (
    WhatIfShock,
    reverse_stress_uniform,
    run_what_if,
)
from Data.modules.market_sim.institutional_core.subledger import (
    Subledger,
    realize_pnl_entry,
    replay_balances,
    trade_entry,
    valuation_entry,
)
from Data.modules.market_sim.institutional_core.tca import (
    FillObservation,
    analyze_fill,
)


CORE_ROOT = Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "institutional_core"


def _fingerprint(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class GapLedgerW37Tests(unittest.TestCase):
    def test_matrix_rows_open_gaps_owners_and_public_dict(self) -> None:
        matrix = build_capability_gap_matrix()
        self.assertGreater(len(matrix.rows), 0)
        gaps = open_gaps(matrix)
        self.assertIsInstance(gaps, list)
        self.assertGreater(len(gaps), 0)

        material = [
            r
            for r in matrix.rows
            if r.status
            not in {
                MeasurementState.NOT_IMPLEMENTED.value,
                MeasurementState.UNMEASURED.value,
                MeasurementState.EMPTY.value,
            }
            or r.implementation in {"PRESENT", "PARTIAL"}
        ]
        for row in material:
            owner = row.current_owner.strip()
            self.assertTrue(owner)
            self.assertNotEqual(owner.upper(), "UNASSIGNED")
            self.assertNotEqual(owner.lower(), "unknown")

        pub = matrix.public_dict()
        self.assertIn("rows", pub)
        self.assertIn("byStatus", pub)
        self.assertEqual(pub["count"], len(matrix.rows))
        self.assertTrue(pub["truth"]["live_trading_blocked"])
        live_rows = [r for r in matrix.rows if r.capability == "live_trading"]
        self.assertTrue(live_rows)
        self.assertEqual(live_rows[0].status, MeasurementState.BLOCKED.value)


class InstrumentMasterW38Tests(unittest.TestCase):
    def test_register_resolve_alias_and_temporal_miss(self) -> None:
        master = InstrumentMaster()
        inst = CanonicalInstrument(
            instrument_id="EQ.AAPL",
            family="equity",
            primary_symbol="AAPL",
            window=TemporalWindow(
                valid_from="2020-01-01T00:00:00+00:00",
                valid_to="2024-01-01T00:00:00+00:00",
            ),
        )
        master.register(inst)
        master.add_alias(
            InstrumentAlias(
                alias="US0378331005",
                alias_type="isin",
                instrument_id="EQ.AAPL",
                window=inst.window,
                source="vendor",
            )
        )

        hit = master.resolve("AAPL", as_of="2022-06-01T00:00:00+00:00")
        self.assertEqual(hit.status, MeasurementState.OBSERVED.value)
        self.assertEqual(hit.instrument_id, "EQ.AAPL")

        isin = master.resolve("US0378331005", as_of="2022-06-01T00:00:00+00:00")
        self.assertEqual(isin.instrument_id, "EQ.AAPL")

        miss = master.resolve("AAPL", as_of="2025-01-01T00:00:00+00:00")
        self.assertEqual(miss.status, MeasurementState.UNAVAILABLE.value)
        self.assertIsNone(miss.instrument_id)

        unknown = master.resolve("ZZZZ", as_of="2022-06-01T00:00:00+00:00")
        self.assertEqual(unknown.status, MeasurementState.UNAVAILABLE.value)


class BitemporalW39Tests(unittest.TestCase):
    def test_point_in_time_and_superseded_revision(self) -> None:
        store = BitemporalStore()
        v1 = build_record(
            entity_id="pos.1",
            version_id="v1",
            effective_time="2024-01-01T00:00:00+00:00",
            observed_at="2024-01-01T01:00:00+00:00",
            recorded_at="2024-01-01T01:00:00+00:00",
            payload={"qty": 10},
            source_system="ibor",
        )
        store.append(v1)
        v2 = build_record(
            entity_id="pos.1",
            version_id="v2",
            effective_time="2024-01-02T00:00:00+00:00",
            observed_at="2024-01-02T01:00:00+00:00",
            recorded_at="2024-01-02T01:00:00+00:00",
            payload={"qty": 12},
            source_system="ibor",
            parent_version_id="v1",
        )
        store.append(v2)

        pit = store.as_of_effective("pos.1", effective_time="2024-01-01T12:00:00+00:00")
        self.assertIsNotNone(pit)
        assert pit is not None
        self.assertEqual(pit.version_id, "v1")
        self.assertEqual(pit.payload["qty"], 10)

        versions = store.versions("pos.1")
        self.assertEqual(versions[0].superseded_by, "v2")
        self.assertIsNone(versions[1].superseded_by)


class DataGovernanceW40Tests(unittest.TestCase):
    def test_ohlc_fail_quarantine_prefer_source_golden_honesty(self) -> None:
        report = evaluate_quality(
            dataset_id="ds.ohlc",
            source_id="csv_local",
            metrics={
                "gap_ratio": 0.0,
                "duplicate_timestamps": 0,
                "negative_prices": 2,
                "unexpected_hash_change": False,
            },
        )
        self.assertEqual(report.verdict, MeasurementState.FAIL.value)
        self.assertTrue(report.quarantined)

        registry = QuarantineRegistry()
        registry.quarantine(
            QuarantineRecord(
                dataset_id="ds.ohlc",
                reason="negative_prices",
                findings=report.findings,
                quarantined_at="2024-01-01T00:00:00+00:00",
            )
        )
        self.assertTrue(registry.is_quarantined("ds.ohlc"))

        preferred = prefer_source(["csv_local", "golden_internal", "derived"])
        self.assertEqual(preferred, "golden_internal")
        self.assertLess(source_rank("golden_internal"), source_rank("csv_local"))
        # First-available alone must not win over hierarchy.
        first_available = ["csv_local", "golden_internal"]
        self.assertEqual(prefer_source(first_available), "golden_internal")
        self.assertNotEqual(prefer_source(first_available), first_available[0])

        golden = GoldenSourceDeclaration(
            domain="equity_ohlcv",
            source_id="csv_local",
            declared_at="2024-01-01T00:00:00+00:00",
            declared_by="ops",
            evidence=MeasurementState.ASSUMED.value,
        )
        self.assertTrue(golden.public_dict()["truth"]["evidence_assumed_until_measured"])


class IborW41Tests(unittest.TestCase):
    def test_reconstruct_deterministic_and_hierarchy_validate(self) -> None:
        events = [
            IborEvent(
                "e2",
                2,
                "OPEN_LOT",
                "2024-01-02T00:00:00+00:00",
                {
                    "sleeve_id": "slv1",
                    "instrument_id": "EQ.A",
                    "lot_id": "L1",
                    "qty": 100,
                    "cost_basis": 10.0,
                },
            ),
            IborEvent(
                "e1",
                1,
                "UPSERT_NODE",
                "2024-01-01T00:00:00+00:00",
                {"node_id": "slv1", "level": "sleeve", "name": "Sleeve", "parent_id": "enterprise"},
            ),
            IborEvent(
                "e0",
                0,
                "UPSERT_NODE",
                "2024-01-01T00:00:00+00:00",
                {"node_id": "enterprise", "level": "enterprise", "name": "Ent", "parent_id": None},
            ),
        ]
        a = reconstruct_ibor(events, enterprise_id="enterprise")
        b = reconstruct_ibor(list(reversed(events)), enterprise_id="enterprise")
        self.assertEqual(a.public_dict()["positions"], b.public_dict()["positions"])
        self.assertEqual(a.event_count, 3)
        pos = next(iter(a.positions.values()))
        self.assertEqual(pos.qty, 100.0)

        ok = validate_hierarchy(a)
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["status"], MeasurementState.PASS.value)


class SubledgerW42Tests(unittest.TestCase):
    def test_trade_valuation_realize_and_replay_identity(self) -> None:
        ledger = Subledger()
        t = trade_entry(
            entry_id="t1",
            ts="2024-01-01T00:00:00+00:00",
            instrument_id="EQ.A",
            lot_id="L1",
            qty=10,
            price=5.0,
            fee=1.0,
            side="BUY",
        )
        v = valuation_entry(
            entry_id="v1",
            ts="2024-01-02T00:00:00+00:00",
            instrument_id="EQ.A",
            mark_delta=3.0,
        )
        r = realize_pnl_entry(
            entry_id="r1",
            ts="2024-01-03T00:00:00+00:00",
            instrument_id="EQ.A",
            lot_id="L1",
            pnl=2.0,
        )
        for entry in (t, v, r):
            self.assertTrue(entry.balanced())
            ledger.post(entry)

        live = ledger.balances()
        replayed = replay_balances(ledger.entries())
        self.assertEqual(live.balances, replayed.balances)
        self.assertEqual(live.entry_count, replayed.entry_count)
        self.assertEqual(live.balances["lots"], 50.0 - 2.0)
        self.assertEqual(live.balances["cash"], -50.0 - 1.0)


class ReconciliationW43Tests(unittest.TestCase):
    def test_breaks_correlate_transition_rules_and_waive(self) -> None:
        contract = CompareContract(
            contract_id="c1",
            domain="positions",
            left_system="ibor",
            right_system="broker",
            fields=("qty",),
            key_field="id",
        )
        run = run_reconciliation(
            run_id="run1",
            contract=contract,
            left_rows=[{"id": "A", "qty": 10}, {"id": "B", "qty": 5}],
            right_rows=[{"id": "A", "qty": 11}, {"id": "B", "qty": 5}],
        )
        self.assertGreaterEqual(len(run.breaks), 1)
        self.assertTrue(all(b.status == "OPEN" for b in run.breaks))

        twin = Break(
            break_id="x2",
            domain=run.breaks[0].domain,
            field=run.breaks[0].field,
            left_system=run.breaks[0].left_system,
            right_system=run.breaks[0].right_system,
            left_key=run.breaks[0].left_key,
            right_key=run.breaks[0].right_key,
            left_value=run.breaks[0].left_value,
            right_value=run.breaks[0].right_value,
        )
        correlated = correlate_breaks([run.breaks[0], twin])
        self.assertEqual(correlated[0].correlation_id, correlated[1].correlation_id)

        brk = run.breaks[0]
        with self.assertRaises(ValueError):
            transition_break(brk, new_status="RESOLVED", actor="ops", ts="t0", note="silent")

        waived = transition_break(brk, new_status="WAIVED", actor="ops", ts="t1", note="accepted")
        self.assertEqual(waived.status, "WAIVED")
        self.assertEqual(waived.explanation, "accepted")


class PerformanceW44Tests(unittest.TestCase):
    def test_twr_mwr_hand_computable_and_missing_honest(self) -> None:
        # (1.1)*(0.95)*(1.02)-1 = 1.0659-1 = 0.0659
        twr = time_weighted_return([0.10, -0.05, 0.02])
        self.assertEqual(twr.state, MeasurementState.MEASURED)
        self.assertAlmostEqual(float(twr.value), 1.10 * 0.95 * 1.02 - 1.0, places=10)

        empty = time_weighted_return([])
        self.assertEqual(empty.state, MeasurementState.EMPTY)
        self.assertIsNone(empty.value)

        # No cashflows: MWR equals simple return (end/start - 1)
        mwr = money_weighted_return(start_value=100.0, end_value=110.0, cashflows=())
        self.assertEqual(mwr.state, MeasurementState.MEASURED)
        self.assertAlmostEqual(float(mwr.value), 0.10, places=6)

        with_cf = money_weighted_return(
            start_value=100.0,
            end_value=120.0,
            cashflows=[Cashflow("2024-01-15", 10.0)],
        )
        self.assertEqual(with_cf.state, MeasurementState.ESTIMATED)
        self.assertIsNotNone(with_cf.value)


class EnterpriseRiskW45Tests(unittest.TestCase):
    def test_aggregation_and_concentration(self) -> None:
        report = aggregate_enterprise_risk(
            [
                PositionRiskInput("EQ.A", 60.0, portfolio_id="p1", factor_loadings={"beta": 1.0}),
                PositionRiskInput("EQ.B", 40.0, portfolio_id="p1", factor_loadings={"beta": 0.5}),
                PositionRiskInput("EQ.C", -20.0, portfolio_id="p2"),
            ],
            nav=100.0,
        )
        self.assertEqual(report.gross_exposure.value, 120.0)
        self.assertEqual(report.net_exposure.value, 80.0)
        self.assertTrue(report.concentration_by_instrument)
        top = report.concentration_by_instrument[0]
        self.assertEqual(top.key, "EQ.A")
        self.assertAlmostEqual(top.weight_pct, 60.0)
        self.assertIn("beta", report.factor_exposures)
        self.assertTrue(report.truth["live_trading_blocked"] if hasattr(report, "truth") else True)
        self.assertTrue(report.public_dict()["truth"]["live_trading_blocked"])


class StressEngineW46Tests(unittest.TestCase):
    def test_what_if_and_reverse_stress(self) -> None:
        positions = {"EQ.A": {"qty": 10, "side": "LONG"}}
        marks = {"EQ.A": 100.0}
        result = run_what_if(
            scenario_id="shock15",
            positions=positions,
            marks=marks,
            cash=0.0,
            shocks=[WhatIfShock("EQ.A", -0.15)],
        )
        self.assertEqual(result.base_equity, 1000.0)
        self.assertAlmostEqual(result.shocked_equity, 850.0)
        self.assertAlmostEqual(result.pnl, -150.0)
        self.assertEqual(result.status, MeasurementState.ASSUMED.value)

        # scenario_risk pnl_pct is percentage points (e.g. -10.0 for -10%).
        rev = reverse_stress_uniform(
            positions=positions,
            marks=marks,
            cash=0.0,
            target_loss_pct=10.0,
            shock_grid=[-0.05, -0.10, -0.15, -0.20],
        )
        self.assertEqual(rev.required_uniform_shock, -0.10)
        self.assertEqual(rev.status, MeasurementState.ESTIMATED.value)


class LiquidityW47Tests(unittest.TestCase):
    def test_adv_estimate_not_observed_from_ohlcv_volume_alone(self) -> None:
        # Single-bar OHLCV volume used as ADV input is still an estimate for DTL.
        ohlcv_volume = 1_000_000.0
        dtl = days_to_liquidate(50_000, ohlcv_volume, participation_limit=0.1)
        self.assertEqual(dtl.state, MeasurementState.ESTIMATED)
        self.assertNotEqual(dtl.state, MeasurementState.OBSERVED)
        self.assertAlmostEqual(float(dtl.value), 0.5)

        missing = days_to_liquidate(10, None)
        self.assertEqual(missing.state, MeasurementState.UNMEASURED)

        report = evaluate_liquidity(
            [LiquidityInput(instrument_id="EQ.A", qty=50_000, adv=ohlcv_volume)]
        )
        self.assertEqual(report.items[0].days_to_liquidate.state, MeasurementState.ESTIMATED)
        self.assertEqual(report.status, MeasurementState.ESTIMATED.value)


class LeverageMarginW48Tests(unittest.TestCase):
    def test_assumed_model_labelled(self) -> None:
        report = compute_leverage_margin(
            [MarginPosition("EQ.A", 100.0, initial_margin_pct=50.0, maintenance_margin_pct=25.0)],
            nav=200.0,
            cash=50.0,
            haircuts=[CollateralHaircut("EQ.A", 10.0)],
            model_label="ASSUMED_reg_t_style",
        )
        self.assertEqual(report.model_label, "ASSUMED_reg_t_style")
        self.assertEqual(report.leverage.state, MeasurementState.ASSUMED)
        self.assertTrue(report.public_dict()["truth"]["model_is_ASSUMED_not_broker_official"])
        self.assertIn("model_ASSUMED", report.notes)


class MultiAssetW49Tests(unittest.TestCase):
    def test_options_and_fixed_income_not_implemented(self) -> None:
        pack = build_multi_asset_truth_pack(
            feature_enabled=True,
            capabilities_builder=lambda feature_enabled=True: {
                "feature_enabled": feature_enabled,
                "markets": [
                    {
                        "family": "equity",
                        "HISTORICAL_SIM_AVAILABLE": "AVAILABLE",
                        "LIVE_PAPER_AVAILABLE": "AVAILABLE",
                        "LIVE_TRADING_AVAILABLE": "BLOCKED",
                    },
                    {
                        "family": "options",
                        "HISTORICAL_SIM_AVAILABLE": "NOT_IMPLEMENTED",
                        "LIVE_PAPER_AVAILABLE": "NOT_IMPLEMENTED",
                        "LIVE_TRADING_AVAILABLE": "BLOCKED",
                        "notes": "identity only",
                    },
                    {
                        "family": "fixed_income",
                        "HISTORICAL_SIM_AVAILABLE": "NOT_IMPLEMENTED",
                        "LIVE_PAPER_AVAILABLE": "NOT_IMPLEMENTED",
                        "LIVE_TRADING_AVAILABLE": "BLOCKED",
                        "notes": "identity only",
                    },
                ],
            },
        )
        options = family_status(pack, "options")
        fi = family_status(pack, "fixed_income")
        self.assertEqual(options["HISTORICAL_SIM_AVAILABLE"], MeasurementState.NOT_IMPLEMENTED.value)
        self.assertEqual(fi["HISTORICAL_SIM_AVAILABLE"], MeasurementState.NOT_IMPLEMENTED.value)
        self.assertEqual(options["LIVE_TRADING_AVAILABLE"], MeasurementState.BLOCKED.value)
        self.assertEqual(pack.public_dict()["liveTradingDefault"], MeasurementState.BLOCKED.value)


class ConstructionW50Tests(unittest.TestCase):
    def test_infeasible_when_lower_bounds_exceed_sum(self) -> None:
        result = optimize_scores(
            {"A": 1.0, "B": 1.0},
            ConstructionConstraints(
                bounds=(
                    WeightBound("A", lower=0.6, upper=1.0),
                    WeightBound("B", lower=0.6, upper=1.0),
                ),
                sum_weights=1.0,
            ),
        )
        self.assertEqual(result.status, MeasurementState.INFEASIBLE.value)
        self.assertIn("lower_bounds_exceed_sum", result.violations)
        self.assertEqual(result.weights, {})


class MandatesW51Tests(unittest.TestCase):
    def test_pre_trade_rejects_restricted_instrument(self) -> None:
        mandate = {
            "universe": ["AAPL", "MSFT"],
            "allowedOrderTypes": ["MARKET"],
            "allowedFamilies": ["equity"],
            "maxOrdersPerDay": 10,
            "maxSymbolExposurePct": 25,
            "maxGrossExposurePct": 100,
            "cannotEnableLive": True,
        }
        decision = pre_trade_check(
            OrderIntent(symbol="RESTRICTED", side="BUY", qty=1, family="equity"),
            mandate,
        )
        self.assertFalse(decision.allowed)
        codes = {v.code for v in decision.violations}
        self.assertIn("UNIVERSE", codes)
        self.assertTrue(decision.public_dict()["truth"]["live_trading_never_granted_by_mandate"])


class DecisionLedgerW52Tests(unittest.TestCase):
    def test_packet_hash_immutability(self) -> None:
        packet = DecisionPacket(
            packet_id="p1",
            stage="PRE_TRADE",
            actor="agent.a",
            as_of="2024-01-01T00:00:00+00:00",
            payload={"symbol": "AAPL", "qty": 1},
            created_at="2024-01-01T00:00:00+00:00",
        )
        h1 = packet.content_hash()
        ledger = DecisionLedger()
        ledger.append(packet)
        self.assertEqual(ledger.verify("p1", h1)["ok"], True)

        # Mutating the stored object changes hash — immutability is content-hash based.
        packet.payload["qty"] = 99
        h2 = packet.content_hash()
        self.assertNotEqual(h1, h2)
        self.assertEqual(ledger.verify("p1", h1)["ok"], False)
        self.assertEqual(hash_payload({"a": 1}), hash_payload({"a": 1}))


class ModelRiskW53Tests(unittest.TestCase):
    def test_cannot_skip_to_approved_without_validation(self) -> None:
        reg = ModelRiskRegistry()
        reg.register(
            ModelCard(
                model_id="m1",
                name="alpha",
                version="1",
                owner="quant",
                state="CANDIDATE",
            )
        )
        with self.assertRaises(ValueError):
            reg.transition("m1", new_state="APPROVED", actor="risk", ts="t0")

        reg.transition("m1", new_state="IN_VALIDATION", actor="risk", ts="t1")
        with self.assertRaises(ValueError):
            reg.transition("m1", new_state="APPROVED", actor="risk", ts="t2")

        approved = reg.transition(
            "m1",
            new_state="APPROVED",
            actor="risk",
            ts="t3",
            validation_evidence=MeasurementState.PASS.value,
        )
        self.assertEqual(approved.state, "APPROVED")


class AiGovernanceW54Tests(unittest.TestCase):
    def test_separates_capability_vs_authority(self) -> None:
        use_case = LlmUseCase(
            use_case_id="research_summarizer",
            purpose="summarize",
            human_in_the_loop=True,
            can_place_orders=False,
        )
        blocked = evaluate_llm_action(use_case, action="PLACE_ORDER")
        self.assertFalse(blocked.allowed)
        self.assertIn("use_case_cannot_place_orders", blocked.reasons)

        live = evaluate_llm_action(use_case, action="ENABLE_LIVE")
        self.assertFalse(live.allowed)
        self.assertIn("live_trading_BLOCKED", live.reasons)

        inv = governance_inventory([use_case])
        self.assertEqual(inv["mcpOwner"], "modules.mcp / McpBridge")
        self.assertTrue(inv["truth"]["no_mcp_duplicate"])
        self.assertTrue(use_case.public_dict()["truth"]["does_not_own_mcp"])
        # Capability (summarize) ≠ authority to trade / enable live.
        self.assertFalse(use_case.public_dict()["canEnableLive"])


class StrategyLifecycleW55Tests(unittest.TestCase):
    def test_promotion_requires_evidence(self) -> None:
        life = StrategyLifecycle()
        life.upsert(StrategyLifecycleRecord(strategy_id="s1", version="1", state="SEALED_EVAL"))
        with self.assertRaises(ValueError):
            life.transition("s1", "1", new_state="PAPER", actor="pm", ts="t0")

        promoted = life.transition(
            "s1",
            "1",
            new_state="PAPER",
            actor="pm",
            ts="t1",
            evidence_key="sealed_holdout",
            evidence_state=MeasurementState.PASS.value,
        )
        self.assertEqual(promoted.state, "PAPER")
        self.assertEqual(promoted.evidence["sealed_holdout"], MeasurementState.PASS.value)


class EntitlementsW56Tests(unittest.TestCase):
    def test_cannot_approve_own_change_and_evaluate(self) -> None:
        self.assertTrue(cannot_approve_own_change(maker_id="alice", checker_id="Alice"))
        self.assertFalse(cannot_approve_own_change(maker_id="alice", checker_id="bob"))

        change = ChangeRequest(
            change_id="c1",
            kind="LIMIT_LOOSEN",
            maker_id="alice",
            payload={"maxGrossExposurePct": 200, "direction": "loosen"},
            required_authority="risk_officer",
        )
        denied = evaluate_approval(change, checker_id="alice", checker_roles=["risk_officer"])
        self.assertFalse(denied.allowed)
        self.assertIn("cannot_approve_own_change", denied.reasons)

        ok = evaluate_approval(change, checker_id="bob", checker_roles=["risk_officer"])
        self.assertTrue(ok.allowed)


class OrderLifecycleW57Tests(unittest.TestCase):
    def test_rejects_live_valid_and_invalid_transitions(self) -> None:
        life = OrderLifecycle()
        live = life.create(
            Order(order_id="o_live", symbol="AAPL", side="BUY", qty=1, mode="LIVE")
        )
        self.assertEqual(live.state, "REJECTED")
        self.assertEqual(live.reject_reason, "LIVE_TRADING_BLOCKED")

        paper = life.create(
            Order(order_id="o1", symbol="AAPL", side="BUY", qty=10, mode="PAPER")
        )
        life.transition("o1", new_state="RISK_CHECKED", ts="t1")
        life.transition("o1", new_state="ACCEPTED", ts="t2")
        life.transition("o1", new_state="FILLED", ts="t3", fill_qty=10)
        self.assertEqual(life.get("o1").state, "FILLED")

        paper2 = life.create(
            Order(order_id="o2", symbol="MSFT", side="BUY", qty=5, mode="PAPER")
        )
        with self.assertRaises(ValueError):
            life.transition("o2", new_state="FILLED", ts="t9")
        self.assertEqual(paper2.state, "CREATED")
        self.assertTrue(life.public_dict()["truth"]["live_trading_blocked"])


class TcaW58Tests(unittest.TestCase):
    def test_measurement_states(self) -> None:
        missing = analyze_fill(
            FillObservation(
                order_id="f1",
                symbol="AAPL",
                side="BUY",
                qty=10,
                fill_price=100.0,
            )
        )
        self.assertEqual(missing.implementation_shortfall.state, MeasurementState.UNMEASURED)
        self.assertEqual(missing.arrival_slippage_bps.state, MeasurementState.UNMEASURED)
        self.assertEqual(missing.fee_bps.state, MeasurementState.OBSERVED)

        full = analyze_fill(
            FillObservation(
                order_id="f2",
                symbol="AAPL",
                side="BUY",
                qty=10,
                fill_price=101.0,
                arrival_price=100.0,
                decision_price=100.0,
                fee=1.0,
            )
        )
        self.assertEqual(full.implementation_shortfall.state, MeasurementState.OBSERVED)
        self.assertAlmostEqual(float(full.implementation_shortfall.value), 100.0)
        self.assertAlmostEqual(float(full.arrival_slippage_bps.value), 100.0)


class CorporateActionsW59Tests(unittest.TestCase):
    def test_split_adjusts_qty_cost_and_pit_as_of(self) -> None:
        ca = CorporateAction(
            ca_id="ca1",
            instrument_id="EQ.A",
            ca_type="SPLIT",
            effective_time="2024-06-01T00:00:00+00:00",
            observed_at="2024-06-02T00:00:00+00:00",
            ratio=2.0,
        )
        before = apply_corporate_action(
            ca, qty=100, cost_basis=50.0, as_of="2024-05-01T00:00:00+00:00"
        )
        self.assertFalse(before["applied"])
        self.assertEqual(before["reason"], "before_effective_time")
        self.assertTrue(before["truth"]["point_in_time_respected"])

        after = apply_corporate_action(
            ca, qty=100, cost_basis=50.0, as_of="2024-06-01T00:00:00+00:00"
        )
        self.assertTrue(after["applied"])
        adj = after["adjustment"]
        self.assertEqual(adj["qtyAfter"], 200.0)
        self.assertEqual(adj["costBasisAfter"], 25.0)


class DurableWorkflowsW60Tests(unittest.TestCase):
    def test_checkpoint_and_resume_helpers(self) -> None:
        wf = DurableWorkflow(
            workflow_id="wf1",
            steps=(
                WorkflowStep("s1", "ingest"),
                WorkflowStep("s2", "reconcile"),
            ),
        )
        cp = start_workflow(wf, run_id="run1")
        self.assertEqual(cp.status, "PENDING")
        cp = advance_workflow(wf, cp)
        self.assertEqual(cp.current_index, 1)
        self.assertIn("s1", cp.step_results)

        resumed = resume_from_checkpoint(wf, cp.public_dict())
        self.assertEqual(resumed.current_index, 1)
        self.assertEqual(resumed.run_id, "run1")
        progress = workflow_progress(resumed, wf)
        self.assertEqual(progress["done"], 1)
        self.assertEqual(progress["total"], 2)


class AuditIntegrityW61Tests(unittest.TestCase):
    def test_append_and_detect_corruption_on_tamper(self) -> None:
        log = HashChainedAuditLog()
        log.append(
            event_id="e1",
            kind="LOGIN",
            actor="ops",
            detail="ok",
            ts="2024-01-01T00:00:00+00:00",
        )
        log.append(
            event_id="e2",
            kind="CHANGE",
            actor="ops",
            detail="limit",
            ts="2024-01-01T01:00:00+00:00",
        )
        verify = log.verify()
        self.assertTrue(verify["ok"])

        events = log.list_events()
        events[1]["detail"] = "tampered"
        corrupted = detect_corruption(events)
        self.assertFalse(corrupted["ok"])
        self.assertTrue(any("payload_tamper" in e for e in corrupted["errors"]))


class InstitutionalSloW62Tests(unittest.TestCase):
    def test_stale_is_degraded_not_green(self) -> None:
        fresh = next(s for s in DEFAULT_SLOS if s.slo_id == "slo_data_fresh")
        stale = evaluate_slo(fresh, value=48.0, state=MeasurementState.OBSERVED.value)
        self.assertIs(stale.meets_target, False)

        rollup = health_rollup([stale])
        self.assertEqual(rollup.overall, MeasurementState.FAIL.value)
        self.assertFalse(is_green_claim(rollup.overall))

        snap = institutional_slo_snapshot(
            {
                "slo_job_success": {"value": 0.995, "state": MeasurementState.OBSERVED.value},
                "slo_data_fresh": {"value": 72.0, "state": MeasurementState.OBSERVED.value},
                "slo_recon_open": {"value": 0.0, "state": MeasurementState.OBSERVED.value},
            },
            live_trading_blocked=True,
        )
        self.assertFalse(is_green_claim(snap["health"]["overall"]))
        self.assertTrue(snap["truth"]["live_trading_blocked"])


class ExceptionsOpsW63Tests(unittest.TestCase):
    def test_lifecycle_no_silent_auto_close(self) -> None:
        reg = ExceptionRegistry()
        reg.open(
            OpsException(
                exception_id="x1",
                kind="RECON",
                severity="HIGH",
                title="qty break",
            )
        )
        with self.assertRaises(ValueError):
            reg.transition("x1", new_status="RESOLVED", actor="bot", ts="t0", note="auto")

        reg.transition("x1", new_status="TRIAGED", actor="ops", ts="t1")
        reg.transition("x1", new_status="IN_PROGRESS", actor="ops", ts="t2")
        with self.assertRaises(ValueError):
            reg.transition("x1", new_status="RESOLVED", actor="ops", ts="t3", note="")
        closed = reg.transition(
            "x1", new_status="RESOLVED", actor="ops", ts="t4", note="fixed upstream"
        )
        self.assertEqual(closed.status, "RESOLVED")
        self.assertEqual(reg.open_items(), [])


class ResilienceW64Tests(unittest.TestCase):
    def test_backup_manifest_and_restore_hash_failure(self) -> None:
        docs = {"positions": {"A": 1}, "cash": {"USD": 100}}
        manifest = build_backup_manifest(
            manifest_id="b1",
            created_at="2024-01-01T00:00:00+00:00",
            documents=docs,
        )
        self.assertEqual(len(manifest.artifacts), 2)
        ok = verify_restore(manifest, docs)
        self.assertTrue(ok["ok"])

        bad = fault_inject(docs, corrupt_keys=["positions"])
        failed = verify_restore(manifest, bad)
        self.assertFalse(failed["ok"])
        self.assertTrue(any(e.startswith("hash_mismatch:") for e in failed["errors"]))


class SecurityHardeningW65Tests(unittest.TestCase):
    def test_redaction_of_secrets(self) -> None:
        out = redact_secrets(
            {
                "api_key": "super-secret",
                "password": "hunter2",
                "nested": {"token": "abc", "symbol": "AAPL"},
                "symbol": "AAPL",
            }
        )
        self.assertEqual(out["payload"]["api_key"], "***REDACTED***")
        self.assertEqual(out["payload"]["password"], "***REDACTED***")
        self.assertEqual(out["payload"]["nested"]["token"], "***REDACTED***")
        self.assertEqual(out["payload"]["nested"]["symbol"], "AAPL")
        self.assertIn("api_key", out["redactedKeys"])


class ApiSurfaceW66Tests(unittest.TestCase):
    def test_catalog_includes_institutional_paths(self) -> None:
        catalog = api_catalog_public()
        paths = {c["path"] for c in catalog["contracts"]}
        self.assertIn("/api/market-sim/institutional/gap-matrix", paths)
        self.assertIn("/api/market-sim/institutional/control-room", paths)
        self.assertTrue(any("/institutional/" in c.path for c in INSTITUTIONAL_API_CATALOG))
        check = check_institutional_api(
            [
                "/api/market-sim/status",
                "/api/market-sim/capabilities",
                "/api/market-sim/data",
            ]
        )
        self.assertTrue(check["ok"])
        blocked = [b for b in check["blocked"] if "live" in b["path"]]
        self.assertTrue(blocked)
        self.assertEqual(blocked[0]["status"], MeasurementState.BLOCKED.value)


class EventsW67Tests(unittest.TestCase):
    def test_contract_has_required_fields(self) -> None:
        catalog = event_catalog_public()
        self.assertGreater(catalog["count"], 0)
        for contract in INSTITUTIONAL_EVENT_CATALOG:
            self.assertTrue(contract.required_fields)
        ibor = next(c for c in INSTITUTIONAL_EVENT_CATALOG if c.event_type == "ibor_mutation")
        good = validate_event(
            "ibor_mutation",
            {
                "event_id": "e1",
                "sequence": 1,
                "kind": "CASH",
                "ts": "t",
                "payload": {},
            },
        )
        self.assertTrue(good["ok"])
        bad = validate_event("ibor_mutation", {"event_id": "e1"})
        self.assertFalse(bad["ok"])
        for field in ibor.required_fields:
            if field != "event_id":
                self.assertIn(field, bad["missingFields"])
        live = validate_event("live_order", {"order_id": "x"})
        self.assertEqual(live["status"], MeasurementState.BLOCKED.value)


class ControlRoomW68Tests(unittest.TestCase):
    def test_no_fake_green_when_health_unmeasured(self) -> None:
        snap = build_control_room_snapshot(generated_at="2024-01-01T00:00:00+00:00")
        self.assertEqual(snap.health["overall"], MeasurementState.UNMEASURED.value)
        self.assertFalse(is_green_claim(snap.overall_status))
        self.assertIn("health_UNMEASURED", snap.notes)
        self.assertTrue(snap.public_dict()["truth"]["no_fake_green"])
        self.assertEqual(
            snap.live_trading.get("LIVE_TRADING_AVAILABLE"),
            MeasurementState.BLOCKED.value,
        )


class ReportingW69Tests(unittest.TestCase):
    def test_pack_fingerprint_deterministic(self) -> None:
        kwargs = {
            "pack_id": "gov-1",
            "generated_at": "2024-01-01T00:00:00+00:00",
            "live_trading_status": {
                "LIVE_TRADING_AVAILABLE": MeasurementState.BLOCKED.value,
                "status": MeasurementState.PASS.value,
            },
            "health": {"overall": MeasurementState.UNMEASURED.value},
            "reconciliation": {"status": MeasurementState.EMPTY.value, "openCount": 0},
            "audit_verify": {"status": MeasurementState.PASS.value, "ok": True},
        }
        a = build_governance_report_pack(**kwargs).public_dict()
        b = build_governance_report_pack(**kwargs).public_dict()
        fp_a = _fingerprint(a)
        fp_b = _fingerprint(b)
        self.assertEqual(fp_a, fp_b)
        self.assertEqual(len(fp_a), 64)
        self.assertFalse(is_green_claim(a["overallStatus"]))


class IlliquidW70Tests(unittest.TestCase):
    def test_stale_valuation_explicit(self) -> None:
        reg = IlliquidRegistry()
        reg.register(
            IlliquidInstrument(
                instrument_id="PE.1",
                family="private_equity",
                name="Fund I",
                valuation_method="NOT_IMPLEMENTED",
            )
        )
        missing = reg.record_valuation(
            instrument_id="PE.1",
            as_of="2020-01-01T00:00:00+00:00",
            nav=None,
        )
        self.assertEqual(missing.nav.state, MeasurementState.UNMEASURED)
        self.assertIn("no_fabricated_mark", missing.nav.notes)

        stale = reg.record_valuation(
            instrument_id="PE.1",
            as_of="2020-01-01T00:00:00+00:00",
            nav=1_000_000.0,
            state=MeasurementState.ESTIMATED.value,
            source="stale_nav_packet",
            methodology="external_nav_ASSUMED",
        )
        self.assertEqual(stale.nav.state, MeasurementState.ESTIMATED)
        self.assertFalse(is_green_claim(stale.nav.state))
        self.assertEqual(stale.source, "stale_nav_packet")
        caps = reg.capability_matrix()
        self.assertTrue(
            all(f["valuation"] == MeasurementState.NOT_IMPLEMENTED.value for f in caps["families"])
        )


class ScaleBenchW71Tests(unittest.TestCase):
    def test_scale_bench_runs(self) -> None:
        out = run_scale_bench(
            cases=(BenchCase("tiny", 100, "unit"), BenchCase("small", 500, "unit")),
            work=lambda n: sum(range(n)),
            budget_sec=5.0,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["results"]), 2)
        self.assertTrue(out["truth"]["smoke_is_not_full_5y_benchmark"])
        self.assertTrue(all(r["ok"] for r in out["results"]))


class AssuranceW72Tests(unittest.TestCase):
    def test_run_assurance_pass_live_blocked_no_forbidden_owners(self) -> None:
        live = verify_live_trading_blocked()
        self.assertTrue(live["ok"])
        self.assertEqual(live["LIVE_TRADING_AVAILABLE"], MeasurementState.BLOCKED.value)

        report = run_assurance(roots=[CORE_ROOT])
        self.assertEqual(report.status, MeasurementState.PASS.value)
        self.assertFalse(any(f.severity == "CRITICAL" for f in report.findings))
        self.assertFalse(any(h.get("className") for h in report.forbidden_hits))
        self.assertTrue(report.live_trading.get("ok"))
        self.assertTrue(report.public_dict()["truth"]["live_trading_blocked"])


if __name__ == "__main__":
    unittest.main()
