# BACKEND CAPABILITY MATRIX — Trading Center WAVE 0

Inventory of MarketSim / Trading domain capabilities.  
Status uses: **COMPLETE | PARTIAL | STUB | BLOCKED | UNAVAILABLE**.

Columns:

| Column | Meaning |
|---|---|
| Capability | Operator-facing name |
| Backend authority | Canonical module/class |
| API / worker contract | HTTP + worker IDs |
| Operational status | COMPLETE / PARTIAL / STUB / BLOCKED / UNAVAILABLE |
| Already in UI? | Legacy route exposure |
| Operator access? | Yes / No / Boundary-only |
| Target workspace | One of the four |
| Target surface | PRIMARY / SECONDARY / ADVANCED |
| R/W | Read / Write / Both |
| Safety constraints | Hard limits |
| Test coverage | Representative suites |

---

## A. Control plane & observability

| Capability | Backend authority | API / worker | Status | Already in UI? | Operator? | Target workspace | Target surface | R/W | Safety | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| MarketSim control plane | `market_sim.service.MarketSimControlPlane` | `/api/market-sim/*`; workers `market_sim.*` | COMPLETE | Yes (all trading pages) | Yes | Command Hub | PRIMARY (status strip) | Both | Feature-gated; live blocked | `test_market_sim*.py` |
| Capability / mode matrix | `market_sim.capabilities.build_market_capabilities` | `GET /api/market-sim/capabilities` | COMPLETE | Partial (broker + contracts) | Yes | Command Hub + Market Data | PRIMARY badges; ADVANCED full matrix | Read | Adapter-derived; never UI-inferred | `test_capability_contract_drift.py`, FE `marketSimCapabilitiesContracts` |
| Trading action matrix | `market_sim.trading_action_matrix` | Embedded in capabilities payload | COMPLETE | No dedicated UI | Yes | Command Hub | ADVANCED | Read | Live money always BLOCKED | Action matrix unit paths + gates JSON |
| Status / health | ControlPlane status + feed metrics | `GET /status`, `/health`, feed metrics | COMPLETE | Yes (simulatie, strips) | Yes | Command Hub | PRIMARY | Read | Degraded ≠ healthy | `test_trading_observability_w18.py` |
| Institutional gap matrix | `institutional_core.gap_ledger` | `GET /institutional/gap-matrix` | PARTIAL | Yes (control-room) | Yes | Command Hub | ADVANCED | Read | Honest PARTIAL/NOT_IMPLEMENTED rows | Institutional hardening suites |
| Control room projection | `institutional_core.control_room` | `GET /institutional/control-room` | PARTIAL | Yes `/trading/control-room` | Yes | Command Hub | ADVANCED | Read (+ limited write) | Read-mostly; notes/pipeline writes not fully exposed | Control-room FE tests + institutional |

---

## B. Research Lab / learning / strategies

| Capability | Backend authority | API / worker | Status | Already in UI? | Operator? | Target workspace | Target surface | R/W | Safety | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| Research Lab learning runtime | `agent_lab`, `learning_runtime.run_learning_on_worker` | `/lab/runs*` lifecycle; worker `market_sim.learning_run` | COMPLETE | Yes `/trading/lab` | Yes | Strategy Lab | PRIMARY | Both | Live_money stamped BLOCKED; sealed lineage | `test_trading_lab_w13..w17*.py`, `test_strategy_learning.py` |
| Lab overview / trials | Lab plane | `/lab/overview`, `/lab/trials` | COMPLETE | Yes (lab) | Yes | Strategy Lab | PRIMARY | Read | — | Lab suites |
| Cost pack | Lab cost pack | `GET /lab/cost-pack` | COMPLETE | Yes (lab Analytics) | Yes | Strategy Lab | ADVANCED | Read | Budget visibility only | Lab suites |
| Hypotheses | `research_hypothesis` | `/lab/runs/{id}/hypotheses`, `/lab/hypotheses/{id}` | COMPLETE | Yes (lab tab) | Yes | Strategy Lab | ADVANCED | Read | Public falsifiable claims only | `test_research_hypothesis_w1.py` |
| Perception (numeric + chart) | `research_perception`, `chart_perception` / `chart_batch` | `/lab/runs/{id}/perception`; worker `market_sim.chart.render_batch` | COMPLETE | Yes (lab tab) | Yes | Strategy Lab | ADVANCED | Read | VLM advisory-only; cannot order | Lab + chart paths |
| Generations / populations | Learning runtime + store | `/generations`, `/candidates` | COMPLETE | Yes (lab tabs) | Yes | Strategy Lab | ADVANCED | Read | Bounded evolution | Learning suites |
| Candidate generation | `learning_candidates`, `strategy_search_grammar` | Via learning worker + candidates API | COMPLETE | Yes (Population) | Yes | Strategy Lab | PRIMARY (table) + ADVANCED | Read | Leakage tags fail-closed | `test_wave5_strategy_discovery.py` |
| Candidate explainability | `candidate_explainability` | `GET .../candidates/{id}/explain` | COMPLETE | **No** (API not in FE client) | Yes | Strategy Lab | ADVANCED drawer | Read | Explain ≠ promote | Backend explain paths |
| Lineage | `strategy_lineage` | Lab lineage / strategy assets | COMPLETE | Yes (lab Lineage) | Yes | Strategy Lab | ADVANCED | Read | Rename ≠ new root | Lifecycle persist tests |
| Lessons / memory | `lesson_trust`, `lesson_retrieval`, `learning_memory` | `/lab/runs/{id}/lessons` | COMPLETE | Yes (lab Lessons) | Yes | Strategy Lab | ADVANCED | Read | SEALED = adaptive sink | `test_wave6_learning_memory.py`, `test_verified_learning_w11.py` |
| Strategy families | `strategy_families` | `GET /strategy-families` | COMPLETE | Partial (lab + strategies) | Yes | Strategy Lab | SECONDARY | Read | DSL kinds only | `test_strategy_families_registry.py` |
| Strategy versions / fork / archive | `strategy_dsl`, ControlPlane strategy APIs | `/strategies*`, versions, fork, archive | COMPLETE | Yes `/trading/strategieen` | Yes | Strategy Lab | PRIMARY | Both | Python code strategies UNAVAILABLE | `test_market_sim_p2_strategies.py` |
| Python code strategies | `code_strategy` | N/A (refused) | UNAVAILABLE | N/A | No | — | — | — | FEATURE_GATED / NOT_AVAILABLE | Explicit refuse tests |
| Historical simulation / replay engine | `engine.SimulationEngine`, `causality`, `gym` | `/runs*`, `/gym/episodes*`; workers `advance`, `gym_episode` | COMPLETE | Yes `/trading/simulatie`; gym **weak UI** | Yes | Strategy Lab (runs) + Market Data (replay sampling) | PRIMARY runs; ADVANCED gym | Both | Causal next-bar fills | `test_market_sim_t1_causality.py`, `test_market_sim_p0_kernel.py`, `p1_gym` |
| Experiments | `experiments` | `/experiments*` | COMPLETE | Partial (control-room projection) | Yes | Strategy Lab | SECONDARY | Both | — | Campaign / experiment tests |
| Research Command composition | `research_command.service.ResearchCommandService` | `/research-command*` | COMPLETE | Yes `/trading/onderzoek` | Yes | Command Hub | PRIMARY | Both | Paper flatten/kill only; strips private CoT | `test_research_command.py` |

---

## C. Qualification, promotion, validation

| Capability | Backend authority | API / worker | Status | Already in UI? | Operator? | Target workspace | Target surface | R/W | Safety | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| QualificationAuthority (Q01–Q11) | `qualification.QualificationAuthority` | `/qualification-runs*`; worker `market_sim.qualification_run` | COMPLETE | Partial (lab Validation + control-room; limited write UI) | Yes | Strategy Lab (ladder) + Command Hub (attention) | PRIMARY ladder; ADVANCED gate detail | Both | Fail-closed; ignores caller `passed=true`; TRAIN-only cannot qualify | `test_qualification_authority_w2*.py`, `test_e2e_qualification_promotion_w35.py` |
| Q01 Data certification | Gate + dataset cert | Dataset certification + qual gates | COMPLETE | Partial | Yes | Market Data (cert) + Strategy Lab (gate) | PRIMARY / ADVANCED | Both | Provenance required | Cert + qual suites |
| Q02 Reproducibility | Gate | Qual gates | COMPLETE | Partial | Yes | Strategy Lab | ADVANCED | Read | Hash/provenance fields | Qual suites |
| Q03 Baseline acceptance | Gate | Qual gates | COMPLETE | Partial | Yes | Strategy Lab | ADVANCED | Read | Always required institutional path | Qual suites |
| Q04 Walk-forward | `wfa` + gate | Qual / `list_wfa_folds` | COMPLETE | Partial (no dedicated WFA UI) | Yes | Strategy Lab | ADVANCED | Read | Insufficient folds → fail | `test_wfa_fold_evaluator_w6.py` |
| Q05 Statistical multiplicity | `stats_inferential` + gate | Qual extras | PARTIAL | Minimal | Yes | Strategy Lab | ADVANCED | Read | Needs performance matrix else UNMEASURED | Qual wave tests |
| Q06 Regime matrix | `regimes` + gate | Qual / perception | PARTIAL | Partial | Yes | Strategy Lab + Market Data (regime monitor) | ADVANCED / SECONDARY | Read | Deterministic COMPLETE; HMM FEATURE_GATED | Regime fingerprint tests |
| Q07 Adversarial robustness | `robustness` + gate | Qual path (no standalone adversarial API) | PARTIAL | No dedicated page | Yes | Strategy Lab | ADVANCED | Read | Real rerun IDs required | `test_robustness_harness_w8.py`, adversarial suites |
| Q08 Execution validity | Gate + `execution` / `sim_to_paper_gap` | Qual + `/paper-deployments/{id}/execution-calibration` | PARTIAL | Client present; weak UI | Yes | Trading Desk + Strategy Lab | ADVANCED | Read | BAR/L1 only; L2/L3 UNAVAILABLE | `test_e2e_paper_calibration_w36.py` |
| Q09 Capacity | `capacity_qualification` | Qual extras | PARTIAL | Minimal | Yes | Strategy Lab | ADVANCED | Read | Defaults UNMEASURED; can FAIL | Qual capacity paths |
| Q10 Sealed holdout | `sealed_attempts.SealedAttemptBinder` | Dataset seal + qual | COMPLETE | Partial | Yes | Strategy Lab + Market Data (seal) | ADVANCED / PRIMARY seal | Both | Single-use lineage; second attempt blocked | Integrity + sealed tests |
| Q11 Portfolio compatibility | Gate + portfolio strategy-risk | `/portfolios/{id}/strategy-risk` + qual | PARTIAL | Partial (portefeuille risk) | Yes | Trading Desk + Strategy Lab | ADVANCED | Read | UNMEASURED fail-closed when required | Portfolio risk governance |
| Promotion (A2–A4 paper) | `promotion.evaluate_promotion`, `readiness`, `strategy_asset.promote_asset` | `POST .../paper/deployments/{id}/promote` | COMPLETE | Partial (paper/lab) | Yes | Strategy Lab (ready queue) + Trading Desk (deploy) | PRIMARY | Write | Never enables live; `assert_not_live_level` | `test_promotion_qualification_adapter_w12.py`, e2e w35 |
| Out-of-sample / splits | `split_manifest.DatasetSplitManifest` | Dataset seal + learning | COMPLETE | Partial (lab Validation) | Yes | Strategy Lab | ADVANCED | Read | TRAIN cannot qualify | `test_e2e_research_integrity_w23.py` |
| Contamination / leakage firewall | `epistemic.EpistemicFirewall`, grammar leakage | Bound into lab/qual/data | COMPLETE | Indirect | Yes (truth flags) | Command Hub (attention) + Strategy Lab | ADVANCED | Read | Future-ts refused; SEALED not adaptive prior | Integrity + causality tests |

---

## D. Paper execution, portfolios, orchestra

| Capability | Backend authority | API / worker | Status | Already in UI? | Operator? | Target workspace | Target surface | R/W | Safety | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| Paper deployments | `paper_deployment` | `/paper/deployments*` | COMPLETE | Yes `/trading/paper` | Yes | Trading Desk | PRIMARY | Both | Incompatible rejected; live BLOCKED | `test_market_sim_p4_paper.py`, A4 loop |
| Shadow observe | Paper deployment | `POST .../shadow-observe` | COMPLETE | Client yes; UI weak | Yes | Trading Desk | ADVANCED | Write | Shadow no live orders | Paper suites |
| Autonomous paper step | `autonomous_paper_loop` | `POST .../autonomous-step`; worker `autonomous_step` | COMPLETE | Yes (paper operator) | Yes | Trading Desk | PRIMARY | Write | Kill-switch + feed health | `test_autonomous_paper_a4_loop.py` |
| Drift review | `paper_forward_drift` | `POST .../drift-review` | COMPLETE | Client yes; UI weak | Yes | Trading Desk | ADVANCED | Write | Min sample required | Paper forward tests |
| Paper sessions / orders | `paper_broker`, RiskGuard | `/paper/sessions*`, orders, kill-switch | COMPLETE | Yes (paper) | Yes | Trading Desk | PRIMARY | Both | Local ledger; not exchange-matched | Paper suites |
| Paper fills / positions | `execution`, `fill_model`, portefeuille ledger | Portfolio/paper APIs | COMPLETE | Yes (paper + portefeuille) | Yes | Trading Desk | PRIMARY | Both | RiskGuard veto | Paper + portefeuille |
| Portfolios (Portefeuille) | `portefeuille.service.PortfolioService` | `/portfolios*` full surface | COMPLETE | Yes `/trading/portefeuille` | Yes | Trading Desk | PRIMARY | Both | Paper capital; risk-loosen approval | `test_portefeuille_paper.py` |
| Allocations / rebalance | Portefeuille | allocations + rebalance preview/execute | COMPLETE | Yes | Yes | Trading Desk | SECONDARY | Both | Preview before execute | Portefeuille tests |
| Recommendations / export | `portefeuille.recommendations`, export | recommendations + export | COMPLETE | Yes | Yes | Trading Desk | ADVANCED | Both | — | Portefeuille tests |
| Portfolio tick | Portfolio service | `POST .../tick`; worker `portfolio_tick` | COMPLETE | Indirect | Yes | Trading Desk | ADVANCED | Write | — | Portefeuille |
| Agent wallets | `accounting.WalletLedger` | Via runs/live + paper metadata | COMPLETE | **Weak** (no dedicated wallets surface) | Yes | Trading Desk | PRIMARY (wallets panel) | Read | Never mix agent wallets | Kernel + paper tests |
| Trade Orchestra | `orchestra.service.TradingOrchestraService` | `/orchestras*`, missions, autonomy | COMPLETE | Partial (Agents section + Research Command) | Yes | Trading Desk (fleet) + Command Hub (session) | PRIMARY fleet; ADVANCED config | Both | Mandate loosen needs approval; paper routing | `test_trading_orchestra.py` |
| Decision records | Orchestra decisions + `decision_ledger` | `/decisions`, orchestra decisions | COMPLETE | Partial (onderzoek + control-room) | Yes | Command Hub | SECONDARY | Read | Public decisions; no private CoT | Orchestra + institutional |
| News feeds / signals | `orchestra.news` | `/news/feeds*`, poll, items, signals | COMPLETE | Yes (onderzoek feed mgmt) | Yes | Command Hub + Market Data (feeds) | SECONDARY | Both | Poll via provider_io | Orchestra / research command |
| Trading agents (roles) | Orchestra roles + institutional_team | Orchestra members/missions | COMPLETE | Partial | Yes | Trading Desk | ADVANCED fleet | Both | Agents cannot enable live | Orchestra + lab roles |
| RiskGuard envelope | `risk_guard` | Bound into paper/portfolio | COMPLETE | Yes (paper risk + portefeuille) | Yes | Trading Desk | PRIMARY | Read (+ governed write) | UNKNOWN ≠ HEALTHY | `test_wave18_paper_safety_kill.py` |
| Kill switch | Paper + portfolio + research command | Multiple kill-switch endpoints | COMPLETE | Yes | Yes | Trading Desk + Command Hub | PRIMARY | Write | Durable; blocks new orders | Kill-switch tests |
| Live / broker trading | `LiveTradingGuard`, `trading.stub.TradingStub` | `GET /live-trading`; UI `/trading/broker` | BLOCKED | Yes (boundary page) | Boundary-only | Trading Desk + Command Hub | PRIMARY badge **PAPER ONLY / BLOCKED** | Read | Always BLOCKED | Live guard + broker page |
| `Data/modules/trading` domain | `trading/stub.py` | Refuse-only | STUB | Broker reflects block | No (as engine) | — | — | — | Not a live engine | Stub tests |

---

## E. Market data, feeds, certification

| Capability | Backend authority | API / worker | Status | Already in UI? | Operator? | Target workspace | Target surface | R/W | Safety | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| Offline historical market data | `data_store.MarketDataStore`, `ohlcv`, `dataset_pipeline` | `/data*`, `/datasets*`; workers `data.scan|import|validate|profile|convert` | COMPLETE | Yes `/trading/marktdata` | Yes | Market Data | PRIMARY | Both | Symlink-safe scans; PIT as-of | `test_market_data_quality_w06.py` |
| Live public market data | Providers + feed runtime | `/market/bars`, `/feeds*`, providers | PARTIAL | Partial | Yes | Market Data | PRIMARY | Both | Quotes ≠ live money; family gaps | Feed + provider tests |
| Providers (CSV, Binance, Stooq) | `providers/*`, ProviderRegistry | `/providers`, import | PARTIAL | Yes (marktdata limits) | Yes | Market Data | SECONDARY | Both | Reachability probed | `test_market_provider_hardening.py` |
| Feed runtime / health | `feed.runtime.FeedRuntime`, ordering/capture | `/feeds*`, metrics, snapshot; `/lab/feed-health` | COMPLETE | Partial (lab feed-health + marktdata health) | Yes | Market Data | PRIMARY | Both | Stale/GAP/UNMEASURED block blind orders | `test_market_feed_runtime.py` |
| Ingestion / sync jobs | Dataset pipeline + scan workers | data scan/import; `scan-batch` | COMPLETE | Partial (scan/register; batch weak UI) | Yes | Market Data | SECONDARY | Write | Worker durable jobs | Data quality + pipeline |
| Dataset seal | Split manifest + plane | `POST /datasets/{id}/{version}/seal` | COMPLETE | Weak UI | Yes | Market Data | ADVANCED | Write | Sealed holdout semantics | Integrity suites |
| Data certification | Plane cert evaluate/get | `/datasets/{id}/certification*` | COMPLETE | Partial (marktdata quality + control-room) | Yes | Market Data | PRIMARY | Both | Persist cert/PIT | `test_cert_tca_qualification_worker_*` |
| Provenance / hashes | `hashes`, qualification context | Bound into cert/qual | COMPLETE | Indirect | Yes | Market Data | ADVANCED | Read | Required for Q02 | Qual suites |
| Point-in-time fabric | `pit_fabric` | Bound into data paths | COMPLETE | **ABSENT dedicated UI** | Yes (advanced) | Market Data | ADVANCED | Read | Causality firewall | PIT / integrity |
| Market regimes (deterministic) | `regimes` | Via perception/qual | PARTIAL | Partial | Yes | Market Data + Strategy Lab | SECONDARY monitor | Read | HMM FEATURE_GATED | Regime tests |
| HMM regimes | `regimes.hmm_regime_capability` | N/A gated | BLOCKED / FEATURE_GATED | No | No (as ready) | — | — | — | Do not show as operational | Capability matrix |
| Replay & sampling config | Engine + data store | Runs + bars + (future replay UX) | COMPLETE (engine) / PARTIAL (UX) | Simulatie only | Yes | Market Data | ADVANCED | Both | Realistic latency optional; indicators advisory | Causality + gym |
| Equity / crypto-spot hist+paper | `capabilities` families | Mode matrix | COMPLETE | Via capabilities | Yes | Market Data / Desk | PRIMARY | — | Live BLOCKED | Capabilities + e2e demos |
| Futures / FX historical sim | `futures_contracts`, `fx` | Mode matrix | COMPLETE (hist) | Weak | Yes (hist only) | Strategy Lab / Market Data | ADVANCED | Read/sim | Paper NOT_IMPLEMENTED | Futures/FX notes in capabilities |
| Futures / FX / options / FI paper | capabilities | Mode matrix | UNAVAILABLE | No | No | — | Show UNAVAILABLE in matrix only | — | NOT_IMPLEMENTED | capabilities.py |
| L2/L3 book execution | execution granularity matrix | N/A | UNAVAILABLE | No | No | — | — | — | OHLCV-only | granularity matrix |
| Alpaca paper (optional) | provider_io secrets | Capabilities paper_brokers | PARTIAL | Indirect | Yes when secrets present | Trading Desk | ADVANCED | Both | Paper secrets ≠ live | capabilities `_alpaca_paper_configured` |

---

## F. Institutional ops (operator-relevant subset)

| Capability | Backend authority | API / worker | Status | Already in UI? | Operator? | Target workspace | Target surface | R/W | Safety | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| Reconciliation | `institutional_core.reconciliation` | `POST /institutional/reconciliation` | PARTIAL | Yes (control-room breaks) | Yes | Command Hub | ADVANCED | Both | Do not claim full IBOR | Institutional suites |
| Exceptions | `exceptions_ops` | `GET /institutional/exceptions` | PARTIAL | Yes (control-room) | Yes | Command Hub | SECONDARY | Read | — | Institutional |
| Audit verify | `audit_integrity` | `GET /institutional/audit/verify` | PARTIAL | Yes (control-room) | Yes | Command Hub | ADVANCED | Read | Hash chain verify | Institutional |
| Authority request/approve | Institutional authority | `/institutional/authority/request|approve` | PARTIAL | **No UI** | Yes (governed) | Command Hub | ADVANCED | Write | Approval capability required | Institutional |
| Multi-asset readiness | `multi_asset` | `GET /institutional/multi-asset` | PARTIAL | Yes (control-room) | Yes | Command Hub | ADVANCED | Read | Honest gaps | Institutional |
| Assurance | `assurance` | GET/POST `/institutional/assurance` | PARTIAL | Partial | Yes | Command Hub | ADVANCED | Both | — | Institutional |
| Enterprise risk (beyond RiskGuard) | `enterprise_risk` | Via institutional surfaces | PARTIAL | Partial | Limited | Trading Desk / Command Hub | ADVANCED | Read | Paper RiskGuard is canonical for trading | Gap ledger |

---

## Status rollup

| Status | Count (approx) | Action for migration |
|---|---|---|
| COMPLETE | ~40 | Must be reachable if operator-relevant |
| PARTIAL | ~18 | Expose honestly; finish when in-scope; else blocker |
| STUB | 1 (`trading` module) | Never present as engine |
| BLOCKED | Live trading + HMM as ready | Show blocked truth |
| UNAVAILABLE | Code strategies, options/FI trading, L2/L3, futures/FX paper | Matrix only; no fake UI |

## Explicit non-capabilities (do not invent UI)

- Manifest-only / gap_ledger historical `NOT_IMPLEMENTED` rows without runtime upgrade
- Python strategy code path
- Live broker order placement
- Synthetic L2 book trading
- HMM regime as production detector
- Control-room “Add Note” / “View Pipeline” disabled stubs
- Lab “Edit metadata / Clone / Export” disabled stubs
