# HADES Gen2 threat model & abuse cases (agents / tools)

**Status:** Living document — implementation-aligned  
**Scope:** Gen2 Mission Control, plugins/tools, Agent Factory, sandbox, committee, finance PAPER walls  
**Non-goal:** Claiming host OS isolation is proven without Windows Job Object operational evidence

---

## Assets

| Asset | Why it matters |
|---|---|
| Local SQLite (Memory/Knowledge/Evidence/Gen2) | User intellectual property; offline corpus |
| Plugin subprocesses | Same OS user as HADES unless Job Object/AppContainer enforced |
| LM Studio local models | Prompt injection → tool misuse |
| PAPER trading ledger | Integrity of simulated capital; must never become live brokerage |
| Approvals / gates | Human control plane for autonomy |
| Flight Recorder events | Auditability; secret leakage risk if unredacted |

---

## Trust boundaries

1. **UI / API** → backend services (local loopback assumed; no cloud auth required)
2. **Model output** → tool/mission IR (untrusted; validate schemas; never authorize)
3. **Plugin code** → host OS (capability envelopes + optional Job Objects)
4. **Remote compute workers** → pairing + HMAC; unpaired remote jobs blocked
5. **Network** → optional; must fail clean when blocked

---

## Abuse cases (must remain mitigated)

| ID | Abuse | Required control |
|---|---|---|
| A01 | Prompt injection instructs plugin to read secrets | Tool-boundary untrusted labeling; envelope deny; secrets never in prompts |
| A02 | Model invents “approved” gate | Gates decided only by deterministic API + human; fingerprint recorded |
| A03 | Skill self-promote without human | Promote requires `human_approved` + benchmark hash bind |
| A04 | Path jail escape via prefix sibling | `relative_to` path kinship checks |
| A05 | Claim Tier-2 isolation on Linux | Host probe honesty; fail-closed unavailable tiers |
| A06 | Fake compute success for unknown ops | Typed job handlers; unknown → failed |
| A07 | Real-money trading creep | PAPER-only walls; proposals require approval; no live order APIs |
| A08 | Replay re-executes side effects silently | `inspection_not_replay`; comparative replay defaults to fixture tools |
| A09 | Committee unanimous echo hides dissent | Divergent roles + claim_marks + minority_positions |
| A10 | Eval labels software scores as model quality | `not_model_quality` / `software:` matrix ids |
| A11 | Unpaired remote job execution | Compute fabric pairing gate |
| A12 | Workflow promote without tests | tested status requires dry/sandbox pass; promote needs human |
| A13 | Workflow sets `invocation_type=install` to skip G11/G8 | `assert_public_invocation_type` + `privileged_policy_skip` required |
| A14 | Chat harvest under network `ask` without approval | `maybe_handle_chat_command` returns APPROVAL_REQUIRED |
| A15 | Empty artifact claimed ready | `verify_ready` requires `non_empty` |
| A16 | Schedule occurrence marked completed when task only started | occurrence status `dispatched` |
| A17 | Policy module missing → fail-open | ImportError fail-closed in invoke/tool_engine |
| A18 | Replay/crash double-write | Effect ledger restart classification (at-least-once; not exactly-once) |

---

## Residual / host-unverified

- Physical Windows Job Object + AppContainer operational proofs: `UNVERIFIED_ON_HOST` until host evidence
- Multi-machine distributed compute: MVP local/LAN only; cluster claims deferred
- Live LM Studio quality: only when `model_invoked` evidence exists
- Coding/build/voice/preview subprocess paths still outside PluginManager kernel

---

## Verification

See `docs/engineering/SECURITY_VERIFICATION.md` and `python -m evals.gen2_release_gate`.
