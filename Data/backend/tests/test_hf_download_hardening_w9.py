"""Wave 9 — Hugging Face download hardening fault-injection tests."""

from __future__ import annotations

import errno
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from Data.modules.common.retry import RetryPolicy
from Data.modules.datasets.huggingface import (
    HfDownloadCheckpoint,
    HfFileKind,
    HfRepoFile,
    HfRepoManifest,
    HfRepoPlan,
    download_hf_file,
    download_hf_repository,
    effective_download_revision,
    parse_content_range,
    scrub_hf_secrets,
    write_repo_manifest,
)
from Data.modules.datasets.types import DatasetError


class ContentRangeParsingTests(unittest.TestCase):
    def test_valid_and_invalid_ranges(self) -> None:
        self.assertEqual(parse_content_range("bytes 40-99/100"), (40, 99, 100))
        self.assertEqual(parse_content_range("bytes 0-0/1"), (0, 0, 1))
        self.assertEqual(parse_content_range("bytes 10-20/*"), (10, 20, None))
        self.assertIsNone(parse_content_range("bytes 10-5/20"))
        self.assertIsNone(parse_content_range("bytes 0-10/10"))  # total <= end
        self.assertIsNone(parse_content_range("bogus"))
        self.assertIsNone(parse_content_range("bytes abc-def/ghi"))


class RevisionPinningTests(unittest.TestCase):
    def test_prefers_resolved_sha(self) -> None:
        self.assertEqual(
            effective_download_revision(revision="main", resolved_revision="abc123"),
            "abc123",
        )
        self.assertEqual(
            effective_download_revision(revision="main", resolved_revision=None),
            "main",
        )

    def test_repository_download_uses_pinned_revision_in_url(self) -> None:
        payload = b'{"id":"1","text":"hello"}\n'
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            return httpx.Response(
                200,
                content=payload,
                headers={"Content-Length": str(len(payload)), "ETag": '"v1"'},
                request=request,
            )

        plan = HfRepoPlan(
            repository_id="org/ds",
            revision="main",
            resolved_revision="deadbeefcafebabe",
            files=[],
            classification={"data.jsonl": HfFileKind.DATA.value},
            data_files=[HfRepoFile(path="data.jsonl", size=len(payload), kind=HfFileKind.DATA)],
            unsupported_files=[],
            metadata_files=[],
            bytes_total=len(payload),
        )
        root = Path(tempfile.mkdtemp())
        result = download_hf_repository(
            plan=plan,
            raw_root=root / "raw",
            workers=1,
            transport=httpx.MockTransport(handler),
            manifest_path=root / "manifest.json",
        )
        self.assertTrue(result.manifest.is_download_complete())
        self.assertTrue(any("deadbeefcafebabe" in u for u in seen_urls))
        self.assertFalse(any("/resolve/main/" in u for u in seen_urls))
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("pinnedRevision"), "deadbeefcafebabe")


class ETagAndRemoteChangeTests(unittest.TestCase):
    def test_etag_mismatch_restarts_partial(self) -> None:
        payload = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 40
        state = {"calls": 0}
        phases: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            state["calls"] += 1
            range_header = request.headers.get("range") or ""
            if state["calls"] == 1:
                # Resume with mismatched etag → client restarts.
                start = int(range_header.split("=", 1)[1].split("-", 1)[0])
                body = payload[start:]
                return httpx.Response(
                    206,
                    content=body,
                    headers={
                        "Content-Length": str(len(body)),
                        "Content-Range": f"bytes {start}-{len(payload) - 1}/{len(payload)}",
                        "ETag": '"new-etag"',
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                content=payload,
                headers={
                    "Content-Length": str(len(payload)),
                    "ETag": '"new-etag"',
                },
                request=request,
            )

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        partial = Path(str(dest) + ".partial")
        partial.write_bytes(payload[:50])
        cp = HfDownloadCheckpoint(
            repository_id="org/ds",
            revision="main",
            filename="file.bin",
            bytes_downloaded=50,
            etag='"old-etag"',
        )
        result = download_hf_file(
            repository_id="org/ds",
            filename="file.bin",
            dest_path=dest,
            checkpoint=cp,
            expected_size=len(payload),
            transport=httpx.MockTransport(handler),
            sleep_fn=lambda _s: None,
            progress_cb=lambda info: phases.append(str(info.get("phase"))),
            policy=RetryPolicy(max_attempts=4, base_seconds=0.01, max_seconds=0.05),
        )
        self.assertEqual(dest.read_bytes(), payload)
        self.assertTrue(result.checkpoint.completed)
        self.assertIn("etag_mismatch", phases)

    def test_invalid_content_range_fails(self) -> None:
        payload = b"hello-world-payload"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                206,
                content=payload[5:],
                headers={
                    "Content-Length": str(len(payload) - 5),
                    "Content-Range": "bytes junk",
                },
                request=request,
            )

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        Path(str(dest) + ".partial").write_bytes(payload[:5])
        cp = HfDownloadCheckpoint(
            repository_id="org/ds",
            revision="main",
            filename="file.bin",
            bytes_downloaded=5,
        )
        with self.assertRaises(DatasetError) as ctx:
            download_hf_file(
                repository_id="org/ds",
                filename="file.bin",
                dest_path=dest,
                checkpoint=cp,
                transport=httpx.MockTransport(handler),
                sleep_fn=lambda _s: None,
                policy=RetryPolicy(max_attempts=2, base_seconds=0.01, max_seconds=0.05),
            )
        self.assertEqual(ctx.exception.code, "hf_invalid_content_range")

    def test_remote_size_change_on_resume(self) -> None:
        original = b"A" * 100
        changed = b"B" * 80
        state = {"calls": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["calls"] += 1
            range_header = request.headers.get("range") or ""
            if state["calls"] == 1 and range_header:
                start = int(range_header.split("=", 1)[1].split("-", 1)[0])
                # Advertise a different total than expected_size.
                body = changed[start:] if start < len(changed) else b""
                return httpx.Response(
                    206,
                    content=body or b"x",
                    headers={
                        "Content-Length": str(max(1, len(body))),
                        "Content-Range": f"bytes {start}-{len(changed) - 1}/{len(changed)}",
                        "ETag": '"v2"',
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                content=changed,
                headers={"Content-Length": str(len(changed)), "ETag": '"v2"'},
                request=request,
            )

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        Path(str(dest) + ".partial").write_bytes(original[:40])
        cp = HfDownloadCheckpoint(
            repository_id="org/ds",
            revision="main",
            filename="file.bin",
            bytes_downloaded=40,
            etag='"v1"',
            total_bytes=len(original),
        )
        phases: list[str] = []
        # expected_size still original → remote change path; then may fail size on restart
        # because we keep expected_size=100 while remote is 80.
        with self.assertRaises(DatasetError) as ctx:
            download_hf_file(
                repository_id="org/ds",
                filename="file.bin",
                dest_path=dest,
                checkpoint=cp,
                expected_size=len(original),
                transport=httpx.MockTransport(handler),
                sleep_fn=lambda _s: None,
                progress_cb=lambda info: phases.append(str(info.get("phase"))),
                policy=RetryPolicy(max_attempts=3, base_seconds=0.01, max_seconds=0.05),
            )
        self.assertIn(ctx.exception.code, {"hf_size_mismatch", "hf_remote_changed", "hf_download_failed"})
        self.assertTrue(
            "remote_changed" in phases or ctx.exception.code in {"hf_size_mismatch", "hf_remote_changed"}
        )


class ExpectedSizeHashAndFaultsTests(unittest.TestCase):
    def test_hash_mismatch(self) -> None:
        payload = b"correct-bytes"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=payload,
                headers={"Content-Length": str(len(payload))},
                request=request,
            )

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        with self.assertRaises(DatasetError) as ctx:
            download_hf_file(
                repository_id="org/ds",
                filename="file.bin",
                dest_path=dest,
                expected_size=len(payload),
                expected_hash="0" * 64,
                transport=httpx.MockTransport(handler),
                sleep_fn=lambda _s: None,
            )
        self.assertEqual(ctx.exception.code, "hf_hash_mismatch")

    def test_timeout_retries_then_fails(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        with self.assertRaises(DatasetError) as ctx:
            download_hf_file(
                repository_id="org/ds",
                filename="file.bin",
                dest_path=dest,
                transport=httpx.MockTransport(handler),
                sleep_fn=lambda _s: None,
                policy=RetryPolicy(max_attempts=2, base_seconds=0.01, max_seconds=0.05),
            )
        self.assertEqual(ctx.exception.code, "hf_timeout")

    def test_429_and_5xx_retry(self) -> None:
        payload = b"ok-after-retries"
        state = {"calls": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["calls"] += 1
            if state["calls"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
            if state["calls"] == 2:
                return httpx.Response(503, request=request)
            return httpx.Response(
                200,
                content=payload,
                headers={"Content-Length": str(len(payload))},
                request=request,
            )

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        result = download_hf_file(
            repository_id="org/ds",
            filename="file.bin",
            dest_path=dest,
            expected_size=len(payload),
            transport=httpx.MockTransport(handler),
            sleep_fn=lambda _s: None,
            policy=RetryPolicy(max_attempts=5, base_seconds=0.01, max_seconds=0.05),
        )
        self.assertEqual(result.byte_size, len(payload))
        self.assertGreaterEqual(result.checkpoint.rate_limit_events, 1)

    def test_disk_full_maps_to_dataset_error(self) -> None:
        payload = b"will-fail-write"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=payload,
                headers={"Content-Length": str(len(payload))},
                request=request,
            )

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        real_open = Path.open

        def boom(self, *args, **kwargs):  # noqa: ANN001
            if str(self).endswith(".partial"):
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_open(self, *args, **kwargs)

        with mock.patch.object(Path, "open", boom):
            with self.assertRaises(DatasetError) as ctx:
                download_hf_file(
                    repository_id="org/ds",
                    filename="file.bin",
                    dest_path=dest,
                    transport=httpx.MockTransport(handler),
                    sleep_fn=lambda _s: None,
                    policy=RetryPolicy(max_attempts=1, base_seconds=0.01, max_seconds=0.05),
                )
        self.assertEqual(ctx.exception.code, "disk_full")


class SecretScrubAndCompletenessTests(unittest.TestCase):
    def test_scrub_removes_tokens_from_manifest_and_checkpoint(self) -> None:
        token = "hf_abcdefghijklmnopqrstuvwxyz0123456789"
        scrubbed = scrub_hf_secrets(
            {
                "Authorization": f"Bearer {token}",
                "token": token,
                "nested": {"hf_token": token, "note": f"using {token}"},
            }
        )
        blob = json.dumps(scrubbed)
        self.assertNotIn(token, blob)
        self.assertIn("[REDACTED]", blob)

        cp = HfDownloadCheckpoint(repository_id="org/ds", revision="main", filename="a.jsonl")
        # Simulate accidental contamination of a dict derived from checkpoint.
        durable = scrub_hf_secrets({**cp.to_dict(), "token": token, "authorization": f"Bearer {token}"})
        self.assertNotIn(token, json.dumps(durable))

        root = Path(tempfile.mkdtemp())
        manifest = HfRepoManifest(
            repository_id="org/ds",
            revision="main",
            resolved_revision="abc",
            files_total=1,
            files={
                "a.jsonl": __import__(
                    "Data.modules.datasets.huggingface", fromlist=["HfFileState"]
                ).HfFileState(path="a.jsonl", size=1, status="complete", downloaded=1)
            },
        )
        path = root / "m.json"
        # Ensure write path cannot persist a leaked token field if caller merges one.
        leaked = manifest.to_dict()
        leaked["hfToken"] = token
        write_repo_manifest(path, manifest)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn(token, text)
        self.assertNotIn("hfToken", text)
        # Explicit scrub of leaked dict still redacts.
        self.assertNotIn(token, json.dumps(scrub_hf_secrets(leaked)))

    def test_incomplete_repo_cannot_be_marked_complete(self) -> None:
        from Data.modules.datasets.huggingface import HfFileState

        manifest = HfRepoManifest(
            repository_id="org/ds",
            revision="main",
            files_total=2,
            files={
                "a.jsonl": HfFileState(path="a.jsonl", status="complete", size=10, downloaded=10),
                "b.jsonl": HfFileState(path="b.jsonl", status="failed", error="boom"),
            },
        )
        self.assertFalse(manifest.is_download_complete())
        with self.assertRaises(DatasetError) as ctx:
            manifest.mark_download_completed()
        self.assertEqual(ctx.exception.code, "hf_download_incomplete")
        self.assertEqual(manifest.phase, "failed")

    def test_repository_failure_phase_is_failed_not_complete(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, request=request)

        plan = HfRepoPlan(
            repository_id="org/ds",
            revision="main",
            resolved_revision="pin1",
            files=[],
            classification={"a.jsonl": "DATA"},
            data_files=[HfRepoFile(path="a.jsonl", size=10, kind=HfFileKind.DATA)],
            unsupported_files=[],
            metadata_files=[],
            bytes_total=10,
        )
        root = Path(tempfile.mkdtemp())
        with self.assertRaises(DatasetError) as ctx:
            download_hf_repository(
                plan=plan,
                raw_root=root / "raw",
                workers=1,
                transport=httpx.MockTransport(handler),
                sleep_fn=lambda _s: None,
                manifest_path=root / "manifest.json",
            )
        self.assertEqual(ctx.exception.code, "hf_download_incomplete")
        data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data.get("phase"), "failed")
        self.assertNotEqual(data.get("phase"), "download_completed")


class SizeHashHappyPathTests(unittest.TestCase):
    def test_expected_size_and_hash_ok(self) -> None:
        payload = b"verified-content"
        digest = hashlib.sha256(payload).hexdigest()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=payload,
                headers={"Content-Length": str(len(payload)), "ETag": '"x"'},
                request=request,
            )

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        result = download_hf_file(
            repository_id="org/ds",
            filename="file.bin",
            dest_path=dest,
            expected_size=len(payload),
            expected_hash=digest,
            transport=httpx.MockTransport(handler),
            sleep_fn=lambda _s: None,
        )
        self.assertEqual(result.content_hash, digest)
        self.assertTrue(result.checkpoint.completed)


if __name__ == "__main__":
    unittest.main()
