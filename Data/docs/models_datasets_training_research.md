# Models, Datasets, Training & Research

Operational guide for the LEVIATHAN Models / Datasets / Training / Research subsystem.

## Models

Configure an OpenAI-compatible endpoint (LM Studio default):

```bash
LEVIATHAN_LLM_BASE_URL=http://127.0.0.1:1234/v1
```

In the UI (`/models`):

1. Providers → create/edit OpenAI-compatible or LM Studio preset
2. Test connection (real health probe + `/v1/models` discovery)
3. Activate a model / assign roles
4. Test tab → real gateway inference (`POST /api/models/{id}/test`)

Secrets: API keys are stored server-side only. GET responses expose `apiKeyConfigured: true/false`, never the key.

## Datasets

Supported local formats: `.jsonl`, `.ndjson`, `.json`, `.csv`, `.tsv`, `.txt`, `.md`.

Import paths:

- Browser upload (`POST /api/datasets/upload`, max 512 MiB per request)
- Local filesystem path under allowed roots (`POST /api/datasets/import/local`)
- Hugging Face file (`POST /api/datasets/import/huggingface`)

HF token: set `LEVIATHAN_HF_TOKEN` or pass once in the import request. Tokens are never written into manifests, job configs returned to the UI, or logs.

Raw imports are immutable. Transforms create new versions with lineage. Materialized shards live under the corpus root:

```text
{CORPUS}/datasets/raw|materialized|processed|exports|manifests
```

`LEVIATHAN_CORPUS_ROOT` overrides the default corpus location (falls back to `Data/backend/data/corpora` when the bulk data root is not writable).

## Training

Optional packages (not required for the API to start):

- torch, transformers, datasets, accelerate, peft, bitsandbytes, safetensors, tokenizers, pyarrow

UI shows **Training environment ready** or lists exact missing packages (`GET /api/training/capabilities`).

Hardware probe (`GET /api/training/hardware`) reports real CPU/RAM/GPU when measurable; never invents VRAM.

Start path:

1. Preflight (`POST /api/training/preflight`) — PASS / WARNING / BLOCKED
2. Plan (`POST /api/training/plan`) — hardware-aware strategy recommendations
3. Create + start job (`POST /api/training/jobs`)
4. Monitor metrics/logs/checkpoints; cancel or resume interrupted jobs

CI / no-GPU path: `method=fixture` or `LEVIATHAN_TRAINING_FIXTURE=1` runs a deterministic worker that emits real steps/metrics/checkpoints without torch.

Completed adapters register into the Model registry as `trained:{artifactId}` with honest `inferenceReady` metadata.

## Research

Local research works offline against Knowledge + dataset indexes.

Web research requires:

```bash
LEVIATHAN_NETWORK_ALLOW_OUTBOUND=true
LEVIATHAN_WEB_SEARCH_ENDPOINT=...   # real search HTTP endpoint
LEVIATHAN_WEB_SEARCH_API_KEY=...    # never returned via GET
```

Without a provider: **Web research unavailable — provider not configured.** Local sources still run.

Evidence ledger citations resolve `citation → evidence → source → snapshot`. Contradictions are preserved, never silently resolved.

Exports: Markdown, HTML, JSON evidence bundle.

## Troubleshooting

| Symptom | Meaning |
|---|---|
| Provider offline | Health probe failed; check endpoint / LM Studio |
| HF 429 | Import job checkpoints and resumes; wait / Retry-After honored |
| CUDA unavailable | Preflight blocks GPU methods or offers CPU/fixture |
| OOM | Job fails with CUDA OOM; checkpoint retained; clone with safer settings |
| Job interrupted | Worker PID gone after restart; use Resume |
| Web unavailable | Outbound disabled or search endpoint/key missing |

## Security notes

- Path traversal rejected on imports
- SSRF blocked for research fetches (loopback/private/link-local/metadata)
- Subprocess training uses argv arrays (`shell=False`)
- Secrets redacted from logs/events/API errors
