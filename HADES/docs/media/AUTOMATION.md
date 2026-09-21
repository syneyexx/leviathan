# Media Automation

Automation is a durable scheduler (`media/scheduling/loop.py`), not `while True`.

- Lease key `media_main` prevents duplicate owners
- Channel budgets: `max_projects_per_day`, publish caps, retries
- Autonomy levels: `OFF` / `RESEARCH` / `PRODUCE` / `QUEUE` / `AUTONOMOUS`
- TikTok (or any platform) consent blocks only that platform job (`WAITING_PLATFORM_CONSENT`)
- Crash recovery: stage checkpoints + publish idempotency keys + reconcile

Manual tick: `POST /api/media/scheduler/tick`.
