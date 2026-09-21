# HADES ASTRA Audit — Phase 4H Host / Runtime Honesty

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-049 — Corrupt persisted execution-lease state is silently treated as empty

- Severity: HIGH / crash-recovery and duplicate-work fencing truth.
- Status: OPEN / CHARACTERIZED.
- Existing durability contract: execution leases persist fencing generations, holders and pause/control state to `execution_leases.json`; mutating writes already fail closed and roll back in-memory changes when `_save()` fails.
- Root cause: `ExecutionLeaseStore._load()` catches both `OSError` and `json.JSONDecodeError` and returns without surfacing failure. A present but unreadable/corrupt durable lease file is therefore indistinguishable from no prior state.
- Startup relevance: `app_lifecycle.startup()` assigns the persistence path and restores/reclaims lease state inside a broad best-effort block. Silent `_load()` failure means startup can continue with empty in-memory fencing/control state even though a durable file existed.
- Risk: after corruption/read failure, stale worker generations or pause/control state can be forgotten and subsequent work can proceed without the crash-recovery evidence HADES intended to preserve.
- Regression characterization: `backend/tests/test_run_lease_load_honesty.py` writes malformed JSON in a temporary directory and requires construction/loading not to silently succeed. It is currently `expectedFailure` and performs no process/network I/O.
- Characterization commit: `a1726817ad9133021f5eda8111097cd8769de3de`.
- Required remediation: distinguish absent persistence from unreadable/corrupt persistence, preserve/diagnose the bad file, and fail closed at the lifecycle boundary rather than silently starting with empty durable fencing state. Do not overwrite the only corrupt evidence before surfacing recovery action.
- Safe-edit constraint: a complete repair spans both `run_leases.py` load semantics and startup policy in `app_lifecycle.py`; no partial behavior change was made.

## F-2026-09-13-050 — Host capability readiness drifts from current HADES runtime minimums

- Severity: MEDIUM / setup and host-readiness honesty.
- Status: IMPLEMENTED / TARGETED REGRESSIONS ADDED / FULL SUITE UNVERIFIED.
- Authoritative setup contract: HADES preparation/runtime requires Python >=3.11 and Node >=22.13; npm/Node are required for the source frontend launch/build path.
- Root cause: `check_host_capabilities()` accepted Python >=3.10, checked Node/npm only for executable presence, and computed overall `status="ready"` from only Python + Git + workspace writability.
- Production fix: `backend/host_capability.py` now uses Python >=3.11, locally probes `node --version` and requires Node >=22.13, and includes Node + npm in the mandatory readiness set alongside Python, Git and workspace writability. Node probing is argv-based with no shell and a bounded local subprocess timeout.
- Regression coverage:
  - original `backend/tests/test_host_capability_runtime_requirements.py` characterization was promoted from `expectedFailure` to permanent assertions;
  - `backend/tests/test_host_capability_runtime_contract.py` adds explicit Node 22.12 rejection, Node 22.13 acceptance and a supported-runtime ready path;
  - the LM Studio HTTP probe is mocked in the new targeted tests, so the regression design does not require live network I/O.
- Implementation commits: `3848fbf8ae25fd3134606892fc5b7752eb6779bb`, `1621c8a55451a7ee422c1988491187aead86b56d`, `295097c86dd9c91acc19351b76330db190027d47`.
- Diff review: production change is isolated to `backend/host_capability.py`; test changes are isolated to the two host-capability regression modules.
- Remaining validation: canonical/full suite, Windows host execution and real installed Node/Python combinations were not run in this environment.

## Additional review

- `backend/host_probes.py` keeps implemented/available/simulated/operational/quality axes separate. The reviewed LM Studio/browser failure paths do not promote failed or unavailable probes to PASS; no additional finding was created from static review.
- `backend/models_routes.py` best-effort tool-capability cache invalidation was reviewed. The cache fingerprint is endpoint/model/tool-API based, while normal model profile values are not part of that capability contract; no user-visible stale-capability defect was established from the swallowed invalidation alone.

## Validation honesty

- No canonical/full suite was run.
- F-049 remains open/characterized; F-050 is implemented with targeted regression sources added but not executed in the full suite here.
- No CI polling, live provider probe or external network test was performed for this checkpoint update.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for this checkpoint.
