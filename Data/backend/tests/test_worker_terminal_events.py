"""W1 — Worker terminal observability foundation."""

from __future__ import annotations

import io
import threading
import unittest

from Data.modules.workers.events import (
    WorkerEvent,
    WorkerEventEmitter,
    WorkerEventKind,
    format_duration_ms,
    format_terminal_message,
    resolve_human_title,
    sanitize_human_label,
    set_worker_event_emitter,
    utc_timestamp,
)


class SanitizeLabelTests(unittest.TestCase):
    def test_strips_newlines_and_control_chars(self) -> None:
        label = sanitize_human_label("Hello\nWorld\t\x00X")
        self.assertEqual(label, "Hello World X")
        self.assertNotIn("\n", label)

    def test_truncates_long_titles(self) -> None:
        long = "A" * 200
        label = sanitize_human_label(long)
        self.assertLessEqual(len(label), 120)
        self.assertTrue(label.endswith("…"))

    def test_empty_none(self) -> None:
        self.assertEqual(sanitize_human_label(None), "")
        self.assertEqual(sanitize_human_label(""), "")


class DurationFormatTests(unittest.TestCase):
    def test_seconds(self) -> None:
        self.assertEqual(format_duration_ms(8700), "8.7s")

    def test_minutes(self) -> None:
        self.assertEqual(format_duration_ms(138_000), "02:18")

    def test_hours(self) -> None:
        self.assertEqual(format_duration_ms(4934_000), "01:22:14")


class ResolveHumanTitleTests(unittest.TestCase):
    def test_research_topic(self) -> None:
        title = resolve_human_title(
            capability_id="research.advance",
            metadata={"topic": "Quantum sensors"},
        )
        self.assertEqual(title, "Quantum sensors")

    def test_source_filename(self) -> None:
        title = resolve_human_title(
            capability_id="source_ingestion.process",
            arguments={"filename": "paper.pdf"},
        )
        self.assertEqual(title, "paper.pdf")

    def test_ignores_secret_looking_keys_as_values_still_ok_from_topic(self) -> None:
        title = resolve_human_title(
            capability_id="research.advance",
            metadata={"api_key": "sk-secret", "topic": "Safe topic"},
        )
        self.assertEqual(title, "Safe topic")
        self.assertNotIn("sk-secret", title)


class FormatterTests(unittest.TestCase):
    def test_research_started(self) -> None:
        event = WorkerEvent(
            event=WorkerEventKind.JOB_STARTED,
            timestamp=utc_timestamp(),
            pool="research",
            worker_id="research-0-abc",
            job_id="ab12cd34ef",
            capability_id="research.advance",
            domain="research",
            human_title="Example topic",
        )
        line = format_terminal_message(event)
        self.assertIn("[WORKER:research-1]", line)
        self.assertIn("Research 'Example topic' gestart", line)
        self.assertIn("job ab12cd34", line)

    def test_research_completed_duration(self) -> None:
        event = WorkerEvent(
            event=WorkerEventKind.JOB_COMPLETED,
            timestamp=utc_timestamp(),
            pool="research",
            worker_id="research-0-abc",
            capability_id="research.advance",
            human_title="Example topic",
            duration_ms=32400,
        )
        line = format_terminal_message(event)
        self.assertIn("voltooid", line)
        self.assertIn("32.4s", line)

    def test_source_failed_safe_reason(self) -> None:
        event = WorkerEvent(
            event=WorkerEventKind.JOB_FAILED,
            timestamp=utc_timestamp(),
            pool="source_ingestion",
            worker_id="source_ingestion-0-x",
            capability_id="source_ingestion.process",
            human_title="book.pdf",
            error_code="PDF_NO_EXTRACTABLE_TEXT",
        )
        line = format_terminal_message(event)
        self.assertIn("Source 'book.pdf' MISLUKT", line)
        self.assertIn("PDF_NO_EXTRACTABLE_TEXT", line)

    def test_dataset_progress(self) -> None:
        event = WorkerEvent(
            event=WorkerEventKind.JOB_PROGRESS,
            timestamp=utc_timestamp(),
            pool="dataset",
            worker_id="dataset-0-x",
            capability_id="dataset.process",
            human_title="python-code",
            progress_current=10000,
            progress_total=48212,
        )
        line = format_terminal_message(event)
        self.assertIn("Dataset 'python-code' 10000/48212", line)

    def test_job_queued_is_control_plane_prefix(self) -> None:
        event = WorkerEvent(
            event=WorkerEventKind.JOB_QUEUED,
            timestamp=utc_timestamp(),
            pool="research",
            job_id="deadbeef01",
            capability_id="research.advance",
            human_title="Neuromorphic computing",
        )
        line = format_terminal_message(event)
        self.assertTrue(line.startswith("[JOB]"))
        self.assertIn("ingepland", line)
        self.assertNotIn("[WORKER]", line)

    def test_pool_started(self) -> None:
        event = WorkerEvent(
            event=WorkerEventKind.POOL_STARTED,
            timestamp=utc_timestamp(),
            pool="research",
            extra={"worker_count": 2},
        )
        line = format_terminal_message(event)
        self.assertEqual(line, "[WORKER] research pool gestart — 2 workers")

    def test_worker_restart(self) -> None:
        event = WorkerEvent(
            event=WorkerEventKind.WORKER_RESTARTED,
            timestamp=utc_timestamp(),
            pool="research",
            worker_id="research-2",
            attempt=1,
        )
        line = format_terminal_message(event)
        self.assertIn("herstart", line)
        self.assertIn("poging 1", line)

    def test_secrets_not_in_message(self) -> None:
        emitter = WorkerEventEmitter(stream=io.StringIO(), enable_structured=False)
        line = emitter.job_started(
            job_id="j1",
            capability_id="research.advance",
            pool="research",
            worker_id="research-0-x",
            human_title="Safe",
            metadata={"api_key": "sk-LIVE-SECRET", "topic": "Safe"},
            arguments={"token": "Bearer XYZ", "password": "hunter2"},
        )
        self.assertNotIn("sk-LIVE-SECRET", line)
        self.assertNotIn("Bearer XYZ", line)
        self.assertNotIn("hunter2", line)
        self.assertIn("Safe", line)

    def test_newlines_in_title_sanitized(self) -> None:
        line = format_terminal_message(
            WorkerEvent(
                event=WorkerEventKind.JOB_STARTED,
                timestamp=utc_timestamp(),
                pool="research",
                worker_id="research-0-x",
                capability_id="research.advance",
                human_title="Line1\nLine2",
            )
        )
        self.assertNotIn("\n", line)
        self.assertIn("Line1 Line2", line)


class EmitterConcurrencyTests(unittest.TestCase):
    def test_concurrent_emits_produce_atomic_lines(self) -> None:
        buf = io.StringIO()
        emitter = WorkerEventEmitter(stream=buf, enable_structured=False)

        def _run(i: int) -> None:
            for j in range(20):
                emitter.job_completed(
                    job_id=f"job-{i}-{j}",
                    capability_id="research.advance",
                    pool="research",
                    worker_id=f"research-{i % 3}-x",
                    human_title=f"Topic-{i}-{j}",
                    duration_ms=1000 + i,
                )

        threads = [threading.Thread(target=_run, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        text = buf.getvalue()
        lines = [ln for ln in text.splitlines() if ln]
        self.assertEqual(len(lines), 80)
        for line in lines:
            self.assertTrue(line.startswith("[WORKER:"), line)
            self.assertIn("voltooid", line)
            # No obvious mid-line interleaving of another worker prefix.
            self.assertEqual(line.count("[WORKER:"), 1, line)


class EmitterLifecycleHelpersTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_worker_event_emitter(None)

    def test_progress_rate_limited(self) -> None:
        buf = io.StringIO()
        emitter = WorkerEventEmitter(stream=buf, enable_structured=False)
        emitter.progress_min_interval_s = 60.0
        first = emitter.job_progress(
            job_id="j1",
            capability_id="embedding.batch",
            progress_current=1,
            progress_total=100,
            human_title="batch",
            pool="embedding",
            worker_id="embedding-0-x",
        )
        second = emitter.job_progress(
            job_id="j1",
            capability_id="embedding.batch",
            progress_current=2,
            progress_total=100,
            human_title="batch",
            pool="embedding",
            worker_id="embedding-0-x",
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)


class LoopWiringSmokeTests(unittest.TestCase):
    def test_loop_imports_emitter(self) -> None:
        from Data.modules.workers import loop

        self.assertTrue(hasattr(loop, "get_worker_event_emitter"))


if __name__ == "__main__":
    unittest.main()
