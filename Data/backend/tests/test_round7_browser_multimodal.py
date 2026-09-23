"""Round 7 — Browser and multimodal exit gates."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.artifacts import ArtifactStore, reopen_artifact
from Data.modules.browser import (
    BrowserAction,
    BrowserBackendKind,
    BrowserJobStatus,
    BrowserWorker,
    FixtureBrowserBackend,
    resolve_browser_backend,
)
from Data.modules.documents import extract_document, validate_numeric_values
from Data.modules.media import MediaAction, MediaService
from Data.modules.voice import RealtimeVoiceService, VoiceAction


SAMPLE_HTML = """<!DOCTYPE html>
<html><head><title>Round7 Demo</title></head>
<body>
  <h1>Welcome</h1>
  <p>Status: idle</p>
  <form id="signup">
    <input id="email" name="email" type="text" value="" />
    <input id="qty" name="qty" type="text" value="0" />
    <button id="submit" type="submit">Go</button>
  </form>
  <a id="report" href="report.csv" download="report.csv">Download report</a>
  <input id="file" type="file" />
  <table>
    <tr><th>Item</th><th>Amount</th></tr>
    <tr><td>Widgets</td><td>42.5</td></tr>
    <tr><td>Gadgets</td><td>7</td></tr>
  </table>
  <div class="footnotes">† Source: ledger page 2</div>
</body></html>
"""


class LocalDomBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.page = self.root / "page.html"
        self.page.write_text(SAMPLE_HTML, encoding="utf-8")
        (self.root / "report.csv").write_text("item,amount\nWidgets,42.5\n", encoding="utf-8")
        self.upload = self.root / "upload.txt"
        self.upload.write_text("payload", encoding="utf-8")
        self.worker = BrowserWorker(backend_kind="local_dom", allow_uploads=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_navigate_observe_click_type_form_verify_download_upload_screenshot(self) -> None:
        nav = self.worker.execute(
            action=BrowserAction.NAVIGATE,
            arguments={"url": str(self.page)},
            run_id="r7",
        )
        self.assertEqual(nav["status"], BrowserJobStatus.COMPLETED.value)
        self.assertEqual(nav["backend"], "local_dom")
        self.assertFalse(nav["truth"]["fixture_is_not_chromium"])
        self.assertIn("Welcome", nav["observation"]["dom_text"])
        self.assertIn("button:", nav["observation"]["accessibility_tree"])
        session_id = nav["session_id"]

        click = self.worker.execute(
            action=BrowserAction.CLICK,
            arguments={"session_id": session_id, "selector": "#submit"},
            run_id="r7",
        )
        # Click applied is NOT task completion.
        self.assertEqual(click["status"], BrowserJobStatus.APPLIED_UNVERIFIED.value)
        self.assertTrue(click["truth"]["click_is_not_task_completion"])
        self.assertTrue(click["metadata"].get("requires_verify_state"))

        verify_fail = self.worker.execute(
            action=BrowserAction.VERIFY_STATE,
            arguments={
                "session_id": session_id,
                "contains_text": "this text is not on the page",
            },
            run_id="r7",
        )
        self.assertEqual(verify_fail["status"], BrowserJobStatus.FAILED.value)

        typed = self.worker.execute(
            action=BrowserAction.TYPE,
            arguments={"session_id": session_id, "selector": "#email", "text": "a@b.c"},
            run_id="r7",
        )
        self.assertEqual(typed["status"], BrowserJobStatus.APPLIED_UNVERIFIED.value)

        filled = self.worker.execute(
            action=BrowserAction.FORM_FILL,
            arguments={"session_id": session_id, "fields": {"qty": "42"}},
            run_id="r7",
        )
        self.assertEqual(filled["status"], BrowserJobStatus.APPLIED_UNVERIFIED.value)

        verify_ok = self.worker.execute(
            action=BrowserAction.VERIFY_STATE,
            arguments={
                "session_id": session_id,
                "predicates": [
                    {"attribute_equals": {"selector": "#email", "attr": "value", "value": "a@b.c"}},
                    {"attribute_equals": {"selector": "#qty", "attr": "value", "value": "42"}},
                    {"form_submitted": True},
                ],
            },
            run_id="r7",
        )
        self.assertEqual(verify_ok["status"], BrowserJobStatus.COMPLETED.value)
        self.assertTrue(verify_ok["metadata"]["verification_passed"])

        dl = self.worker.execute(
            action=BrowserAction.DOWNLOAD,
            arguments={"session_id": session_id, "selector": "#report"},
            run_id="r7",
        )
        self.assertEqual(dl["status"], BrowserJobStatus.COMPLETED.value)
        self.assertEqual(dl["metadata"]["download"]["filename"], "report.csv")

        up = self.worker.execute(
            action=BrowserAction.UPLOAD,
            arguments={"session_id": session_id, "selector": "#file", "path": str(self.upload)},
            run_id="r7",
        )
        self.assertEqual(up["status"], BrowserJobStatus.APPLIED_UNVERIFIED.value)

        shot = self.worker.execute(
            action=BrowserAction.SCREENSHOT,
            arguments={"session_id": session_id},
            run_id="r7",
        )
        self.assertEqual(shot["status"], BrowserJobStatus.COMPLETED.value)
        self.assertEqual(shot["metadata"].get("screenshot_kind"), "html_dom_snapshot")

    def test_fixture_remains_test_only_and_playwright_unavailable(self) -> None:
        fixture = resolve_browser_backend("fixture")
        self.assertEqual(fixture.kind, BrowserBackendKind.FIXTURE)
        worker = BrowserWorker(backend=FixtureBrowserBackend())
        job = worker.request(action=BrowserAction.NAVIGATE, url="https://example.test/x")
        self.assertTrue(job.public_dict()["truth"]["fixture_is_not_chromium"])

        pw = resolve_browser_backend("playwright")
        self.assertEqual(pw.kind, BrowserBackendKind.PLAYWRIGHT)
        result = BrowserWorker(backend=pw).execute(
            action=BrowserAction.NAVIGATE,
            arguments={"url": "https://example.test"},
        )
        self.assertEqual(result["status"], BrowserJobStatus.UNSUPPORTED.value)
        self.assertTrue(result["truth"]["unavailable_is_not_ready"])

    def test_upload_denied_by_policy(self) -> None:
        worker = BrowserWorker(backend_kind="local_dom", allow_uploads=False)
        nav = worker.execute(action="NAVIGATE", arguments={"url": str(self.page)})
        denied = worker.execute(
            action="UPLOAD",
            arguments={
                "session_id": nav["session_id"],
                "path": str(self.upload),
            },
        )
        self.assertEqual(denied["status"], BrowserJobStatus.REJECTED.value)
        self.assertTrue(denied["truth"]["side_effects_under_authorization"])


class DocumentExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_html_tables_footnotes_numbers_with_provenance(self) -> None:
        path = self.root / "doc.html"
        path.write_text(SAMPLE_HTML, encoding="utf-8")
        extraction = extract_document(path)
        self.assertEqual(extraction.source_kind, "html")
        self.assertGreaterEqual(len(extraction.tables), 1)
        self.assertTrue(extraction.tables[0]["multi_column"])
        self.assertGreaterEqual(len(extraction.footnotes), 1)
        self.assertTrue(any(v.kind == "number" and v.value == 42.5 for v in extraction.values))
        report = validate_numeric_values(extraction, expected={"widgets": 42.5, "gadgets": 7})
        self.assertTrue(report["ok"])
        self.assertTrue(all(r["provenance"] for r in report["results"]))

    def test_multipage_text_and_scan_honesty(self) -> None:
        path = self.root / "multi.txt"
        path.write_text("Page one total 100\fPage two footnote * see ledger\nAmount 3.14", encoding="utf-8")
        extraction = extract_document(path)
        self.assertGreaterEqual(len(extraction.pages), 2)
        self.assertTrue(any(v.value == 3.14 for v in extraction.values))

        scan = self.root / "scan.png"
        scan.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        scan_ex = extract_document(scan)
        self.assertIn("ocr_scan", scan_ex.unsupported)

    def test_pdf_stream_fallback_without_pypdf(self) -> None:
        # Minimal PDF-like bytes with a literal string — stream fallback path.
        path = self.root / "mini.pdf"
        content = b"%PDF-1.4\n1 0 obj<< /Type /Page >>\n(BT Total 99 ET)\nendobj\n"
        path.write_bytes(content)
        extraction = extract_document(path)
        self.assertEqual(extraction.source_kind, "pdf")
        self.assertTrue(extraction.backend in {"pypdf", "pdf_stream_fallback"})


class ArtifactValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = ArtifactStore(root / "a.db", root / "artifacts")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reopen_validates_structure_not_just_create(self) -> None:
        record = self.store.create_from_bytes(
            data=b'{"ok": true, "count": 3}',
            artifact_type="json",
            producer="test",
            filename="out.json",
            metadata={"required_keys": ["ok", "count"]},
        )
        self.assertEqual(record.verification_status, "unverified")
        result = reopen_artifact(self.store, record.artifact_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["verification_status"], "validated")
        self.assertTrue(result["truth"]["file_created_is_not_validation"])
        refreshed = self.store.get(record.artifact_id)
        assert refreshed is not None
        self.assertEqual(refreshed.verification_status, "validated")

        bad = self.store.create_from_bytes(
            data=b"not-json",
            artifact_type="json",
            producer="test",
            filename="bad.json",
        )
        bad_result = reopen_artifact(self.store, bad.artifact_id)
        self.assertFalse(bad_result["ok"])


class VoiceMediaHonestyTests(unittest.TestCase):
    def test_fixture_media_not_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = ArtifactStore(root / "a.db", root / "artifacts")
            artifacts.initialize()
            media = MediaService(artifact_store=artifacts)
            gen = media.execute(
                action=MediaAction.IMAGE_GENERATE,
                arguments={"prompt": "cube"},
            )
            self.assertTrue(gen["truth"]["fixture_is_not_production"])
            self.assertFalse(gen["truth"]["production_capable"])
            job = media.request(action=MediaAction.PROBE, path=str(root / "missing.bin"))
            self.assertTrue(job.public_dict()["truth"]["fixture_is_not_production"])
            self.assertFalse(job.public_dict()["truth"]["production_capable"])

    def test_fixture_voice_not_production(self) -> None:
        from Data.modules.voice.realtime import VoiceJob, VoiceJobStatus, VoiceMetrics

        metrics = VoiceMetrics().public_dict()
        self.assertFalse(metrics["truth"]["production_capable"])
        self.assertTrue(metrics["truth"]["fixture_timestamps_are_not_production_metrics"])
        job = VoiceJob(
            job_id="j1",
            action=VoiceAction.START_SESSION,
            status=VoiceJobStatus.COMPLETED,
            detail="fixture",
        )
        self.assertFalse(job.public_dict()["truth"]["production_capable"])
        self.assertTrue(job.public_dict()["truth"]["fixture_is_not_production"])


if __name__ == "__main__":
    unittest.main()
