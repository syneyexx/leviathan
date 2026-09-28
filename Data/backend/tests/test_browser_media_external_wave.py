"""Browser + media externalization architecture regressions."""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.execution.browser_dispatch import enqueue_browser_job
from Data.modules.execution.media_dispatch import enqueue_media_job
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    api_may_execute_inline,
    classify_capability,
)
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability

BROWSER_LIVE = (
    "browser.navigate",
    "browser.extract_text",
    "browser.screenshot",
    "browser.click",
    "browser.type",
    "browser.form_fill",
    "browser.download",
    "browser.upload",
    "browser.verify_state",
    "browser.scroll",
    "browser.wait",
    "browser.keypress",
    "browser.qa.crawl",
    "browser.qa.advance",
    "browser.qa.replay",
)

MEDIA_LIVE = (
    "media.probe",
    "media.thumbnail",
    "media.image_generate",
    "media.image_edit",
    "media.video_ingest",
    "media.vision_inspect",
    "media.transcode",
    "media.convert",
    "media.audio.process",
    "media.video.process",
    "media.image.batch",
)


def _attr_calls(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                out.add(func.attr)
            elif isinstance(func, ast.Name):
                out.add(func.id)
    return out


class BrowserMediaPoolOwnershipTests(unittest.TestCase):
    def test_browser_pool_singleton(self) -> None:
        pool = POOL_CATALOG["browser"]
        self.assertEqual(pool.default_count, 1)
        self.assertEqual(pool.max_count, 1)
        self.assertTrue(any(k.startswith("browser") for k in pool.job_kinds))

    def test_media_pool_exists(self) -> None:
        pool = POOL_CATALOG["media"]
        self.assertEqual(pool.default_count, 1)
        self.assertEqual(pool.max_count, 2)

    def test_live_caps_route_to_specialists(self) -> None:
        for cap in BROWSER_LIVE:
            self.assertEqual(pool_for_capability(cap), "browser", msg=cap)
            self.assertEqual(
                classify_capability(cap),
                ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                msg=cap,
            )
            self.assertNotEqual(pool_for_capability(cap), "general", msg=cap)
        for cap in MEDIA_LIVE:
            self.assertEqual(pool_for_capability(cap), "media", msg=cap)
            self.assertEqual(
                classify_capability(cap),
                ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                msg=cap,
            )
            self.assertNotEqual(pool_for_capability(cap), "general", msg=cap)

    def test_voice_external_required(self) -> None:
        # Voice wave: production voice.* is EXTERNAL_REQUIRED (singleton pool),
        # same fail-closed class as browser/media — not EXTERNAL_PREFERRED.
        self.assertEqual(
            classify_capability("voice.transcribe"),
            ExecutionWorkloadClass.EXTERNAL_REQUIRED,
        )
        self.assertEqual(pool_for_capability("voice.transcribe"), "voice")

    def test_qa_status_inline_safe(self) -> None:
        self.assertEqual(
            classify_capability("browser.qa.status"),
            ExecutionWorkloadClass.INLINE_SAFE,
        )

    def test_api_cannot_inline_when_externalized(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}, clear=False):
            os.environ.pop("LEVIATHAN_WORKER_ID", None)
            for cap in ("browser.navigate", "browser.qa.crawl", "media.probe", "media.transcode"):
                self.assertFalse(api_may_execute_inline(cap), msg=cap)
                self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)


class BrowserMediaRouteBoundaryTests(unittest.TestCase):
    def test_browser_route_no_process_next_or_inline_execute(self) -> None:
        path = Path("Data/backend/routes/browser.py")
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = _attr_calls(tree)
        self.assertNotIn("process_next", calls)
        self.assertNotIn("browser_qa_crawler.run", source)
        self.assertIn("enqueue_and_maybe_await_browser", source)
        # Docstrings may mention forbidden patterns; executable calls must not.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotEqual(node.func.attr, "process_next")
                if isinstance(node.func.value, ast.Name) and node.func.value.id in {
                    "browser_worker",
                    "browser_qa_crawler",
                }:
                    self.assertNotIn(node.func.attr, {"execute", "run"})

    def test_browser_qa_route_no_worker_execute(self) -> None:
        path = Path("Data/backend/routes/browser_qa.py")
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = _attr_calls(tree)
        self.assertNotIn("process_next", calls)
        self.assertIn("enqueue_and_maybe_await_browser", source)
        self.assertNotIn("browser_worker.execute", source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "browser_worker":
                    self.fail(f"browser_worker.{node.func.attr}() must not be called from QA routes")

    def test_media_route_no_process_next(self) -> None:
        path = Path("Data/backend/routes/media.py")
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = _attr_calls(tree)
        self.assertNotIn("process_next", calls)
        self.assertIn("enqueue_and_maybe_await_media", source)

    def test_entrypoints_exist_and_no_process_next(self) -> None:
        for name in ("browser", "media"):
            path = Path(f"Data/modules/workers/entrypoints/{name}.py")
            self.assertTrue(path.is_file(), msg=name)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            self.assertNotIn("process_next", _attr_calls(tree))


class BrowserMediaEnqueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db = Path(self.tmp.name) / "jobs.db"
        store = JobStore(db)
        store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        self.runtime = JobRuntime(store, gateway, ResourceManager(2))

    def test_enqueue_browser_never_falls_to_general(self) -> None:
        job = enqueue_browser_job(
            self.runtime,
            capability_id="browser.navigate",
            arguments={"url": "https://example.com"},
        )
        self.assertEqual(job.worker_pool, "browser")
        self.assertIsNone(self.runtime.process_next())

    def test_enqueue_media_never_falls_to_general(self) -> None:
        job = enqueue_media_job(
            self.runtime,
            capability_id="media.probe",
            arguments={"path": "/tmp/x.mp4"},
        )
        self.assertEqual(job.worker_pool, "media")
        self.assertIsNone(self.runtime.process_next())

    def test_process_next_monkeypatch_routes_still_enqueue(self) -> None:
        """API helpers must not call process_next even if patched to explode."""
        with mock.patch.object(
            self.runtime, "process_next", side_effect=AssertionError("process_next forbidden")
        ):
            job = enqueue_browser_job(
                self.runtime,
                capability_id="browser.screenshot",
                arguments={},
            )
            self.assertEqual(job.worker_pool, "browser")
            job2 = enqueue_media_job(
                self.runtime,
                capability_id="media.thumbnail",
                arguments={"path": "/tmp/a.png"},
            )
            self.assertEqual(job2.worker_pool, "media")
            # Route modules must not call process_next (AST).
            for route_path in (
                Path("Data/backend/routes/browser.py"),
                Path("Data/backend/routes/media.py"),
                Path("Data/backend/routes/browser_qa.py"),
            ):
                tree = ast.parse(route_path.read_text(encoding="utf-8"))
                self.assertNotIn("process_next", _attr_calls(tree), msg=str(route_path))


class BrowserUrlPolicyTests(unittest.TestCase):
    def test_blocks_javascript_and_file(self) -> None:
        from Data.modules.browser.errors import BrowserDomainError
        from Data.modules.browser.url_policy import validate_browser_url

        with self.assertRaises(BrowserDomainError):
            validate_browser_url("javascript:alert(1)")
        with self.assertRaises(BrowserDomainError):
            validate_browser_url("file:///etc/passwd")

    def test_blocks_metadata_and_loopback_by_default(self) -> None:
        from Data.modules.browser.errors import BrowserDomainError
        from Data.modules.browser.url_policy import validate_browser_url

        with self.assertRaises(BrowserDomainError):
            validate_browser_url("http://127.0.0.1/admin")
        with self.assertRaises(BrowserDomainError):
            validate_browser_url("http://169.254.169.254/latest/meta-data")

    def test_qa_allowlist_permits_localhost(self) -> None:
        from Data.modules.browser.url_policy import validate_browser_url

        info = validate_browser_url(
            "http://localhost:8080/",
            allowed_hosts=("localhost", "127.0.0.1"),
        )
        self.assertTrue(info["allowlist"])


class MediaFfmpegSafetyTests(unittest.TestCase):
    def test_network_input_blocked(self) -> None:
        from Data.modules.media.errors import MediaDomainError
        from Data.modules.media.ffmpeg_backend import assert_local_media_path

        with self.assertRaises(MediaDomainError):
            assert_local_media_path("https://evil.example/video.mp4")

    def test_ffmpeg_backend_readiness_no_auto_install(self) -> None:
        from Data.modules.media.ffmpeg_backend import FfmpegMediaBackend

        backend = FfmpegMediaBackend()
        ready = backend.readiness()
        self.assertIn("ready", ready)
        # Must not have attempted playwright-style install keys
        self.assertNotIn("auto_installed", ready)

    def test_fixture_not_production_capable(self) -> None:
        from Data.modules.media import MediaService

        svc = MediaService()
        result = svc.execute(action="IMAGE_GENERATE", arguments={"prompt": "cat"})
        self.assertEqual(result.get("backend"), "fixture")
        self.assertFalse((result.get("truth") or {}).get("production_capable", True))


class BrowserPromptInjectionObservationTests(unittest.TestCase):
    def test_page_text_remains_untrusted_observation(self) -> None:
        from Data.modules.browser import BrowserAction, BrowserWorker, FixtureBrowserBackend

        worker = BrowserWorker(backend=FixtureBrowserBackend())
        result = worker.execute(
            action=BrowserAction.NAVIGATE,
            arguments={"url": "https://example.test/inject"},
            run_id="run-a",
        )
        obs = result.get("observation") or {}
        truth = (obs.get("truth") or {}) | (result.get("truth") or {})
        self.assertTrue(truth.get("page_text_is_untrusted_context"))


class HadesEditorUntouchedTests(unittest.TestCase):
    def test_diff_excludes_hades_and_editor(self) -> None:
        import subprocess

        # Prefer three-dot vs origin/main. Shallow CI clones may lack the ref —
        # fall back to the merge-base of HEAD's first-parent history, or skip
        # when no remote base is available (scope honesty CI job covers this).
        base = "origin/main"
        try:
            subprocess.check_call(
                ["git", "rev-parse", "--verify", base],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            try:
                subprocess.check_call(
                    ["git", "fetch", "--no-tags", "--depth", "50", "origin", "main"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError:
                self.skipTest("origin/main unavailable in this checkout")
        try:
            out = subprocess.check_output(
                ["git", "diff", "--name-only", f"{base}...HEAD"],
                text=True,
                stderr=subprocess.STDOUT,
            )
        except subprocess.CalledProcessError as exc:
            # Unrelated histories / missing merge-base — try two-dot against tip.
            try:
                out = subprocess.check_output(
                    ["git", "diff", "--name-only", f"{base}..HEAD"],
                    text=True,
                )
            except subprocess.CalledProcessError:
                self.skipTest(f"cannot diff against {base}: {exc}")
        for line in out.splitlines():
            self.assertFalse(line.startswith("Data/HADES/"), msg=line)
            self.assertFalse(line.startswith("editor/"), msg=line)


if __name__ == "__main__":
    unittest.main()
