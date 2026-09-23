#!/usr/bin/env bash
# Local parity with .github/workflows/leviathan-ci.yml (LEVIATHAN Data/ only).
# HADES/ and editor/ are NOT_APPLICABLE — never treated as success by omission.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== LEVIATHAN CI (local) =="
echo "policy: exclude HADES/ editor/"

python -m pytest Data/backend/tests -q --tb=line
python -m pytest Data/backend/tests/test_round8_security_isolation.py -q --tb=line
python -m pytest Data/backend/tests/test_round*.py -q --tb=line

if [[ -d Data/frontend ]]; then
  (
    cd Data/frontend
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
    npm run typecheck
    npm run lint
    npm run test
    npm run build
  )
else
  echo "frontend: UNMEASURED (directory missing) — not PASS"
  exit 1
fi

python - <<'PY'
from Data.modules.release import GateMeasurement, default_leviathan_ci_plan
plan = default_leviathan_ci_plan(
    backend_exit=0,
    frontend_typecheck_exit=0,
    frontend_lint_exit=0,
    frontend_test_exit=0,
    frontend_build_exit=0,
    security_exit=0,
    migration_exit=0,
    integrity_exit=0,
    fixture_separation_exit=0,
    round_exit=0,
)
payload = plan.public_dict()
assert payload["truth"]["skipped_unavailable_is_not_success"]
assert payload["truth"]["not_applicable_is_not_pass"]
hades = next(s for s in plan.suites if s.suite_id == "hades")
editor = next(s for s in plan.suites if s.suite_id == "editor")
assert hades.measurement == GateMeasurement.NOT_APPLICABLE
assert editor.measurement == GateMeasurement.NOT_APPLICABLE
print("ci-plan summary:", payload["summary"])
PY

echo "== LEVIATHAN CI local OK =="
