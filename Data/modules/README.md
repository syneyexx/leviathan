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

Backend shims under `Data/backend/reasoning.py` and `Data/backend/llm.py` re-export for compatibility.

Create a new module only when real functionality requires persistent/domain ownership.
