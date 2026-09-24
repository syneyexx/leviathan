# Brain / retrieval boundary

## Gate

Retrieval is **off by default** for:

- greeting / how-are-you
- identity / name questions
- exact-output commands
- casual social chat
- formatting-only / settings control

Eligibility uses intent classification (`retrieval_policy.py`), **not** `word_count >= 8`.

When eligible: relevance threshold applies; zero injection if nothing meets threshold. Hash embedding scores are marked uncalibrated.

## Authority

Trusted **system** role may contain only:

- effective behavior / identity
- runtime contract
- operator/project constraints

Retrieved chunks are serialized as:

```xml
<reference_context untrusted="true">…</reference_context>
```

attached to the latest **user** turn (or a dedicated user message), never as system authority.

Role markers (`user:`, `<|assistant|>`, `[tier2]`, …) are escaped as data literals. Source datasets are not destructively rewritten.
