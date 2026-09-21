# Agent work skills — voortgang

**Taak:** Professionele lokale AI-werkvaardigheden (fasen A→L), start op `ed8883c` (PR #35).  
**Branch:** `cursor/agent-work-skills-quality-0f40` · **PR:** #36  
**Baseline commit:** `ed8883c901554a9bd0f42f993e4eca108917ef4f`

## Antwoord op “is de hele lijst af?”

| Scope | Status |
|---|---|
| Fasen **A→L** (implementatie + acceptatieketens + tests) | **Af** |
| Verplichte gebruikersscenario’s **1–10** | **Af** (executable fixtures in `tests.test_user_scenarios_a_to_l`) |
| Windows host VERIFY | **Gesimuleerd + bat aanwezig** (`host_verify_sim`, mode=`simulated_windows`) — fysieke Windows-machine niet in deze cloud-VM |
| Live LM Studio / OS Job Object / remote compute | **Bewust niet geclaimd** (geen fake success) |

## Fasen A→L

| Fase | Status | Bewijs |
|---|---|---|
| A | **af** | regressies + honest completion/budgets/contracts |
| B | **af** | Mission Control werkplek + typed API |
| C | **af** | goal→explore→repair→diff; async LM; reviewer |
| D | **af** (heuristic) | project_map/impact/retrieval-compare; NL synonym explore |
| E | **af** | RunContext + checkpoints + compaction |
| F | **af** | ≥39 quality scenarios; live layer unmeasured zonder LM |
| G | **af** | evidence checks; complexity roles; skill execute UI |
| H | **af** | leases persist; pause_requested→paused; restart restore |
| I | **af** | ClaimRegister SQLite; circular Knowledge filter |
| J | **af** (gated preview) | plan/start/stop + functionele UI-checks |
| K | **af** (sim + bat) | `VERIFY_HADES_HOST.bat` + `host_verify_sim` + `/host/verify` |
| L | **af** (local) | LocalExecutor submit/status/cancel; distributed blocked |

## Gebruikersscenario’s 1–10

| # | Scenario | Test |
|---|---|---|
| 1 | Settings-locatie uitleggen zonder edits | `test_01_*` |
| 2 | Bug repareren + regressietest | `test_02_*` |
| 3 | API-veld + types + UI | `test_03_*` |
| 4 | Onderzoek met lokale docs + citations | `test_04_*` |
| 5 | Pauze + bijsturen + behouden werk | `test_05_*` |
| 6 | Twee lokale modellen vergelijken | `test_06_*` (gesimuleerde LM) |
| 7 | Skill candidate→benchmark→promote→execute | `test_07_*` |
| 8 | UI-preview verificatierapport | `test_08_*` |
| 9 | Hervatten na herstart | `test_09_*` |
| 10 | Gecontroleerd toepassen + backup/restore | `test_10_*` |

## Verificatie

- `python3 -m unittest tests.test_user_scenarios_a_to_l tests.test_work_skills_completion tests.test_phases_d_to_l tests.test_agent_work_skills_a tests.test_coding_agent_goal tests.test_gen2_reliability tests.test_gen2` → **PASS**
- `npx tsc --noEmit` → **PASS**
- `host_verify_sim` → **passed** (`simulated_windows`)

## Niet geclaimd

Fysieke Windows Job Object/AppContainer, live LM Studio op operator-host, remote compute pairing, LSP-grade intel, live browser screenshots met vision-model.
