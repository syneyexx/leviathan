"""MODULE provider adapter — market_sim mutations via ExecutionGateway."""

from __future__ import annotations

from typing import Any

from Data.modules.execution.types import CapabilityResult, CapabilityStatus

from .types import MarketSimError


class MarketSimModuleExecutor:
    """Dispatches catalogued market_sim.* MODULE capabilities to the control plane."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def execute_module_capability(
        self,
        capability_id: str,
        provider_ref: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any] | CapabilityResult:
        try:
            output = self._dispatch(provider_ref, arguments, run_id=run_id)
        except MarketSimError as exc:
            return CapabilityResult(
                request_id=request_id,
                capability_id=capability_id,
                status=CapabilityStatus.FAILED,
                error=str(exc),
                telemetry={"code": exc.code, "http_status": exc.http_status},
            )
        return {
            "capability_id": capability_id,
            "provider_ref": provider_ref,
            "output": output,
            "truth": {
                "via_execution_gateway": True,
                "paper_sim_only": True,
                "no_private_bypass": True,
            },
        }

    def _dispatch(
        self,
        provider_ref: str,
        arguments: dict[str, Any],
        *,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        svc = self.service
        action = provider_ref

        if action == "run.start":
            rid = str(arguments.get("run_id") or run_id or "")
            return {"run": svc.start_run(rid)}
        if action == "run.pause":
            rid = str(arguments.get("run_id") or run_id or "")
            return {"run": svc.pause_run(rid)}
        if action == "run.step":
            rid = str(arguments.get("run_id") or run_id or "")
            return {"run": svc.step_run(rid)}
        if action == "run.stop":
            rid = str(arguments.get("run_id") or run_id or "")
            return {"run": svc.stop_run(rid)}
        if action == "run.create":
            run = svc.create_run(**{k: v for k, v in _snake_args(arguments).items() if v is not None})
            return {"run": run}
        if action == "strategy.create":
            return svc.create_strategy(**_snake_args(arguments))
        if action == "strategy.version":
            sid = str(arguments.get("strategy_id") or "")
            return svc.version_strategy(sid, **_snake_args(arguments, skip={"strategy_id"}))
        if action == "strategy.fork":
            sid = str(arguments.get("strategy_id") or "")
            return svc.fork_strategy(sid, name=arguments.get("name"))
        if action == "strategy.archive":
            sid = str(arguments.get("strategy_id") or "")
            return {"strategy": svc.archive_strategy(sid)}
        if action == "strategy.promote":
            sid = str(arguments.get("strategy_id") or "")
            return {
                "strategy": svc.promote_strategy(
                    sid,
                    to_status=str(arguments.get("to_status") or arguments.get("toStatus") or ""),
                    reason=str(arguments.get("reason") or ""),
                    decided_by=str(arguments.get("decided_by") or arguments.get("decidedBy") or "operator"),
                    evidence=arguments.get("evidence"),
                )
            }
        if action == "strategy.validate":
            return svc.validate_strategy_dsl(dict(arguments.get("dsl_spec") or arguments.get("dslSpec") or {}))
        if action == "data.register":
            return {
                "source": svc.register_market_data(
                    str(arguments.get("path") or ""),
                    symbol=arguments.get("symbol"),
                    timeframe=arguments.get("timeframe"),
                )
            }
        if action == "data.import":
            return svc.import_market_dataset(
                str(arguments.get("path") or ""),
                symbol=arguments.get("symbol"),
                timeframe=arguments.get("timeframe"),
                seal=bool(arguments.get("seal", False)),
                role=str(arguments.get("role") or "RESEARCH"),
                provider=str(arguments.get("provider") or "csv_local"),
            )
        if action == "data.scan":
            return {"sources": svc.scan_market_data()}
        if action == "dataset.seal":
            return {
                "dataset": svc.seal_market_dataset(
                    str(arguments.get("dataset_id") or ""),
                    str(arguments.get("version") or ""),
                    role=str(arguments.get("role") or "SEALED_TEST"),
                )
            }
        if action == "paper.session.start":
            return {
                "session": svc.start_paper_session(
                    symbol=str(arguments.get("symbol") or ""),
                    strategy_id=arguments.get("strategy_id") or arguments.get("strategyId"),
                    strategy_version=arguments.get("strategy_version") or arguments.get("strategyVersion"),
                    broker_id=str(arguments.get("broker_id") or arguments.get("brokerId") or "local_paper"),
                    provider_id=str(arguments.get("provider_id") or arguments.get("providerId") or "binance_public"),
                    initial_cash=float(arguments.get("initial_cash") or arguments.get("initialCash") or 100_000.0),
                )
            }
        if action == "paper.order.place":
            return svc.paper_place_order(
                str(arguments.get("session_id") or ""),
                side=str(arguments.get("side") or ""),
                qty=float(arguments.get("qty") or 0),
                client_order_id=arguments.get("client_order_id") or arguments.get("clientOrderId"),
            )
        if action == "paper.kill_switch":
            return {
                "session": svc.paper_kill_switch(
                    str(arguments.get("session_id") or ""),
                    armed=bool(arguments.get("armed", True)),
                )
            }
        if action == "experiment.propose":
            return {
                "trial": svc.propose_experiment(
                    strategy_id=str(arguments.get("strategy_id") or arguments.get("strategyId") or ""),
                    hypothesis=str(arguments.get("hypothesis") or ""),
                    proposer_agent_id=str(
                        arguments.get("proposer_agent_id") or arguments.get("proposerAgentId") or ""
                    ),
                    source_id=str(arguments.get("source_id") or arguments.get("sourceId") or ""),
                    acceptance_criteria=arguments.get("acceptance_criteria")
                    or arguments.get("acceptanceCriteria"),
                    seed=int(arguments.get("seed") or 42),
                    config=arguments.get("config"),
                )
            }
        if action == "experiment.complete":
            run_ids = arguments.get("run_ids") or arguments.get("runIds")
            if isinstance(run_ids, str):
                run_ids = [run_ids]
            return {
                "trial": svc.complete_experiment(
                    str(arguments.get("trial_id") or ""),
                    metrics=dict(arguments.get("metrics") or {}) or None,
                    strategy_version=arguments.get("strategy_version") or arguments.get("strategyVersion"),
                    run_id=arguments.get("run_id") or arguments.get("runId"),
                    run_ids=list(run_ids) if run_ids else None,
                )
            }
        if action == "demo.run":
            return svc.run_market_demo(
                family=str(arguments.get("family") or "crypto_spot"),
                bars_limit=int(arguments.get("bars_limit") or arguments.get("barsLimit") or 120),
            )
        if action == "campaign.create":
            args = _snake_args(arguments)
            return {
                "campaign": svc.create_research_campaign(
                    strategy_id=str(args.get("strategy_id") or ""),
                    hypothesis=str(args.get("hypothesis") or ""),
                    proposer_agent_id=str(args.get("proposer_agent_id") or "human"),
                    source_id=args.get("source_id"),
                    seed=int(args.get("seed") or 42),
                    config=args.get("config"),
                    acceptance_criteria=args.get("acceptance_criteria"),
                    n_bars=args.get("n_bars"),
                )
            }
        if action == "campaign.start":
            return {
                "campaign": svc.start_research_campaign(
                    str(arguments.get("campaign_id") or arguments.get("campaignId") or "")
                )
            }
        if action == "campaign.pause":
            return {
                "campaign": svc.pause_research_campaign(
                    str(arguments.get("campaign_id") or arguments.get("campaignId") or "")
                )
            }
        if action == "campaign.resume":
            return {
                "campaign": svc.resume_research_campaign(
                    str(arguments.get("campaign_id") or arguments.get("campaignId") or "")
                )
            }
        if action == "campaign.advance":
            return {
                "campaign": svc.advance_research_campaign(
                    str(arguments.get("campaign_id") or arguments.get("campaignId") or ""),
                    trial_id=arguments.get("trial_id") or arguments.get("trialId"),
                )
            }
        if action == "campaign.cancel":
            return {
                "campaign": svc.cancel_research_campaign(
                    str(arguments.get("campaign_id") or arguments.get("campaignId") or "")
                )
            }
        if action == "gym.episode.create":
            args = _snake_args(arguments)
            return svc.create_gym_episode(
                source_id=args.get("source_id"),
                bars_path=args.get("bars_path"),
                curriculum_stage=str(args.get("curriculum_stage") or "trend"),
                seed=int(args.get("seed") or 42),
                start_index=int(args.get("start_index") or 0),
                end_index=args.get("end_index"),
                initial_cash=float(args.get("initial_cash") or 100_000.0),
                dataset_id=args.get("dataset_id"),
                dataset_version=args.get("dataset_version"),
            )
        if action == "gym.episode.step":
            return svc.gym_step(
                str(arguments.get("episode_id") or arguments.get("episodeId") or ""),
                action=str(arguments.get("action") or "HOLD"),
            )
        if action == "gym.scorecard.create":
            args = _snake_args(arguments)
            return {
                "scorecard": svc.create_agent_scorecard(
                    agent_id=str(args.get("agent_id") or ""),
                    equity=list(args.get("equity") or []),
                    agent_version=str(args.get("agent_version") or "v1"),
                    regime=str(args.get("regime") or "all"),
                    year=args.get("year"),
                    violations=args.get("violations"),
                    token_cost=int(args.get("token_cost") or 0),
                    latency_ms=float(args.get("latency_ms") or 0.0),
                    n_episodes=int(args.get("n_episodes") or 1),
                    timeframe=str(args.get("timeframe") or "1h"),
                )
            }
        if action == "gym.readiness.set":
            args = _snake_args(arguments)
            return {
                "readiness": svc.set_agent_readiness(
                    str(args.get("agent_id") or ""),
                    level=str(args.get("level") or "A0"),
                    measurement=str(args.get("measurement") or "UNMEASURED"),
                    reason=str(args.get("reason") or ""),
                    evidence=args.get("evidence"),
                )
            }
        if action == "gym.export":
            args = _snake_args(arguments)
            return {
                "export": svc.export_gym_trajectory(
                    str(args.get("episode_id") or ""),
                    dest_path=args.get("dest_path"),
                    sealed_windows=args.get("sealed_windows"),
                )
            }
        if action == "gym.sim_real_gap":
            args = _snake_args(arguments)
            return {
                "report": svc.create_sim_real_gap_report(
                    sim_fills=list(args.get("sim_fills") or arguments.get("simFills") or []),
                    paper_fills=list(args.get("paper_fills") or arguments.get("paperFills") or []),
                    calibration_source_ids=args.get("calibration_source_ids")
                    or arguments.get("calibrationSourceIds"),
                    evaluation_source_ids=args.get("evaluation_source_ids")
                    or arguments.get("evaluationSourceIds"),
                )
            }
        raise MarketSimError(
            "UNKNOWN_MODULE_ACTION",
            f"Unsupported market_sim module action: {provider_ref}",
            http_status=500,
        )


def _snake_args(arguments: dict[str, Any], *, skip: set[str] | None = None) -> dict[str, Any]:
    """Normalize camelCase API args to snake_case kwargs."""
    skip = skip or set()
    mapping = {
        "sourceId": "source_id",
        "strategyId": "strategy_id",
        "strategyVersion": "strategy_version",
        "startTs": "start_ts",
        "endTs": "end_ts",
        "initialCash": "initial_cash",
        "feeBps": "fee_bps",
        "slippageBps": "slippage_bps",
        "maxPositionPct": "max_position_pct",
        "maxDrawdownPct": "max_drawdown_pct",
        "perTradeRiskPct": "per_trade_risk_pct",
        "deliberationEveryN": "deliberation_every_n",
        "stochasticSlippage": "stochastic_slippage",
        "gameMode": "game_mode",
        "entryRules": "entry_rules",
        "exitRules": "exit_rules",
        "riskRules": "risk_rules",
        "requiredTimeframes": "required_timeframes",
        "brainDependencies": "brain_dependencies",
        "dslSpec": "dsl_spec",
        "barsLimit": "bars_limit",
        "acceptanceCriteria": "acceptance_criteria",
        "proposerAgentId": "proposer_agent_id",
        "clientOrderId": "client_order_id",
        "brokerId": "broker_id",
        "providerId": "provider_id",
        "campaignId": "campaign_id",
        "trialId": "trial_id",
        "nBars": "n_bars",
        "barsPath": "bars_path",
        "curriculumStage": "curriculum_stage",
        "startIndex": "start_index",
        "endIndex": "end_index",
        "initialCash": "initial_cash",
        "datasetId": "dataset_id",
        "datasetVersion": "dataset_version",
        "episodeId": "episode_id",
        "agentId": "agent_id",
        "agentVersion": "agent_version",
        "tokenCost": "token_cost",
        "latencyMs": "latency_ms",
        "nEpisodes": "n_episodes",
        "destPath": "dest_path",
        "sealedWindows": "sealed_windows",
        "simFills": "sim_fills",
        "paperFills": "paper_fills",
        "calibrationSourceIds": "calibration_source_ids",
        "evaluationSourceIds": "evaluation_source_ids",
    }
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        if key in skip:
            continue
        dest = mapping.get(key, key)
        if dest in skip:
            continue
        # Prefer already-snake keys if both present
        if dest not in out or key == dest:
            out[dest] = value
    return out
