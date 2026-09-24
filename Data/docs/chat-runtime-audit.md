# Chat runtime audit

## Canonical ownership

| Concern | Owner |
|--------|--------|
| Identity / system prompt / language / generation / retrieval knobs | `BehaviorProfileStore` + `BehaviorSettingsResolver` → immutable `BehaviorSnapshot` per turn |
| Intent + retrieval gate | `Data.modules.reasoning.retrieval_policy` via `ReasoningEngine` |
| Context compilation | `ContextBuilder` (+ `reference.py` for untrusted Brain data) |
| Provider streaming | `OpenAICompatibleLLM` + `StreamNormalizer` |
| Persistence | existing conversation `Database` (one user + one assistant turn per request) |
| Heavy work | `JobRuntime` / `WorkerSupervisor` (not the chat request path) |

## Turn pipeline

```
Settings → BehaviorSnapshot → retrieval policy → ContextBuilder → model adapter
  → StreamNormalizer → SSE (token/snapshot/replace/done) → one final assistant turn
```

## Forensic notes (Round 1)

1. **Dutch → English**: English-only identity/system defaults + no language policy forced English replies.
2. **Identity hardcoding**: `DEFAULT_BEHAVIOR_PROFILE` + ContextBuilder/coding fallbacks duplicated seed text. Now: single `seed.py` + resolver.
3. **Medical leakage on greetings**: `use_knowledge = … or word_count >= 8` made ordinary Dutch social messages retrieval-eligible.
4. **System-authority Brain**: knowledge was concatenated into `role=system`.
5. **`[tier2]` repetition**: `extract_delta_text` treated cumulative `message.content` snapshots as deltas; frontend/backend appended → exponential/repeated text. Classified as **B** (cumulative snapshots appended as deltas), possibly compounded by contaminated history (**D** if prior turns stored).

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Wrong language | Settings → language_mode / latest user message diagnostics in turn events |
| Unexpected Brain hits | `retrieval_gate.reason` on run events / done payload |
| Duplicated stream text | `stream_stats.duplicate_snapshots_suppressed`, frame kinds |
| Workers idle | `run_leviathan_workers.bat`, `LEVIATHAN_WORKERS_*` env |
