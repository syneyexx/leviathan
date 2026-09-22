# Data/modules

Long-lived / stateful domain systems for LEVIATHAN.

## Current modules

| Module | Ownership |
|---|---|
| `reasoning/` | `ReasoningEngine`, `ReasoningPlan` |
| `context/` | `ContextBuilder`, `ContextPack` |
| `model_runtime/` | `OpenAICompatibleLLM`, `LLMUnavailable` |
| `run/` | `RunStore`, Run lifecycle + events |
| `artifacts/` | `ArtifactStore`, content hash provenance |
| `knowledge/` | Knowledge V2 documents/chunks/hybrid retrieval |
| `function_runtime/` | FunctionRegistry + lazy ON_DEMAND runtime |
| `execution/` | CapabilityCatalog + ExecutionGateway |
| `approvals/` | PolicyEngine + ApprovalStore + ApprovalService |
| `jobs/` | JobStore + JobRuntime + ResourceManager |
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
| `evaluation/` | EvaluationHarness (+ neuro ablations) |
| `isolation/` | IsolationGuard |
| `training/` | TrainingRegistry stub + TrainingRecipeRegistry |
| `browser/` | BrowserAutomationStub |
| `media/` | MediaAutomationStub |
| `voice/` | VoiceRuntimeStub |
| `release/` | ReleaseGateRunner |
| `security/` | SecurityAuditor (posture, not pentest) |
| `native/` | NativeRuntimeStub |
| `trading/` | TradingStub |
| `backup/` | BackupService (local SQLite snapshots) |
| `metrics/` | MetricsCollector (in-process) |
| `chaos/` | ChaosInjector (default OFF) |
| `master/` | MasterGateRunner (phases 0–45 summary) |

Backend shims under `Data/backend/reasoning.py` and `Data/backend/llm.py` re-export for compatibility.

Create a new module only when real functionality requires persistent/domain ownership.
