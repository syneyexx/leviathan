# HADES-10 Flight Certificate

- **commit:** `d30220adcc8841718141d350f44b8279a379178f`
- **branch:** `cursor/hades-10-chat-primary-60e4`
- **origin/main:** `81c256d821180c0c0c7c2aff6c41a3b60d888cbc`
- **generated_at:** 2026-09-14T18:18:22.719556+00:00
- **overall:** **NOT_FLIGHT_READY**
- **reason:** Critical HADES-10 software gates PASS, but certificate is not bound to exact origin/main (81c256d821180c0c0c7c2aff6c41a3b60d888cbc); host Windows/LM paths remain UNVERIFIED_ON_HOST/UNMEASURED; full verify_hades --quick has known pre-existing BETA/V3/V4/host failures on main tip.

## Software gates

| Gate | Status |
|---|---|
| `frontend_typecheck` | PASS |
| `frontend_lint` | PASS |
| `hades10_focused_backend` | PASS |
| `launcher_lifecycle` | PASS |
| `verify_hades_quick` | NOT_RUN |

## Host / quality

| Check | Status |
|---|---|
| `windows_host` | UNVERIFIED_ON_HOST |
| `tray_lifecycle` | UNVERIFIED_ON_HOST |
| `lm_studio_live` | UNMEASURED |
| `meet_dit_model_live_quality` | UNMEASURED |
| `exact_origin_main_checkout` | FAIL |

## Notes

- UNMEASURED live-model quality does not fail software health.
- UNVERIFIED_ON_HOST Windows tray/LM Studio paths must be re-run on the owner Windows host.
- Exact-main certification after merge: check out `origin/main` and re-run `tools/emit_flight_certificate.py`.
