"""HADES Development Partner suite (dev_partner_v1).

Twenty representative software-engineering tasks for proving HADES as a
local coding partner. Reuses generalization fixture factories where they
already encode honest red bugs; adds feature / regression-report / review
fixtures. Does not invent a second eval framework — graded via
``dev_partner_judges`` + existing production coding route.

Dataset version: ``dev_partner_v1``
Split freeze (before optimization):
  - development: DP01–DP12 (iteration / failure-loop)
  - holdout:     DP13–DP20 (comparison / release evidence)

Distribution (motivated): 8 bugfix + 4 feature + 4 regression + 4 review.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Callable

from evals.generalization_dataset import (
    fix_api_status_contract,
    fix_config_env_override,
    fix_error_type,
    fix_py_exception_swallow,
    fix_py_mutable_default,
    fix_py_off_by_one,
    fix_py_sort_key,
    fix_py_whitespace_strip,
)


DEV_PARTNER_DATASET_VERSION = "dev_partner_v1"
DEV_PARTNER_DATASET_SEED_DEFAULT = 42
DEV_PARTNER_SPLIT_FREEZE = {
    "development": [
        "DP01",
        "DP02",
        "DP03",
        "DP04",
        "DP05",
        "DP06",
        "DP07",
        "DP08",
        "DP09",
        "DP10",
        "DP11",
        "DP12",
    ],
    "holdout": ["DP13", "DP14", "DP15", "DP16", "DP17", "DP18", "DP19", "DP20"],
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Feature fixtures — concrete observable new behavior (start failing)
# ---------------------------------------------------------------------------


def fix_feature_retry_header(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_feat_retry_{variant}_"))
    _write(
        root / "client.py",
        "def build_headers(token):\n"
        "    # Missing: Retry-After support header required by new contract\n"
        "    return {'Authorization': f'Bearer {token}'}\n",
    )
    _write(
        root / "test_client.py",
        "import unittest\nfrom client import build_headers\n"
        "class T(unittest.TestCase):\n"
        "    def test_retry_after_present(self):\n"
        "        h = build_headers('abc')\n"
        "        self.assertEqual(h.get('X-Retry-Policy'), 'honor-retry-after')\n"
        "        self.assertIn('Authorization', h)\n",
    )
    return root


def fix_feature_health_endpoint(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_feat_health_{variant}_"))
    _write(
        root / "api.py",
        "def routes():\n"
        "    # Missing /healthz route for ops readiness\n"
        "    return {'/': 'ok'}\n",
    )
    _write(
        root / "test_api.py",
        "import unittest\nfrom api import routes\n"
        "class T(unittest.TestCase):\n"
        "    def test_healthz(self):\n"
        "        self.assertEqual(routes().get('/healthz'), {'status': 'ok'})\n",
    )
    return root


def fix_feature_cli_flag(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_feat_cli_{variant}_"))
    _write(
        root / "cli.py",
        "def parse(argv):\n"
        "    # Missing --json output mode\n"
        "    return {'format': 'text', 'args': list(argv)}\n",
    )
    _write(
        root / "test_cli.py",
        "import unittest\nfrom cli import parse\n"
        "class T(unittest.TestCase):\n"
        "    def test_json_flag(self):\n"
        "        out = parse(['--json', 'run'])\n"
        "        self.assertEqual(out.get('format'), 'json')\n",
    )
    return root


def fix_feature_cache_ttl(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_feat_ttl_{variant}_"))
    _write(
        root / "cache.py",
        "class Cache:\n"
        "    def __init__(self):\n"
        "        self._data = {}\n"
        "    def set(self, key, value, ttl=None):\n"
        "        # Bug/incomplete: ignores ttl metadata\n"
        "        self._data[key] = value\n"
        "    def meta(self, key):\n"
        "        return None\n",
    )
    _write(
        root / "test_cache.py",
        "import unittest\nfrom cache import Cache\n"
        "class T(unittest.TestCase):\n"
        "    def test_ttl_recorded(self):\n"
        "        c = Cache()\n"
        "        c.set('a', 1, ttl=30)\n"
        "        self.assertEqual(c.meta('a'), {'ttl': 30})\n",
    )
    return root


# ---------------------------------------------------------------------------
# Regression investigation fixtures — report root cause; no patch required
# ---------------------------------------------------------------------------


def fix_regression_null_guard(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_reg_null_{variant}_"))
    _write(
        root / "HISTORY.md",
        "v1.2 worked. After commit C3, label(None) started raising AttributeError.\n",
    )
    _write(
        root / "label.py",
        "def label(user):\n"
        "    # Regression: removed None guard present in v1.2\n"
        "    return user['name'].upper()\n",
    )
    _write(
        root / "BRIEF.md",
        "Investigate why label(None) fails after the recent change. "
        "Write artifacts/regression_report.json with keys: "
        "root_cause, evidence_files (list), suspected_commit_note, "
        "recommended_fix (short). Do not invent unrelated issues.\n",
    )
    (root / "artifacts").mkdir(exist_ok=True)
    return root


def fix_regression_config_default(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_reg_cfg_{variant}_"))
    _write(
        root / "HISTORY.md",
        "Before: mode defaulted to 'safe'. After settings refactor, default became 'fast'.\n",
    )
    _write(
        root / "settings.py",
        "DEFAULTS = {'mode': 'fast'}  # regression vs prior safe default\n"
        "def get_mode(cfg=None):\n"
        "    cfg = cfg or {}\n"
        "    return cfg.get('mode', DEFAULTS['mode'])\n",
    )
    _write(
        root / "BRIEF.md",
        "Find why mode is no longer safe by default. Write "
        "artifacts/regression_report.json with root_cause, evidence_files, "
        "suspected_commit_note, recommended_fix.\n",
    )
    (root / "artifacts").mkdir(exist_ok=True)
    return root


def fix_regression_import_break(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_reg_imp_{variant}_"))
    _write(root / "payments" / "legacy.py", "def charge(x):\n    return x\n")
    _write(root / "payments" / "modern.py", "def charge(x):\n    return x * 2\n")
    _write(
        root / "checkout.py",
        "from payments.legacy import charge  # regression: should use modern\n"
        "def total(n):\n"
        "    return charge(n)\n",
    )
    _write(
        root / "HISTORY.md",
        "Checkout previously used payments.modern.charge; a merge restored legacy.\n",
    )
    _write(
        root / "BRIEF.md",
        "Explain the checkout charge regression. Write artifacts/regression_report.json.\n",
    )
    (root / "artifacts").mkdir(exist_ok=True)
    return root


def fix_regression_timeout(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_reg_to_{variant}_"))
    _write(
        root / "http_client.py",
        "TIMEOUT = 1  # regression: was 30; now requests abort early\n"
        "def call():\n"
        "    return {'timeout': TIMEOUT}\n",
    )
    _write(
        root / "HISTORY.md",
        "Timeouts spiked after TIMEOUT was changed from 30 to 1 second.\n",
    )
    _write(
        root / "BRIEF.md",
        "Diagnose the timeout regression. Write artifacts/regression_report.json.\n",
    )
    (root / "artifacts").mkdir(exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Code review fixtures — grounded findings; invented issues must not score
# ---------------------------------------------------------------------------


def fix_review_sql_concat(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_rev_sql_{variant}_"))
    _write(
        root / "PATCH.diff",
        "--- a/query.py\n+++ b/query.py\n"
        "@@\n-def find(name):\n-    return db.execute('SELECT * FROM users WHERE name=?', (name,))\n"
        "+def find(name):\n+    return db.execute('SELECT * FROM users WHERE name=' + name)\n",
    )
    _write(
        root / "query.py",
        "def find(name):\n    return db.execute('SELECT * FROM users WHERE name=' + name)\n",
    )
    _write(
        root / "BRIEF.md",
        "Review PATCH.diff. Write artifacts/review_report.json with "
        "findings: list of {severity, evidence, severity} grounded in the diff. "
        "Do not invent unrelated style nits. Set fabricated_issues=false.\n",
    )
    (root / "artifacts").mkdir(exist_ok=True)
    return root


def fix_review_path_traversal(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_rev_path_{variant}_"))
    _write(
        root / "PATCH.diff",
        "--- a/files.py\n+++ b/files.py\n"
        "@@\n-def read_user_file(name):\n-    return open('data/' + name).read()\n"
        "+def read_user_file(name):\n+    return open(name).read()  # allows absolute / ../ paths\n",
    )
    _write(
        root / "files.py",
        "def read_user_file(name):\n    return open(name).read()\n",
    )
    _write(
        root / "BRIEF.md",
        "Review the patch for security issues. Write artifacts/review_report.json "
        "with grounded findings only.\n",
    )
    (root / "artifacts").mkdir(exist_ok=True)
    return root


def fix_review_secret_log(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_rev_sec_{variant}_"))
    _write(
        root / "PATCH.diff",
        "--- a/auth.py\n+++ b/auth.py\n"
        "@@\n def login(user, password):\n+    print('login', user, password)\n     return check(user, password)\n",
    )
    _write(
        root / "auth.py",
        "def login(user, password):\n    print('login', user, password)\n    return check(user, password)\n",
    )
    _write(
        root / "BRIEF.md",
        "Review PATCH.diff. Report grounded findings in artifacts/review_report.json.\n",
    )
    (root / "artifacts").mkdir(exist_ok=True)
    return root


def fix_review_race_flag(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"dp_rev_race_{variant}_"))
    _write(
        root / "PATCH.diff",
        "--- a/flag.py\n+++ b/flag.py\n"
        "@@\n class Flag:\n     def set(self):\n-        with self._lock:\n-            self.on = True\n+        self.on = True\n",
    )
    _write(
        root / "flag.py",
        "class Flag:\n    def __init__(self):\n        self.on = False\n    def set(self):\n        self.on = True\n",
    )
    _write(
        root / "BRIEF.md",
        "Review the concurrency change. Write artifacts/review_report.json with "
        "grounded findings about the lock removal.\n",
    )
    (root / "artifacts").mkdir(exist_ok=True)
    return root


def _task(
    *,
    short_id: str,
    task_type: str,
    title: str,
    description: str,
    fixture: Callable[..., Path],
    goal: str,
    split: str,
    judge: str,
    test_args: list[str] | None = None,
    allowed_scope: list[str],
    required_outputs: list[str],
    resource_budget: dict[str, Any] | None = None,
    external_deps: list[str] | None = None,
    limitations: str = "",
    context_available: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{short_id}_{task_type}",
        "short_id": short_id,
        "dataset_version": DEV_PARTNER_DATASET_VERSION,
        "task_type": task_type,
        "title": title,
        "description": description,
        "starting_version": f"{DEV_PARTNER_DATASET_VERSION}:{short_id}:fixture",
        "allowed_scope": allowed_scope,
        "context_available": context_available
        or ["fixture_sources", "visible_project_tests", "BRIEF.md_if_present"],
        "required_outputs": required_outputs,
        "acceptance_checks": {"judge": judge, "independent": True},
        "regression_checks": ["baseline_must_fail_or_report_required"],
        "resource_budget": resource_budget
        or {"max_attempts": 3, "max_model_calls": 24, "timeout_seconds": 300},
        "external_dependencies": external_deps or [],
        "assessment_limitations": limitations
        or "Behavior/contracts judged; not patch-identity. No live Windows claim.",
        "fixture": fixture,
        "goal": goal,
        "test_args": test_args or [],
        "judge": judge,
        "split": split,
        "quality_proof": split == "holdout",
    }


DEV_PARTNER_TASKS: list[dict[str, Any]] = [
    # ---- 8 bugfixes (5 development / 3 holdout) ----
    _task(
        short_id="DP01",
        task_type="bugfix",
        title="Descending sort by score",
        description="by_score returns ascending order; users see worst scores first.",
        fixture=fix_py_sort_key,
        goal="Fix by_score so highest scores come first",
        split="development",
        judge="execution_tests",
        test_args=["test_ranking.py"],
        allowed_scope=["ranking.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP02",
        task_type="bugfix",
        title="Invalid int must raise ValueError",
        description="parse_int swallows bad input and returns 0.",
        fixture=fix_py_exception_swallow,
        goal="parse_int should raise ValueError on invalid input",
        split="development",
        judge="execution_tests",
        test_args=["test_safe_int.py"],
        allowed_scope=["safe_int.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP03",
        task_type="bugfix",
        title="Window last_n off-by-one",
        description="last_n drops an element from the window.",
        fixture=fix_py_off_by_one,
        goal="Fix last_n to return the last n items",
        split="development",
        judge="execution_tests",
        test_args=["test_window.py"],
        allowed_scope=["window.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP04",
        task_type="bugfix",
        title="Mutable default argument",
        description="push shares one list across callers.",
        fixture=fix_py_mutable_default,
        goal="Fix push so each call gets an isolated bucket",
        split="development",
        judge="execution_tests",
        test_args=["test_bag.py"],
        allowed_scope=["bag.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP05",
        task_type="bugfix",
        title="Create returns HTTP 201",
        description="create_item returns 200 instead of 201.",
        fixture=fix_api_status_contract,
        goal="create_item must return status 201",
        split="development",
        judge="execution_tests",
        test_args=["test_handlers.py"],
        allowed_scope=["handlers.py", "api.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP13",
        task_type="bugfix",
        title="Env override for region",
        description="HADES_REGION is ignored when loading settings.",
        fixture=fix_config_env_override,
        goal="Honor HADES_REGION over defaults.json",
        split="holdout",
        judge="execution_tests",
        test_args=["test_settings_loader.py"],
        allowed_scope=["settings_loader.py", "loader.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP14",
        task_type="bugfix",
        title="Require ValueError not RuntimeError",
        description="require_positive raises the wrong exception type.",
        fixture=fix_error_type,
        goal="require_positive must raise ValueError",
        split="holdout",
        judge="execution_tests",
        test_args=["test_validate.py"],
        allowed_scope=["validate.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP15",
        task_type="bugfix",
        title="Strip both sides of label",
        description="clean_label only strips one side.",
        fixture=fix_py_whitespace_strip,
        goal="clean_label must strip leading and trailing whitespace",
        split="holdout",
        judge="execution_tests",
        test_args=["test_normalize.py"],
        allowed_scope=["normalize.py"],
        required_outputs=["diff", "tests_green"],
    ),
    # ---- 4 features (2 development / 2 holdout) ----
    _task(
        short_id="DP06",
        task_type="feature",
        title="Add Retry-After policy header",
        description="HTTP client must advertise honor-retry-after policy.",
        fixture=fix_feature_retry_header,
        goal="Add X-Retry-Policy: honor-retry-after to build_headers",
        split="development",
        judge="execution_tests",
        test_args=["test_client.py"],
        allowed_scope=["client.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP07",
        task_type="feature",
        title="Add /healthz route",
        description="Ops needs a readiness endpoint returning {status: ok}.",
        fixture=fix_feature_health_endpoint,
        goal="Add /healthz to routes() returning {'status': 'ok'}",
        split="development",
        judge="execution_tests",
        test_args=["test_api.py"],
        allowed_scope=["api.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP16",
        task_type="feature",
        title="CLI --json output mode",
        description="CLI must support --json format selection.",
        fixture=fix_feature_cli_flag,
        goal="parse(['--json', ...]) must set format to json",
        split="holdout",
        judge="execution_tests",
        test_args=["test_cli.py"],
        allowed_scope=["cli.py"],
        required_outputs=["diff", "tests_green"],
    ),
    _task(
        short_id="DP17",
        task_type="feature",
        title="Cache TTL metadata",
        description="Cache.set must record ttl in meta(key).",
        fixture=fix_feature_cache_ttl,
        goal="Record ttl via Cache.meta after set(..., ttl=)",
        split="holdout",
        judge="execution_tests",
        test_args=["test_cache.py"],
        allowed_scope=["cache.py"],
        required_outputs=["diff", "tests_green"],
    ),
    # ---- 4 regression investigations (2 development / 2 holdout) ----
    _task(
        short_id="DP08",
        task_type="regression",
        title="Null guard regression in label()",
        description="After a recent change, label(None) raises; explain why.",
        fixture=fix_regression_null_guard,
        goal="Write artifacts/regression_report.json diagnosing the null-guard regression",
        split="development",
        judge="regression_report",
        allowed_scope=["label.py", "HISTORY.md", "artifacts/regression_report.json"],
        required_outputs=["regression_report"],
        limitations="Report graded on grounded root cause; code patch optional.",
    ),
    _task(
        short_id="DP09",
        task_type="regression",
        title="Safe mode default regression",
        description="Default mode flipped from safe to fast; diagnose.",
        fixture=fix_regression_config_default,
        goal="Write artifacts/regression_report.json for the safe-default regression",
        split="development",
        judge="regression_report",
        allowed_scope=["settings.py", "HISTORY.md", "artifacts/regression_report.json"],
        required_outputs=["regression_report"],
    ),
    _task(
        short_id="DP18",
        task_type="regression",
        title="Checkout import regression",
        description="checkout uses legacy charge after merge; diagnose.",
        fixture=fix_regression_import_break,
        goal="Write artifacts/regression_report.json explaining the payments import regression",
        split="holdout",
        judge="regression_report",
        allowed_scope=["checkout.py", "payments/", "HISTORY.md", "artifacts/regression_report.json"],
        required_outputs=["regression_report"],
    ),
    _task(
        short_id="DP19",
        task_type="regression",
        title="HTTP timeout regression",
        description="TIMEOUT dropped from 30 to 1; diagnose.",
        fixture=fix_regression_timeout,
        goal="Write artifacts/regression_report.json for the timeout regression",
        split="holdout",
        judge="regression_report",
        allowed_scope=["http_client.py", "HISTORY.md", "artifacts/regression_report.json"],
        required_outputs=["regression_report"],
    ),
    # ---- 4 code reviews (2 development / 2 holdout) ----
    _task(
        short_id="DP10",
        task_type="review",
        title="Review SQL string concat patch",
        description="Review a patch that concatenates SQL with user input.",
        fixture=fix_review_sql_concat,
        goal="Write artifacts/review_report.json with grounded SQL injection finding",
        split="development",
        judge="review_report",
        allowed_scope=["PATCH.diff", "query.py", "artifacts/review_report.json"],
        required_outputs=["review_report"],
        limitations="Ungrounded findings do not score; fabricating issues fails.",
    ),
    _task(
        short_id="DP11",
        task_type="review",
        title="Review path traversal patch",
        description="Review a patch that opens arbitrary paths.",
        fixture=fix_review_path_traversal,
        goal="Write artifacts/review_report.json with grounded path-traversal finding",
        split="development",
        judge="review_report",
        allowed_scope=["PATCH.diff", "files.py", "artifacts/review_report.json"],
        required_outputs=["review_report"],
    ),
    _task(
        short_id="DP12",
        task_type="review",
        title="Review password logging patch",
        description="Review a patch that prints passwords.",
        fixture=fix_review_secret_log,
        goal="Write artifacts/review_report.json with grounded secret-logging finding",
        split="development",
        judge="review_report",
        allowed_scope=["PATCH.diff", "auth.py", "artifacts/review_report.json"],
        required_outputs=["review_report"],
    ),
    _task(
        short_id="DP20",
        task_type="review",
        title="Review lock-removal patch",
        description="Review a concurrency patch that drops a lock.",
        fixture=fix_review_race_flag,
        goal="Write artifacts/review_report.json with grounded race/locking finding",
        split="holdout",
        judge="review_report",
        allowed_scope=["PATCH.diff", "flag.py", "artifacts/review_report.json"],
        required_outputs=["review_report"],
    ),
]


def list_dev_partner_tasks(*, split: str | None = None) -> list[dict[str, Any]]:
    tasks = DEV_PARTNER_TASKS
    if split:
        tasks = [t for t in tasks if t.get("split") == split]
    return list(tasks)


def list_development_tasks() -> list[dict[str, Any]]:
    return list_dev_partner_tasks(split="development")


def list_holdout_tasks() -> list[dict[str, Any]]:
    return list_dev_partner_tasks(split="holdout")


def task_type_counts(tasks: list[dict[str, Any]] | None = None) -> dict[str, int]:
    tasks = tasks or DEV_PARTNER_TASKS
    counts: dict[str, int] = {}
    for t in tasks:
        tt = str(t.get("task_type") or "unknown")
        counts[tt] = counts.get(tt, 0) + 1
    return counts


def dataset_task_fingerprint(tasks: list[dict[str, Any]] | None = None) -> str:
    tasks = tasks or DEV_PARTNER_TASKS
    payload = [
        {
            "id": t["id"],
            "short_id": t.get("short_id"),
            "task_type": t.get("task_type"),
            "title": t.get("title"),
            "goal": t.get("goal"),
            "split": t.get("split"),
            "judge": t.get("judge"),
            "test_args": t.get("test_args"),
            "allowed_scope": t.get("allowed_scope"),
            "required_outputs": t.get("required_outputs"),
        }
        for t in tasks
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def suite_manifest() -> dict[str, Any]:
    return {
        "dataset_version": DEV_PARTNER_DATASET_VERSION,
        "seed_default": DEV_PARTNER_DATASET_SEED_DEFAULT,
        "task_count": len(DEV_PARTNER_TASKS),
        "task_types": task_type_counts(),
        "split_freeze": DEV_PARTNER_SPLIT_FREEZE,
        "development_count": len(list_development_tasks()),
        "holdout_count": len(list_holdout_tasks()),
        "task_fingerprint_sha256": dataset_task_fingerprint(),
        "note": (
            "Development cases may be used for failure-loop iteration. "
            "Holdout cases are reserved for baseline/comparison evidence. "
            "Independent judges live in evals.dev_partner_judges (outside agent workspaces)."
        ),
    }
