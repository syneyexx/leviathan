# HADES architectural decisions

Update this document only when a durable project-level decision changes.

## D001 — Offline first
Core HADES must boot and remain useful without internet. Online features are optional enrichments controlled by policy.

## D002 — LM Studio remains dynamic
Do not hardcode a model ID. Endpoint, API key and model inference settings are user-configurable. HADES selects from models exposed by LM Studio.

## D003 — Preserve the established GUI
Runtime/architecture work must not redesign the interface unless explicitly requested. Functional regressions caused by “cleanup” are unacceptable.

**HADES-10 override:** information architecture may become Chat-primary (navigation
hierarchy, defaults, Chat capabilities). Keep the established visual identity/tokens.
Do not invent a new shell. See D018.

## D004 — Three knowledge roles
Memory, Knowledge Library and Evidence Vault have different semantics. Do not collapse them into one undifferentiated context store.

## D005 — Plugins remain adapters
Third-party projects stay at process/CLI/REST/MCP boundaries. HADES owns lifecycle and policy; upstream projects remain separable.

## D006 — One execution truth for plugins
Manual Plugin-page runs and autonomous AI runs use the same PluginManager/tool-call persistence/lifecycle rules. UI-only mock execution is not acceptable.

## D007 — Global policy wins
`block` always blocks. Manual actions can provide explicit one-time approval where policy is `ask`; autonomous execution cannot silently manufacture user approval.

## D008 — No fake success
Task completion requires verification. Service start requires health proof. Research expert status requires evidence. Errors remain visible/persistent.

## D009 — Deterministic safety boundaries
Permissions, subprocess invocation, filesystem writes, migrations, trading state and exact-once lifecycle changes belong in deterministic code, not model prompts.

## D010 — Windows is first-class
All release/start/dependency flows must work from Windows CMD/PowerShell. Do not rely on Unix-only inline environment syntax or shell behavior.

## D011 — PAPER trading only in core
The built-in trading path remains simulation-only. Any future real-money integration requires a separate explicit architecture/security review.

## D012 — Incremental refactor over rewrite
Characterize existing behavior with tests, extract interfaces, migrate subsystem by subsystem, then remove old code. Never replace the entire framework in one unverified generation.

## D014 — No hardcoded moral content filters
HADES Core must not hardcode moral/content refusal lists or “as an AI I cannot…” gates.
User-facing behavioral limits belong in the configurable **system prompt** and/or the local model.
Deterministic **security** boundaries remain mandatory: network/file/shell policies, plugin permissions,
approvals, trading PAPER-only, filesystem jails, and “no fake success” verification.

## D015 — User-authorized document harvest
When the user explicitly authorizes downloads (chat harvest intent, `/harvest`, Research harvest,
or `authorized_downloads=true` on the API), HADES may fetch linked documents into the Knowledge Library
with provenance. Partial failures must be reported; completion requires real ingested sources.

## D016 — Gen1 baseline; Gen2 backlog is not active authority
The world-class “50 capabilities” wave is complete and forms the product baseline
(`docs/archive/HADES_WORLD_CLASS_VISION.md`). Gen2 planning documents are archived under
`docs/archive/planning/` as historical evidence only.

**HADES-10 override:** do not build additional Gen2 systems from the old roadmap.
Existing useful Gen2/runtime capabilities may be connected into Chat; otherwise leave
them under Advanced. Active direction is Chat-primary product completion, not roadmap
campaigns.

## D017 — One lifecycle owner per surface (A12)
Work Runtime owns Work task status. Mission Control mirrors Work and may only
downgrade false completion when acceptance evidence fails. Workflows own
workflow-run status only. Coding jobs keep `coding_job_control.CONTROL_OWNER`.
See `backend/run_lifecycle.py` and `docs/architecture/lifecycle-ownership.md`.
SQLite remains the persistence store; no parallel orchestration engine.

## D018 — Chat is the primary intelligence surface
Chat (`#/chat`) is the primary HADES intelligence surface for questions, work,
coding, research, tools, approvals, files, knowledge, memory, artifacts and
verification. Other major pages remain capability/operator consoles under Advanced
(or Daily for Research/Files/Memory/Models/Settings). Mission Control must not
become Home.

## D019 — One authoritative main interface
The product GUI is `HadesApp` with Classic pages under `components/hades/pages/`.
Obsidian is a visual skin of those same pages (`ui_style`), not a second product.
V3, V4 and BETA interface templates are removed and unsupported.
New Capability Intelligence UI is implemented only on this main interface.

