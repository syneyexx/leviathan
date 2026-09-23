# Data/modules

Long-lived / stateful domain systems for LEVIATHAN.

## Current modules

| Module | Ownership |
|---|---|
| `reasoning/` | `ReasoningEngine`, `ReasoningPlan` (legacy classifier) |
| `cognition/` | **Cognitive Runtime** — TaskModel, BeliefState, WorkingMemory, Perception, MetaController, loop, VerifiedExperience |
| `settings/` | **Settings Control Plane** — operator catalog, SQLite overrides, hot/restart apply |
| `context/` | `ContextBuilder`, `ContextPack` |
| `model_runtime/` | `OpenAICompatibleLLM`, `LLMUnavailable` |
| `run/` | `RunStore`, Run lifecycle + versioned `EventEnvelope` |
| `artifacts/` | `ArtifactStore`, content hash provenance |
| `knowledge/` | Knowledge V2 documents/chunks/hybrid retrieval |
| `function_runtime/` | FunctionRegistry + lazy ON_DEMAND runtime |
| `execution/` | CapabilityCatalog + ExecutionGateway + FrontierCapabilityManifest |
| `approvals/` | PolicyEngine + ApprovalStore + ApprovalService + AuthorityProfile |
| `jobs/` | JobStore + JobRuntime + ResourceManager + leases/budgets |
| `observations/` | ToolObservation + durable effect ledger |
| `evidence/` | EvidenceStore + EvidenceService |
| `memory/` | MemoryStore (controlled; not Knowledge) |
| `verification/` | VerificationEngine (evidence-based) |
| `agents/` | AgentRuntime (shared gateway only; flagged) |
| `workflows/` | WorkflowStore + WorkflowRuntime |
| `schedules/` | ScheduleStore + ScheduleRunner |
| `observability/` | ObservabilityHub (in-process; not APM) |
| `neuro/` | NeuroAdvisor + residual/cortex/critic/memory/adapters/snapshots (advisory; never authority) |
| `module_manager/` | Universal Module Manager — single `ILeviathanModule` loader (+ optional subprocess) |
| `plugins/` | PluginRegistry (declarative → catalog; not a second loader) |
| `mcp/` | Universal MCP Bridge (one bridge / many sessions; Tools provider) |
| `evaluation/` | EvaluationHarness + EvaluationPlatform (+ neuro ablations, scorecards, regression corpus) |
| `isolation/` | IsolationGuard |
| `training/` | TrainingRegistry stub + TrainingRecipeRegistry |
| `browser/` | BrowserAutomationStub |
| `media/` | MediaAutomationStub |
| `voice/` | VoiceRuntimeStub |
| `release/` | ReleaseGateRunner + evaluation relevance |
| `security/` | SecurityAuditor (posture, not pentest) |
| `native/` | NativeRuntimeStub |
| `trading/` | TradingStub (real broker refused) |
| `market_sim/` | MarketSimControlPlane + causal engine + multi-agent worker (flagged) |
| `backup/` | BackupService (local SQLite snapshots) |
| `metrics/` | MetricsCollector (in-process) |
| `chaos/` | ChaosInjector (default OFF) |
| `master/` | MasterGateRunner (phases 0–45 summary) |
| `common/` | Shared helpers + CorrelationIds + ownership matrix |
| `settings/` | Settings Control Plane + BehaviorProfile |

Backend shims under `Data/backend/reasoning.py` and `Data/backend/llm.py` re-export for compatibility.

Create a new module only when real functionality requires persistent/domain ownership.
