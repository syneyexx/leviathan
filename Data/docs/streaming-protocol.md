# Streaming protocol

## Typed frames

Internal `StreamFrame(kind=delta|snapshot|replace|done|error, text, sequence, finish_reason, …)`.

| Upstream | Normalization |
|----------|----------------|
| `choice.delta.content` | `delta` |
| `choice.message.content` | cumulative **snapshot** → emit suffix deltas; identical → suppress; diverge → `replace` |

## SSE events

| Event | Payload highlights |
|-------|--------------------|
| `meta` | conversation/run ids, reasoning summary |
| `token` | append-safe delta (`kind=delta`, `sequence`, `request_id`, `turn_id`) |
| `snapshot` / `replace` | full text replace |
| `done` | final ChatResponse + `finish_reason`, `termination_source`, `stream_stats`, `behavior`, `retrieval_gate` |
| `cancelled` / `error` | termination |

Frontend: ignore duplicate `event:sequence` keys; finalize `done` once; deltas append; snapshots replace; AbortController supported.

## Termination

Completion results expose `text`, `model`, `provider`, `finish_reason`, `termination_source`, `usage`, request/turn ids. Stop sequences only when configured for the active provider/model — never universal `User:`/`Assistant:` stops.
