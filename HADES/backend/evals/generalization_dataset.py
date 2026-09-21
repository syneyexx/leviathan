"""Generalization evaluation dataset (independent quality set).

Separate from E01–E08 known regression fixtures in ``independent_tasks.py``.
Holdout oracles live in ``holdout_judges.py`` — agents must not rewrite them.

Dataset version: generalization_v1 (>=20 substantively different tasks).
Expanded under A01 toward the combined agent eval corpus (see agent_tasks.py).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Callable


GENERALIZATION_DATASET_VERSION = "generalization_v1"
GENERALIZATION_DATASET_SEED_DEFAULT = 42


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures (each starts red; solutions are NOT embedded as agent oracles)
# ---------------------------------------------------------------------------


def fix_py_sort_key(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_sort_{variant}_"))
    _write(
        root / "ranking.py",
        "def by_score(rows):\n"
        "    # Bug: sorts ascending instead of descending by score\n"
        "    return sorted(rows, key=lambda r: r['score'])\n",
    )
    _write(
        root / "test_ranking.py",
        "import unittest\nfrom ranking import by_score\n"
        "class T(unittest.TestCase):\n"
        "    def test_highest_first(self):\n"
        "        out = by_score([{'score': 1}, {'score': 9}, {'score': 3}])\n"
        "        self.assertEqual([r['score'] for r in out], [9, 3, 1])\n",
    )
    return root


def fix_py_exception_swallow(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_exc_{variant}_"))
    _write(
        root / "safe_int.py",
        "def parse_int(text):\n"
        "    try:\n"
        "        return int(text)\n"
        "    except Exception:\n"
        "        # Bug: swallows and returns 0 instead of raising ValueError\n"
        "        return 0\n",
    )
    _write(
        root / "test_safe_int.py",
        "import unittest\nfrom safe_int import parse_int\n"
        "class T(unittest.TestCase):\n"
        "    def test_valid(self):\n"
        "        self.assertEqual(parse_int('7'), 7)\n"
        "    def test_invalid_raises(self):\n"
        "        with self.assertRaises(ValueError):\n"
        "            parse_int('nope')\n",
    )
    return root


def fix_py_off_by_one(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_obo_{variant}_"))
    _write(
        root / "window.py",
        "def last_n(items, n):\n"
        "    # Bug: off-by-one drops the oldest of the window\n"
        "    if n <= 0:\n"
        "        return []\n"
        "    return items[-(n - 1):] if n > 1 else []\n",
    )
    _write(
        root / "test_window.py",
        "import unittest\nfrom window import last_n\n"
        "class T(unittest.TestCase):\n"
        "    def test_last_three(self):\n"
        "        self.assertEqual(last_n([1, 2, 3, 4, 5], 3), [3, 4, 5])\n",
    )
    return root


def fix_py_mutable_default(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_mut_{variant}_"))
    _write(
        root / "bag.py",
        "def push(item, bucket=[]):\n"
        "    # Bug: mutable default shares state across calls\n"
        "    bucket.append(item)\n"
        "    return bucket\n",
    )
    _write(
        root / "test_bag.py",
        "import unittest\nfrom bag import push\n"
        "class T(unittest.TestCase):\n"
        "    def test_isolated(self):\n"
        "        a = push('x')\n"
        "        b = push('y')\n"
        "        self.assertEqual(a, ['x'])\n"
        "        self.assertEqual(b, ['y'])\n",
    )
    return root


def fix_js_multiply_runtime(*, variant: str = "holdout") -> Path:
    """Real Node execution judge — not string-only 'return a + b' proof."""
    root = Path(tempfile.mkdtemp(prefix=f"gen_js_mul_{variant}_"))
    _write(
        root / "math_util.mjs",
        "export function multiply(a, b) {\n  // Bug: adds instead of multiplies\n  return a + b;\n}\n",
    )
    _write(
        root / "run_check.mjs",
        "import { multiply } from './math_util.mjs';\n"
        "const got = multiply(6, 7);\n"
        "if (got !== 42) {\n"
        "  console.error('expected 42 got', got);\n"
        "  process.exit(1);\n"
        "}\n"
        "console.log('ok');\n",
    )
    _write(
        root / "test_math_runtime.py",
        "import shutil\nimport subprocess\nimport unittest\nfrom pathlib import Path\n"
        "class T(unittest.TestCase):\n"
        "    def test_node_runtime(self):\n"
        "        node = shutil.which('node')\n"
        "        self.assertIsNotNone(node, 'node required for JS runtime proof')\n"
        "        proc = subprocess.run([node, 'run_check.mjs'], cwd=str(Path('.')), capture_output=True, text=True)\n"
        "        self.assertEqual(proc.returncode, 0, proc.stderr)\n",
    )
    return root


def fix_js_async_await(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_js_async_{variant}_"))
    _write(
        root / "fetcher.mjs",
        "export async function loadValue() {\n"
        "  return Promise.resolve(21).then((x) => x * 2);\n"
        "}\n"
        "export function getValueSyncBroken() {\n"
        "  // Bug: returns a Promise instead of awaited number\n"
        "  return loadValue();\n"
        "}\n",
    )
    _write(
        root / "run_check.mjs",
        "import { getValueSyncBroken } from './fetcher.mjs';\n"
        "// Correct API after fix should be async getValue returning 42\n"
        "import * as mod from './fetcher.mjs';\n"
        "const fn = mod.getValue || mod.getValueSyncBroken;\n"
        "const result = await fn();\n"
        "if (result !== 42) {\n"
        "  console.error('expected 42 got', result);\n"
        "  process.exit(1);\n"
        "}\n"
        "if (typeof result !== 'number') {\n"
        "  console.error('expected number');\n"
        "  process.exit(1);\n"
        "}\n"
        "console.log('ok');\n",
    )
    _write(
        root / "test_async_runtime.py",
        "import shutil\nimport subprocess\nimport unittest\nfrom pathlib import Path\n"
        "class T(unittest.TestCase):\n"
        "    def test_awaited_number(self):\n"
        "        node = shutil.which('node')\n"
        "        self.assertIsNotNone(node)\n"
        "        # After fix, module should export async getValue()\n"
        "        src = Path('fetcher.mjs').read_text(encoding='utf-8')\n"
        "        self.assertIn('export async function getValue', src)\n"
        "        proc = subprocess.run([node, 'run_check.mjs'], cwd='.', capture_output=True, text=True)\n"
        "        self.assertEqual(proc.returncode, 0, proc.stderr)\n",
    )
    return root


def fix_api_status_contract(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_api_st_{variant}_"))
    _write(
        root / "handlers.py",
        "def create_item(payload):\n"
        "    # Bug: returns 200 for create; contract requires 201\n"
        "    return {'status': 200, 'body': {'id': 1, **payload}}\n",
    )
    _write(
        root / "test_handlers.py",
        "import unittest\nfrom handlers import create_item\n"
        "class T(unittest.TestCase):\n"
        "    def test_created_status(self):\n"
        "        resp = create_item({'name': 'x'})\n"
        "        self.assertEqual(resp['status'], 201)\n"
        "        self.assertEqual(resp['body']['name'], 'x')\n",
    )
    return root


def fix_api_pagination_field(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_page_{variant}_"))
    _write(
        root / "list_api.py",
        "def list_page(items, page, page_size):\n"
        "    start = (page - 1) * page_size\n"
        "    chunk = items[start:start + page_size]\n"
        "    # Bug: uses 'next' bool instead of 'next_page' int|None\n"
        "    return {'items': chunk, 'next': start + page_size < len(items)}\n",
    )
    _write(
        root / "test_list_api.py",
        "import unittest\nfrom list_api import list_page\n"
        "class T(unittest.TestCase):\n"
        "    def test_next_page_int(self):\n"
        "        out = list_page(list(range(10)), page=1, page_size=3)\n"
        "        self.assertEqual(out['items'], [0, 1, 2])\n"
        "        self.assertEqual(out.get('next_page'), 2)\n"
        "        self.assertNotIn('next', out)\n"
        "    def test_last_page(self):\n"
        "        out = list_page(list(range(3)), page=1, page_size=3)\n"
        "        self.assertIsNone(out.get('next_page'))\n",
    )
    return root


def fix_config_env_override(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_env_{variant}_"))
    _write(root / "defaults.json", json.dumps({"region": "eu", "debug": False}))
    _write(
        root / "settings_loader.py",
        "import json\nimport os\nfrom pathlib import Path\n\n"
        "def load():\n"
        "    data = json.loads(Path('defaults.json').read_text(encoding='utf-8'))\n"
        "    # Bug: ignores HADES_REGION env override\n"
        "    return data\n",
    )
    _write(
        root / "test_settings_loader.py",
        "import os\nimport unittest\nfrom settings_loader import load\n"
        "class T(unittest.TestCase):\n"
        "    def test_env_override(self):\n"
        "        os.environ['HADES_REGION'] = 'us'\n"
        "        try:\n"
        "            cfg = load()\n"
        "            self.assertEqual(cfg['region'], 'us')\n"
        "        finally:\n"
        "            os.environ.pop('HADES_REGION', None)\n",
    )
    return root


def fix_config_key_typo(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_key_{variant}_"))
    _write(root / "app.toml", "timeout_seconds = 15\nmax_retries = 3\n")
    _write(
        root / "read_config.py",
        "from pathlib import Path\n\n"
        "def timeout():\n"
        "    text = Path('app.toml').read_text(encoding='utf-8')\n"
        "    values = {}\n"
        "    for line in text.splitlines():\n"
        "        if '=' in line:\n"
        "            k, v = line.split('=', 1)\n"
        "            values[k.strip()] = int(v.strip())\n"
        "    # Bug: looks up timeout_secs instead of timeout_seconds\n"
        "    return values.get('timeout_secs', 60)\n",
    )
    _write(
        root / "test_read_config.py",
        "import unittest\nfrom read_config import timeout\n"
        "class T(unittest.TestCase):\n"
        "    def test_reads_timeout_seconds(self):\n"
        "        self.assertEqual(timeout(), 15)\n",
    )
    return root


def fix_async_gather_cancel(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_gather_{variant}_"))
    _write(
        root / "fanout.py",
        "import asyncio\n\n"
        "async def work(n):\n"
        "    await asyncio.sleep(0.01)\n"
        "    return n * 2\n\n"
        "async def run_all(values):\n"
        "    # Bug: uses return_exceptions incorrectly and drops failures as None\n"
        "    results = await asyncio.gather(*[work(v) for v in values], return_exceptions=True)\n"
        "    return [None if isinstance(r, Exception) else r for r in results]\n",
    )
    _write(
        root / "test_fanout.py",
        "import asyncio\nimport unittest\nfrom fanout import run_all\n"
        "class T(unittest.TestCase):\n"
        "    def test_doubles(self):\n"
        "        out = asyncio.run(run_all([1, 2, 3]))\n"
        "        self.assertEqual(out, [2, 4, 6])\n"
        "    def test_source_raises_on_worker_error(self):\n"
        "        # Contract: run_all must NOT swallow exceptions into None\n"
        "        src = open('fanout.py', encoding='utf-8').read()\n"
        "        self.assertNotIn('None if isinstance(r, Exception)', src)\n",
    )
    return root


def fix_thread_join(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_join_{variant}_"))
    _write(
        root / "parallel.py",
        "import threading\n\n"
        "def map_parallel(fn, items):\n"
        "    out = [None] * len(items)\n"
        "    threads = []\n"
        "    for i, item in enumerate(items):\n"
        "        def target(idx=i, value=item):\n"
        "            out[idx] = fn(value)\n"
        "        t = threading.Thread(target=target)\n"
        "        threads.append(t)\n"
        "        t.start()\n"
        "    # Bug: missing join — may return before workers finish\n"
        "    return out\n",
    )
    _write(
        root / "test_parallel.py",
        "import time\nimport unittest\nfrom parallel import map_parallel\n"
        "class T(unittest.TestCase):\n"
        "    def test_joins(self):\n"
        "        src = open('parallel.py', encoding='utf-8').read()\n"
        "        self.assertIn('.join()', src)\n"
        "        def slow(x):\n"
        "            time.sleep(0.05)\n"
        "            return x + 1\n"
        "        self.assertEqual(map_parallel(slow, [1, 2, 3]), [2, 3, 4])\n",
    )
    return root


def fix_error_type(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_errtype_{variant}_"))
    _write(
        root / "validate.py",
        "def require_positive(n):\n"
        "    if n <= 0:\n"
        "        # Bug: raises RuntimeError; API contract is ValueError\n"
        "        raise RuntimeError('n must be positive')\n"
        "    return n\n",
    )
    _write(
        root / "test_validate.py",
        "import unittest\nfrom validate import require_positive\n"
        "class T(unittest.TestCase):\n"
        "    def test_value_error(self):\n"
        "        with self.assertRaises(ValueError):\n"
        "            require_positive(0)\n"
        "    def test_ok(self):\n"
        "        self.assertEqual(require_positive(2), 2)\n",
    )
    return root


def fix_retry_backoff(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_retry_{variant}_"))
    _write(
        root / "retry.py",
        "def with_retries(fn, *, attempts=3):\n"
        "    # Bug: only tries once\n"
        "    return fn()\n",
    )
    _write(
        root / "test_retry.py",
        "import unittest\nfrom retry import with_retries\n"
        "class T(unittest.TestCase):\n"
        "    def test_retries_until_success(self):\n"
        "        state = {'n': 0}\n"
        "        def flaky():\n"
        "            state['n'] += 1\n"
        "            if state['n'] < 3:\n"
        "                raise ConnectionError('tmp')\n"
        "            return 'ok'\n"
        "        self.assertEqual(with_retries(flaky, attempts=5), 'ok')\n"
        "        self.assertEqual(state['n'], 3)\n",
    )
    return root


def fix_multifile_constant_drift(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_drift_{variant}_"))
    _write(root / "constants.py", "MAX_ITEMS = 10\n")
    _write(
        root / "service.py",
        "from constants import MAX_ITEMS\n\n"
        "def clamp(n):\n"
        "    # Bug: hardcodes 5 instead of shared MAX_ITEMS\n"
        "    return min(n, 5)\n",
    )
    _write(
        root / "test_service.py",
        "import unittest\nfrom service import clamp\nfrom constants import MAX_ITEMS\n"
        "class T(unittest.TestCase):\n"
        "    def test_uses_constant(self):\n"
        "        self.assertEqual(clamp(100), MAX_ITEMS)\n"
        "        src = open('service.py', encoding='utf-8').read()\n"
        "        self.assertIn('MAX_ITEMS', src)\n",
    )
    return root


def fix_multifile_wrong_import(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_imp_{variant}_"))
    pkg = root / "payments"
    pkg.mkdir()
    _write(pkg / "__init__.py", "")
    _write(pkg / "legacy.py", "def charge(amount):\n    return amount * 0\n")
    _write(pkg / "modern.py", "def charge(amount):\n    return amount\n")
    _write(
        root / "checkout.py",
        "from payments.legacy import charge\n\n"
        "def total(amount):\n"
        "    # Bug: imports legacy zeroing charge\n"
        "    return charge(amount)\n",
    )
    _write(
        root / "test_checkout.py",
        "import unittest\nfrom checkout import total\n"
        "class T(unittest.TestCase):\n"
        "    def test_charges_full(self):\n"
        "        self.assertEqual(total(50), 50)\n",
    )
    return root


def fix_docs_cli_flag(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_docs_cli_{variant}_"))
    _write(root / "cli.py", "import argparse\n\ndef build_parser():\n    p = argparse.ArgumentParser()\n    p.add_argument('--dry-run', action='store_true')\n    return p\n")
    _write(root / "README.md", "Run with `python cli.py --dryrun`.\n")
    _write(
        root / "test_docs.py",
        "import unittest\nfrom pathlib import Path\nfrom cli import build_parser\n"
        "class T(unittest.TestCase):\n"
        "    def test_readme_flag_matches_parser(self):\n"
        "        text = Path('README.md').read_text(encoding='utf-8')\n"
        "        self.assertIn('--dry-run', text)\n"
        "        self.assertNotIn('--dryrun', text)\n"
        "        ns = build_parser().parse_args(['--dry-run'])\n"
        "        self.assertTrue(ns.dry_run)\n",
    )
    return root


def fix_docs_version_badge(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_docs_ver_{variant}_"))
    _write(root / "VERSION", "2.4.1\n")
    _write(root / "docs" / "install.md", "Install HADES v2.3.0 from the releases page.\n")
    _write(
        root / "test_version_docs.py",
        "import unittest\nfrom pathlib import Path\n"
        "class T(unittest.TestCase):\n"
        "    def test_docs_match_version_file(self):\n"
        "        ver = Path('VERSION').read_text(encoding='utf-8').strip()\n"
        "        text = Path('docs/install.md').read_text(encoding='utf-8')\n"
        "        self.assertIn(ver, text)\n",
    )
    return root


def fix_flow_csrf_drop(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_csrf_{variant}_"))
    _write(
        root / "form_flow.py",
        "def prepare_submit(form, session):\n"
        "    # Bug: drops csrf_token from session\n"
        "    return {'name': form.get('name'), 'csrf_token': None}\n",
    )
    _write(
        root / "test_form_flow.py",
        "import unittest\nfrom form_flow import prepare_submit\n"
        "class T(unittest.TestCase):\n"
        "    def test_keeps_csrf(self):\n"
        "        out = prepare_submit({'name': 'ada'}, {'csrf_token': 'tok-9'})\n"
        "        self.assertEqual(out['csrf_token'], 'tok-9')\n",
    )
    return root


def fix_flow_redirect_query(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_redir_{variant}_"))
    _write(
        root / "redirect.py",
        "from urllib.parse import urlencode, urlparse, parse_qs, urlunparse\n\n"
        "def continue_url(base, next_path, preserve_query=True):\n"
        "    # Bug: drops query string from next_path\n"
        "    return f'{base}?next={next_path.split(\"?\")[0]}'\n",
    )
    _write(
        root / "test_redirect.py",
        "import unittest\nfrom redirect import continue_url\n"
        "class T(unittest.TestCase):\n"
        "    def test_preserves_query(self):\n"
        "        url = continue_url('https://app/login', '/dash?tab=billing')\n"
        "        self.assertIn('tab=billing', url)\n",
    )
    return root


def fix_py_timezone(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_tz_{variant}_"))
    _write(
        root / "schedule.py",
        "from datetime import datetime\n\n"
        "def is_past(ts_iso):\n"
        "    # Bug: compares naive now to aware timestamps incorrectly by stripping tz\n"
        "    ts = datetime.fromisoformat(ts_iso.replace('Z', '+00:00'))\n"
        "    return datetime.utcnow() > ts.replace(tzinfo=None)\n",
    )
    _write(
        root / "test_schedule.py",
        "import unittest\nfrom datetime import datetime, timezone, timedelta\nfrom schedule import is_past\n"
        "class T(unittest.TestCase):\n"
        "    def test_aware_past(self):\n"
        "        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()\n"
        "        self.assertTrue(is_past(past))\n"
        "    def test_keeps_tz_compare(self):\n"
        "        src = open('schedule.py', encoding='utf-8').read()\n"
        "        self.assertNotIn('replace(tzinfo=None)', src)\n",
    )
    return root


def fix_json_error_contract(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_json_{variant}_"))
    _write(
        root / "parse_json.py",
        "import json\n\n"
        "def loads_strict(text):\n"
        "    # Bug: returns {} on error instead of raising json.JSONDecodeError\n"
        "    try:\n"
        "        return json.loads(text)\n"
        "    except Exception:\n"
        "        return {}\n",
    )
    _write(
        root / "test_parse_json.py",
        "import json\nimport unittest\nfrom parse_json import loads_strict\n"
        "class T(unittest.TestCase):\n"
        "    def test_ok(self):\n"
        "        self.assertEqual(loads_strict('{\"a\":1}'), {'a': 1})\n"
        "    def test_raises(self):\n"
        "        with self.assertRaises(json.JSONDecodeError):\n"
        "            loads_strict('{bad')\n",
    )
    return root


def fix_py_whitespace_strip(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_strip_{variant}_"))
    _write(
        root / "normalize.py",
        "def clean_label(text):\n"
        "    # Bug: strips only leading whitespace\n"
        "    return text.lstrip()\n",
    )
    _write(
        root / "test_normalize.py",
        "import unittest\nfrom normalize import clean_label\n"
        "class T(unittest.TestCase):\n"
        "    def test_both_sides(self):\n"
        "        self.assertEqual(clean_label('  hi  '), 'hi')\n",
    )
    return root


def fix_py_dict_merge(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_merge_{variant}_"))
    _write(
        root / "merge.py",
        "def merge_prefs(a, b):\n"
        "    # Bug: shallow update mutates caller and loses nested defaults\n"
        "    a.update(b)\n"
        "    return a\n",
    )
    _write(
        root / "test_merge.py",
        "import unittest\nfrom merge import merge_prefs\n"
        "class T(unittest.TestCase):\n"
        "    def test_does_not_mutate_left(self):\n"
        "        left = {'theme': 'dark', 'nested': {'x': 1}}\n"
        "        right = {'nested': {'y': 2}}\n"
        "        out = merge_prefs(left, right)\n"
        "        self.assertEqual(left, {'theme': 'dark', 'nested': {'x': 1}})\n"
        "        self.assertEqual(out['nested'], {'x': 1, 'y': 2})\n"
        "        self.assertEqual(out['theme'], 'dark')\n",
    )
    return root


def fix_py_path_join(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_path_{variant}_"))
    _write(
        root / "paths.py",
        "def join_under(root, rel):\n"
        "    # Bug: string concat allows escaping via ../\n"
        "    return root + '/' + rel\n",
    )
    _write(
        root / "test_paths.py",
        "import unittest\nfrom pathlib import Path\nfrom paths import join_under\n"
        "class T(unittest.TestCase):\n"
        "    def test_rejects_escape(self):\n"
        "        root = '/workspace/project'\n"
        "        with self.assertRaises(ValueError):\n"
        "            join_under(root, '../secret')\n"
        "    def test_joins_safe(self):\n"
        "        out = join_under('/workspace/project', 'src/a.py')\n"
        "        self.assertEqual(Path(out).as_posix(), '/workspace/project/src/a.py')\n",
    )
    return root


def fix_py_regex_literal(*, variant: str = "holdout") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"gen_re_{variant}_"))
    _write(
        root / "match_id.py",
        "import re\n\ndef find_id(text, needle):\n"
        "    # Bug: treats needle as regex instead of literal\n"
        "    return bool(re.search(needle, text))\n",
    )
    _write(
        root / "test_match_id.py",
        "import unittest\nfrom match_id import find_id\n"
        "class T(unittest.TestCase):\n"
        "    def test_literal_dot(self):\n"
        "        self.assertFalse(find_id('fileXtxt', 'file.txt'))\n"
        "        self.assertTrue(find_id('file.txt', 'file.txt'))\n",
    )
    return root


def fix_ts_type_narrow_runtime(*, variant: str = "holdout") -> Path:
    """JS runtime check for a TS-authored module (executed via Node)."""
    root = Path(tempfile.mkdtemp(prefix=f"gen_ts_narrow_{variant}_"))
    _write(
        root / "narrow.ts",
        "export function label(value: string | null): string {\n"
        "  // Bug: does not narrow null\n"
        "  return value.toUpperCase();\n"
        "}\n",
    )
    # Emit a JS mirror the agent must fix; judge runs JS for real execution.
    _write(
        root / "narrow.mjs",
        "export function label(value) {\n  return value.toUpperCase();\n}\n",
    )
    _write(
        root / "run_check.mjs",
        "import { label } from './narrow.mjs';\n"
        "if (label('ok') !== 'OK') process.exit(1);\n"
        "if (label(null) !== '') { console.error('null must map to empty string'); process.exit(1); }\n"
        "console.log('ok');\n",
    )
    _write(
        root / "test_narrow_runtime.py",
        "import shutil\nimport subprocess\nimport unittest\nfrom pathlib import Path\n"
        "class T(unittest.TestCase):\n"
        "    def test_runtime_and_ts_source(self):\n"
        "        node = shutil.which('node')\n"
        "        self.assertIsNotNone(node)\n"
        "        ts = Path('narrow.ts').read_text(encoding='utf-8')\n"
        "        self.assertIn('value === null', ts)\n"
        "        proc = subprocess.run([node, 'run_check.mjs'], cwd='.', capture_output=True, text=True)\n"
        "        self.assertEqual(proc.returncode, 0, proc.stderr)\n",
    )
    return root


GENERALIZATION_TASKS: list[dict[str, Any]] = [
    {
        "id": "G01_py_sort",
        "category": "python",
        "title": "Descending sort by score",
        "fixture": fix_py_sort_key,
        "goal": "Fix by_score so highest scores come first",
        "test_args": ["test_ranking.py"],
        "split": "holdout",
    },
    {
        "id": "G02_py_exc",
        "category": "python",
        "title": "Invalid int must raise ValueError",
        "fixture": fix_py_exception_swallow,
        "goal": "parse_int should raise ValueError on invalid input",
        "test_args": ["test_safe_int.py"],
        "split": "holdout",
    },
    {
        "id": "G03_py_off_by_one",
        "category": "python",
        "title": "Window last_n off-by-one",
        "fixture": fix_py_off_by_one,
        "goal": "Fix last_n to return the last n items",
        "test_args": ["test_window.py"],
        "split": "holdout",
    },
    {
        "id": "G04_py_mutable_default",
        "category": "python",
        "title": "Mutable default argument",
        "fixture": fix_py_mutable_default,
        "goal": "Fix push so each call gets an isolated bucket",
        "test_args": ["test_bag.py"],
        "split": "holdout",
    },
    {
        "id": "G05_js_multiply",
        "category": "ts_js",
        "title": "JS multiply runtime proof",
        "fixture": fix_js_multiply_runtime,
        "goal": "Fix multiply in math_util.mjs; must pass Node run_check",
        "test_args": ["test_math_runtime.py"],
        "split": "holdout",
    },
    {
        "id": "G06_js_async",
        "category": "async_concurrency",
        "title": "Async getValue must return number",
        "fixture": fix_js_async_await,
        "goal": "Export async getValue that awaits and returns 42",
        "test_args": ["test_async_runtime.py"],
        "split": "holdout",
    },
    {
        "id": "G07_api_status",
        "category": "api_contracts",
        "title": "Create returns HTTP 201",
        "fixture": fix_api_status_contract,
        "goal": "create_item must return status 201",
        "test_args": ["test_handlers.py"],
        "split": "holdout",
    },
    {
        "id": "G08_api_pagination",
        "category": "api_contracts",
        "title": "Pagination next_page field",
        "fixture": fix_api_pagination_field,
        "goal": "Return next_page int|None instead of boolean next",
        "test_args": ["test_list_api.py"],
        "split": "holdout",
    },
    {
        "id": "G09_config_env",
        "category": "config",
        "title": "Env override for region",
        "fixture": fix_config_env_override,
        "goal": "Honor HADES_REGION over defaults.json",
        "test_args": ["test_settings_loader.py"],
        "split": "holdout",
    },
    {
        "id": "G10_config_key",
        "category": "config",
        "title": "TOML key typo in reader",
        "fixture": fix_config_key_typo,
        "goal": "Read timeout_seconds from app.toml",
        "test_args": ["test_read_config.py"],
        "split": "holdout",
    },
    {
        "id": "G11_async_gather",
        "category": "async_concurrency",
        "title": "asyncio.gather must not swallow errors as None",
        "fixture": fix_async_gather_cancel,
        "goal": "Fix run_all to propagate or re-raise worker errors",
        "test_args": ["test_fanout.py"],
        "split": "holdout",
    },
    {
        "id": "G12_thread_join",
        "category": "async_concurrency",
        "title": "Thread map must join workers",
        "fixture": fix_thread_join,
        "goal": "Join threads before returning from map_parallel",
        "test_args": ["test_parallel.py"],
        "split": "holdout",
    },
    {
        "id": "G13_error_type",
        "category": "error_handling",
        "title": "Require ValueError not RuntimeError",
        "fixture": fix_error_type,
        "goal": "require_positive must raise ValueError",
        "test_args": ["test_validate.py"],
        "split": "holdout",
    },
    {
        "id": "G14_retry",
        "category": "error_handling",
        "title": "Retry until attempts exhausted",
        "fixture": fix_retry_backoff,
        "goal": "with_retries must retry on failure up to attempts",
        "test_args": ["test_retry.py"],
        "split": "holdout",
    },
    {
        "id": "G15_multifile_drift",
        "category": "multi_file",
        "title": "Shared MAX_ITEMS constant drift",
        "fixture": fix_multifile_constant_drift,
        "goal": "clamp must use constants.MAX_ITEMS",
        "test_args": ["test_service.py"],
        "split": "holdout",
    },
    {
        "id": "G16_multifile_import",
        "category": "multi_file",
        "title": "Wrong payments import",
        "fixture": fix_multifile_wrong_import,
        "goal": "checkout must use payments.modern.charge",
        "test_args": ["test_checkout.py"],
        "split": "holdout",
    },
    {
        "id": "G17_docs_cli",
        "category": "docs",
        "title": "README CLI flag mismatch",
        "fixture": fix_docs_cli_flag,
        "goal": "Align README with --dry-run flag",
        "test_args": ["test_docs.py"],
        "split": "holdout",
    },
    {
        "id": "G18_docs_version",
        "category": "docs",
        "title": "Docs version vs VERSION file",
        "fixture": fix_docs_version_badge,
        "goal": "docs/install.md must mention VERSION contents",
        "test_args": ["test_version_docs.py"],
        "split": "holdout",
    },
    {
        "id": "G19_flow_csrf",
        "category": "user_flow",
        "title": "CSRF token dropped on submit",
        "fixture": fix_flow_csrf_drop,
        "goal": "Preserve csrf_token from session into submit payload",
        "test_args": ["test_form_flow.py"],
        "split": "holdout",
    },
    {
        "id": "G20_flow_redirect",
        "category": "user_flow",
        "title": "Redirect drops query string",
        "fixture": fix_flow_redirect_query,
        "goal": "Preserve query string when building continue_url",
        "test_args": ["test_redirect.py"],
        "split": "holdout",
    },
    {
        "id": "G21_py_timezone",
        "category": "python",
        "title": "Timezone-aware is_past",
        "fixture": fix_py_timezone,
        "goal": "Compare aware UTC timestamps without stripping tzinfo",
        "test_args": ["test_schedule.py"],
        "split": "holdout",
    },
    {
        "id": "G22_json_contract",
        "category": "error_handling",
        "title": "JSON decode must raise",
        "fixture": fix_json_error_contract,
        "goal": "loads_strict must raise json.JSONDecodeError on bad input",
        "test_args": ["test_parse_json.py"],
        "split": "holdout",
    },
    {
        "id": "G23_ts_narrow",
        "category": "ts_js",
        "title": "Null narrow with Node runtime",
        "fixture": fix_ts_type_narrow_runtime,
        "goal": "label(null) returns '' and TS source narrows null",
        "test_args": ["test_narrow_runtime.py"],
        "split": "holdout",
    },
    {
        "id": "G24_py_strip",
        "category": "python",
        "title": "Strip both sides of label",
        "fixture": fix_py_whitespace_strip,
        "goal": "clean_label must strip leading and trailing whitespace",
        "test_args": ["test_normalize.py"],
        "split": "holdout",
    },
    {
        "id": "G25_py_merge",
        "category": "python",
        "title": "Deep-ish merge without mutating left",
        "fixture": fix_py_dict_merge,
        "goal": "merge_prefs must not mutate left and must keep nested keys",
        "test_args": ["test_merge.py"],
        "split": "holdout",
    },
    {
        "id": "G26_py_path_join",
        "category": "error_handling",
        "title": "Reject path escape in join_under",
        "fixture": fix_py_path_join,
        "goal": "join_under must raise ValueError on ../ escape",
        "test_args": ["test_paths.py"],
        "split": "holdout",
    },
    {
        "id": "G27_py_regex_literal",
        "category": "python",
        "title": "Match needle as literal not regex",
        "fixture": fix_py_regex_literal,
        "goal": "find_id must treat needle as a literal substring pattern",
        "test_args": ["test_match_id.py"],
        "split": "holdout",
    },
]


# Development examples — visible patterns for harness demos; NOT holdout oracles.
DEVELOPMENT_EXAMPLES: list[dict[str, Any]] = [
    {
        "id": "DEV01_py_add_sign",
        "category": "python",
        "title": "Dev-only sign flip (not holdout)",
        "split": "development",
        "note": "Development illustration only; excluded from holdout scoring.",
        "goal": "Flip subtract to add in demo module",
        "fixture": fix_py_sort_key,  # intentional reuse for wiring only; not scored as holdout
        "test_args": ["test_ranking.py"],
    },
    {
        "id": "DEV02_py_strip_demo",
        "category": "python",
        "title": "Dev-only strip demo (not holdout)",
        "split": "development",
        "note": "Development illustration only; excluded from holdout scoring.",
        "goal": "Demo strip both sides",
        "fixture": fix_py_whitespace_strip,
        "test_args": ["test_normalize.py"],
    },
]


def dataset_task_fingerprint(tasks: list[dict[str, Any]] | None = None) -> str:
    tasks = tasks or GENERALIZATION_TASKS
    payload = [
        {
            "id": t["id"],
            "category": t["category"],
            "title": t["title"],
            "goal": t["goal"],
            "test_args": t.get("test_args"),
            "split": t.get("split"),
        }
        for t in tasks
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def list_holdout_tasks() -> list[dict[str, Any]]:
    return [t for t in GENERALIZATION_TASKS if t.get("split") == "holdout"]


def categories_covered() -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in GENERALIZATION_TASKS:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    return counts
