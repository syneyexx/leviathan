# HADES Neural Memory — Phase 0 baseline

Recorded against `origin/main` at start of neural work.

| Field | Value |
|---|---|
| Baseline SHA | `92cdfb5a21046bfc0659915c4f2333f6221d830f` |
| Branch tip | FINALBETA GUI merge (`#143`) |
| Working tree at audit | clean |

## Current production architecture (must preserve)

```text
React / TypeScript UI
  → FastAPI
  → Python intelligence / reasoning / policy
  → LM Studio / SQLite / PluginManager / Gen2
  → NativeRuntimeFacade
  → C++20 bounded native runtime
```

Python owns intelligence, orchestration, policy, application state, training
coordination, and reasoning. C++ owns deterministic native execution.

Authoritative docs: `docs/ARCHITECTURE.md`, `docs/REASONING_ARCHITECTURE.md`,
`docs/HADES_CODEBASE_MAP.md`.

## Training architecture

| Component | Path | Role |
|---|---|---|
| Training workspace | `backend/training_service.py` | Dataset/job registry under `{db_parent}/training/` |
| LoRA worker | `backend/training_worker.py` | Isolated subprocess; imports torch/transformers/peft |
| Optional deps | `backend/requirements-training.txt` | **Not** in normal `requirements.txt` |
| Capabilities probe | `TrainingWorkspace.capabilities()` | Truthful package availability; no import of heavy ML into FastAPI |

Normal HADES startup must not import PyTorch. Training remains opt-in and process-isolated.

## Dataset Brain flow

```text
Dataset registration (TrainingWorkspace)
  → DatasetBrainManager start job
  → dataset_brain_worker (subprocess)
  → local snapshot (data.jsonl) + manifest.json
  → Knowledge Library index (redacted text; hidden CoT columns excluded)
```

Key files: `backend/dataset_brain.py`, `backend/dataset_brain_worker.py`.

Hidden-reasoning fields excluded (same set in training worker):

`reasoning`, `chain_of_thought`, `chain-of-thought`, `cot`, `thought`,
`thoughts`, `scratchpad`, `internal_reasoning`, `analysis`.

Atomic writes use temp + `fsync` + `os.replace`.

## Model gateway flow

`backend/reasoning/model_gateway.py` — shared capacity, retries, metrics, typed
errors for LM Studio OpenAI-compatible calls. No Transformer hidden-state access.
Neural runtime must be added **alongside**, not by faking neural integration via
prompt injection.

## Existing memory / knowledge

| Concept | Location | Role |
|---|---|---|
| Durable Memory | `backend/database.py` | Explicit facts/preferences |
| Knowledge Library | `platform_db` / KnowledgeService | Chunked exact retrieval |
| One Brain | `backend/hades_brain/` | Coordination façade over existing subsystems |
| Dataset Brain | above | Offline dataset materialization — **not** neural memory |
| Embeddings | `backend/embeddings.py` | Optional LM Studio vectors for retrieval |

**Neural Memory** is a new subsystem (`backend/neural/`). Do not rename existing brains.

## Configuration conventions

- Runtime settings: `backend/config.py` (`HADES_` env prefix, pydantic-settings).
- Training root: `{database_path.parent}/training/`.
- Neural checkpoints (Phase 1+): tests use temp dirs; product root reserved as
  `{database_path.parent}/neural/` (not wired into FastAPI yet).

## Test commands

| Gate | Command |
|---|---|
| Backend unit tests | `backend/.venv/bin/python -m unittest discover -s backend/tests -v` |
| Frontend | `npm run typecheck && npm test` |
| Full release | `python verify_hades.py` / `VERIFY_HADES.bat` |
| Focused neural | `backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_neural*.py' -v` |

## Baseline health (this environment)

See `docs/neural/STATUS.md` for the run log. Results must be truthful
(`PASS` / `FAIL` / `SKIPPED` / `NOT RUN`).
