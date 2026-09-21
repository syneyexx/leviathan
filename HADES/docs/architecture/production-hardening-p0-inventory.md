# Production hardening P0 inventory

Truth-based inventory of production gaps closed against live HADES `main`
(not a new roadmap). Status is evidence-backed; host-only paths stay
`UNVERIFIED_ON_HOST` and are not claimed PASS.

| # | P0 gap | Closure | Evidence |
|---|--------|---------|----------|
| 1 | Inventory of production gaps | Documented | This file + `docs/CURRENT_STATUS.md` + `docs/architecture/configuration-limit-audit.md` |
| 2 | Agents layer stubs (`web_scout`, `evidence_auditor`, `tool_orchestrator`, `trading_specialist`, `voice_specialist`) | Closed | `backend/reasoning/specialists.py` (`planned_only` default False), `backend/agent_runtimes.py`, empty `PLANNED_AGENT_IDS`, platform migration 10, `backend/tests/test_implemented_agents.py` |
| 3 | Mission Control NVIDIA/demo primary UX | Closed | `components/hades/pages/mission-control-page.tsx` — empty goal; Knowledge fuse; sample fixtures only behind `showSampleFixtures` |
| 4 | Gen2 monolith in `services.py` | Closed | Packages under `backend/gen2/` (`sandbox`, `flight_recorder`, `finance_fusion`, `committee`, `context_compiler`, `eval_lab`, `compute_fabric`, `temporal_graph`, `agent_factory`, `mission_control`, `dashboard`, …); thin `Gen2Services` facade; per-package characterization tests |
| 5 | Control Plane unclassified behavioral hardcodes | Closed | `backend/control/detect.py` (Python + TS/TSX), `backend/control/limit_classifications.py`, `test_hardcoded_limit_detector` fails on unclassified findings |
| 6 | FE↔BE API contract drift (settings + Gen2) | Closed | `AppSettings`/`SettingsInput` nullability; `test_settings_contract_drift`, `test_api_contract_drift`, `test_gen2_api_contract_drift`; committee `mode` under `consensus.mode` |
| 7 | Gen2 honesty (fake ready / distributed / billing / quality) | Closed | Sandbox fail-closed unavailable tiers; flight recorder blocks side effects by default; context `not_provider_billing`; compute `remote_dispatch_not_implemented`; live eval `not_model_quality` / infrastructure smoke |
| 8 | Coding Agent false-success / LSP / browser honesty | Closed | `language_servers.py`, `preview_runtime.py`, `coding_job_control.py`, `test_coding_agent_reliability_p0.py` (E01–E08 honesty suite; full agent greens not claimed) |
| 9 | Release gates fragmented / non-canonical | Closed | `verify_hades.py` (+ `--quick` / `--python-only`), `VERIFY_HADES.bat`, `docs/TESTING_RELEASE_GATES.md` |
| 10 | Repo hygiene (LFS plugin dist pointers, quick-gate CSS/voice contracts) | Closed | Plugin overlay rebuild when dist is LFS pointer; `--quick` tolerates missing `dist`; voice contract uses live session refs |

## Explicitly out of P0 claim (honest residuals)

- Physical Windows Job Objects / AppContainer operational tests → `UNVERIFIED_ON_HOST`
- Live LM Studio committee quality / model-quality eval → requires host LM
- Live Puppeteer / VoiceStudio audio → `UNVERIFIED_ON_HOST`
- Distributed compute peering → not implemented (`remote_dispatch_not_implemented`)
- Gen1 fifty-capability vision → archived baseline, not open backlog

## Verification pointer

Canonical gate: `python verify_hades.py` (or `--quick`). Record results in `docs/CURRENT_STATUS.md`.
