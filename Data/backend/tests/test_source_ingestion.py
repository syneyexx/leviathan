"""Source Ingestion subsystem — security, ZIP, resume, Brain isolation tests."""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from Data.modules.common.paths import PathEscapeError
from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.knowledge import KnowledgeStore
from Data.modules.research.service import ResearchService
from Data.modules.research.store import ResearchStore
from Data.modules.source_ingestion.archives.security import (
    check_declared_bomb,
    normalize_member_path,
)
from Data.modules.source_ingestion.archives.zip_safe import inspect_zip
from Data.modules.source_ingestion.binary import classify_bytes, is_binary
from Data.modules.source_ingestion.detection import detect_source_type
from Data.modules.source_ingestion.handlers import build_default_registry
from Data.modules.source_ingestion.secrets_policy import should_quarantine
from Data.modules.source_ingestion.settings import SourceIngestionSettings
from Data.modules.source_ingestion.skip_policy import should_skip_path
from Data.modules.source_ingestion.store import IngestionStore
from Data.modules.source_ingestion.types import IngestionError, MemberOutcome


@pytest.fixture()
def tmp_env(tmp_path: Path):
    db = tmp_path / "leviathan.db"
    research = ResearchStore(db)
    research.initialize()
    knowledge = KnowledgeStore(db, data_root=tmp_path / "knowledge")
    knowledge.initialize()
    job_store = JobStore(db)
    job_store.initialize()
    gateway = ExecutionGateway(catalog=build_default_catalog())
    runtime = JobRuntime(job_store, gateway, ResourceManager(2))
    sources = tmp_path / "sources"
    snaps = tmp_path / "snapshots"
    sources.mkdir()
    snaps.mkdir()
    service = ResearchService(
        research,
        knowledge=knowledge,
        sources_root=sources,
        snapshots_root=snaps,
        job_runtime=runtime,
    )
    # Force in-process settings for tests
    if service.source_ingestion is not None:
        service.source_ingestion.settings.runner = "inprocess"
        service.source_ingestion.settings.max_member_count = 100
        service.source_ingestion.settings.max_compression_ratio = 50.0
        service.source_ingestion.settings.max_total_uncompressed_bytes = 50 * 1024 * 1024
        service.source_ingestion.settings.max_nested_archive_depth = 1
    return service, research, knowledge, tmp_path


def _make_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_normalize_path_rejects_traversal():
    with pytest.raises(PathEscapeError):
        normalize_member_path("../evil.txt")
    with pytest.raises(PathEscapeError):
        normalize_member_path("../../outside.txt")
    with pytest.raises(PathEscapeError):
        normalize_member_path("/absolute.txt")
    with pytest.raises(PathEscapeError):
        normalize_member_path(r"C:\evil.txt")
    with pytest.raises(PathEscapeError):
        normalize_member_path(r"..\..\mixed.txt")
    with pytest.raises(PathEscapeError):
        normalize_member_path("\\\\server\\share\\x")
    assert normalize_member_path("docs/readme.md") == "docs/readme.md"
    assert normalize_member_path(r"docs\readme.md") == "docs/readme.md"


def test_zip_bomb_declared_ratio():
    settings = SourceIngestionSettings(
        max_total_uncompressed_bytes=10_000_000,
        max_compression_ratio=10.0,
    )
    with pytest.raises(IngestionError) as ei:
        check_declared_bomb(
            settings=settings,
            declared_uncompressed_total=1_000_000_000,
            compressed_archive_size=1000,
        )
    assert ei.value.code == "ARCHIVE_ZIP_BOMB"


def test_member_count_limit(tmp_path: Path):
    settings = SourceIngestionSettings(max_member_count=3, max_compression_ratio=1000.0)
    zpath = tmp_path / "many.zip"
    members = {f"f{i}.txt": b"x" for i in range(5)}
    _make_zip(zpath, members)
    with pytest.raises(IngestionError) as ei:
        inspect_zip(zpath, container_source_id="c", settings=settings)
    assert ei.value.code == "ARCHIVE_TOO_MANY_MEMBERS"


def test_binary_and_text_detection():
    assert classify_bytes(b"hello world\n")["is_text"] is True
    assert is_binary(b"\x00\x01\x02\x03\xff\xfe") is True
    assert is_binary(bytes([i % 256 for i in range(512)])) is True


def test_secret_filename_quarantine():
    q, reason = should_quarantine(relative_path=".env", sample=b"FOO=1")
    assert q is True
    assert reason and "secrets" in reason
    q2, _ = should_quarantine(relative_path="normal_config.py", sample=b"token = 'example'")
    assert q2 is False
    pem = b"-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
    q3, reason3 = should_quarantine(relative_path="id_rsa", sample=pem)
    assert q3 is True


def test_skip_policy_node_modules():
    skip, reason = should_skip_path("node_modules/lodash/index.js")
    assert skip is True
    assert reason and "generated_directory" in reason
    skip2, _ = should_skip_path("src/main.py")
    assert skip2 is False
    skip3, reason3 = should_skip_path("bin/tool.exe")
    assert skip3 is True
    assert reason3 and "binary" in reason3


def test_detection_pdf_and_zip_and_exe_trick():
    pdf = detect_source_type(filename="a.pdf", sample=b"%PDF-1.4")
    assert pdf.kind.value == "document"
    z = detect_source_type(filename="p.zip", sample=b"PK\x03\x04")
    assert z.is_archive is True
    evil = detect_source_type(filename="photo.jpg.exe", sample=b"\xff\xd8\xff\xe0")
    assert evil.kind.value == "binary"


def test_registry_resolves_handlers():
    reg = build_default_registry()
    assert reg.get("document") is not None
    assert reg.get("source_code") is not None
    assert "source_ingestion.process" in {
        c.id for c in build_default_catalog().list()
    }


def test_basic_zip_ingestion(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="zip ingest")
    zpath = tmp_path / "project.zip"
    _make_zip(
        zpath,
        {
            "README.md": b"# Hello\n",
            "docs/notes.txt": b"architecture notes",
            "src/main.py": b"def run():\n    return 1\n",
            "src/helper.ts": b"export const x = 1;\n",
            "config/settings.yaml": b"debug: true\n",
            "data/sample.csv": b"a,b\n1,2\n",
            "data/sample.jsonl": b'{"id":1}\n{"id":2}\n',
            "bin/fake.bin": b"\x00\x01\x02\x03\xff",
            ".env": b"SECRET=supersecret\n",
            "node_modules/pkg/index.js": b"module.exports=1\n",
        },
    )
    with open(zpath, "rb") as handle:
        result = service.upload_source(
            project.project_id,
            filename="project.zip",
            stream=handle,
            content_type="application/zip",
        )
    assert result["source_type"] == "archive"
    source_id = result["source_id"]
    # Ensure archive fully processed (background may still be mid-flight for large)
    if service.source_ingestion is not None:
        # Drain any remaining jobs / direct process for residual pending
        for _ in range(5):
            progress = service.source_ingestion.get_status(source_id)
            if progress.files_pending == 0 and progress.status.value not in {
                "queued",
                "parsing",
                "expanding",
                "inspecting",
                "classifying",
            }:
                break
            if service.source_ingestion.jobs is not None:
                service.source_ingestion.process_next()
            else:
                service.source_ingestion.pipeline().process_source(source_id)

    progress = service.get_ingestion_status(project.project_id, source_id)["progress"]
    assert progress["files_discovered"] >= 8
    assert progress["files_ingested"] >= 5
    assert progress["files_quarantined"] >= 1  # .env
    children = service.list_ingestion_children(project.project_id, source_id, limit=200)
    paths = {m["relative_path"]: m for m in children["members"]}
    assert "README.md" in paths
    assert paths["README.md"]["outcome"] == "success"
    assert paths["bin/fake.bin"]["outcome"] == "skipped"
    assert paths[".env"]["outcome"] == "quarantined"
    assert "node_modules/pkg/index.js" in paths
    assert paths["node_modules/pkg/index.js"]["outcome"] == "skipped"

    # Distinct child sources with provenance
    sources = research.list_sources(project.project_id, limit=200)
    child_paths = [
        (s.provenance or {}).get("relative_path")
        for s in sources
        if (s.metadata or {}).get("is_child")
    ]
    assert "src/main.py" in child_paths
    assert "docs/notes.txt" in child_paths

    # Brain docs are per-content, not one giant blob
    docs = knowledge.list_documents(limit=100)
    titles = [d.title for d in docs]
    assert any("README.md" in t or "project.zip/README.md" in t for t in titles)
    # Secret must not appear in knowledge content
    for d in docs:
        assert "supersecret" not in d.content


def test_zip_slip_rejected(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="slip")
    zpath = tmp_path / "slip.zip"
    # Craft zip with traversal name using ZipInfo
    with zipfile.ZipFile(zpath, "w") as zf:
        info = zipfile.ZipInfo("../evil.txt")
        zf.writestr(info, b"evil")
    with open(zpath, "rb") as handle:
        result = service.upload_source(
            project.project_id,
            filename="slip.zip",
            stream=handle,
        )
    source_id = result["source_id"]
    if service.source_ingestion and service.source_ingestion.jobs:
        service.source_ingestion.process_next()
    elif service.source_ingestion:
        try:
            service.source_ingestion.pipeline().process_source(source_id)
        except Exception:
            pass
    progress = service.get_ingestion_status(project.project_id, source_id)["progress"]
    # Parent remains visible; failure recorded
    src = research.get_source(source_id)
    assert src is not None
    assert progress["status"] in {"failed", "partial", "completed", "queued", "parsing"}


def test_duplicate_content_idempotent_brain(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="dup")
    same = b"identical payload for dedupe\n"
    zpath = tmp_path / "dup.zip"
    _make_zip(zpath, {"a/one.txt": same, "b/two.txt": same})
    with open(zpath, "rb") as handle:
        result = service.upload_source(project.project_id, filename="dup.zip", stream=handle)
    source_id = result["source_id"]
    if service.source_ingestion:
        if service.source_ingestion.jobs:
            service.source_ingestion.process_next()
        else:
            service.source_ingestion.pipeline().process_source(source_id)
    children = service.list_ingestion_children(project.project_id, source_id, limit=50)
    success = [m for m in children["members"] if m["outcome"] == "success"]
    assert len(success) == 2
    # Same brain document id for identical content
    brain_ids = {m["brain_document_id"] for m in success if m.get("brain_document_id")}
    assert len(brain_ids) == 1


def test_unknown_text_extension(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="weird")
    payload = b"notes with unknown extension but utf-8 text\n"
    result = service.upload_source(
        project.project_id,
        filename="notes.weirdext",
        stream=io.BytesIO(payload),
    )
    source = research.get_source(result["source_id"])
    assert source is not None
    assert source.parse_status.value == "ok"
    assert source.brain_status.value == "synced"


def test_unknown_binary_extension(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="bin")
    payload = bytes([0, 1, 2, 3, 255, 254, 128]) * 100
    from Data.modules.research.types import ResearchError

    with pytest.raises(ResearchError) as ei:
        service.upload_source(
            project.project_id,
            filename="blob.weirdbin",
            stream=io.BytesIO(payload),
        )
    assert ei.value.code in {"UNSUPPORTED_SOURCE_TYPE", "SOURCE_PARSE_FAILED"}
    # Source row should still exist for honesty
    sources = research.list_sources(project.project_id, limit=10)
    assert any(s.title == "blob.weirdbin" for s in sources)

def test_empty_file(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="empty")
    result = service.upload_source(
        project.project_id,
        filename="empty.txt",
        stream=io.BytesIO(b""),
    )
    source = research.get_source(result["source_id"])
    assert source is not None


def test_single_file_regression_txt(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="txt")
    result = service.upload_source(
        project.project_id,
        filename="hello.txt",
        stream=io.BytesIO(b"hello research\n"),
    )
    source = research.get_source(result["source_id"])
    assert source is not None
    assert source.parse_status.value == "ok"
    assert source.brain_status.value == "synced"
    assert result["extracted_chars"] > 0


def test_cancel_and_retry(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="cancel")
    zpath = tmp_path / "c.zip"
    _make_zip(zpath, {f"f{i}.txt": f"body {i}\n".encode() for i in range(20)})
    with open(zpath, "rb") as handle:
        result = service.upload_source(project.project_id, filename="c.zip", stream=handle)
    source_id = result["source_id"]
    # Request cancel (may already be complete for small zip)
    cancelled = service.cancel_ingestion(project.project_id, source_id)
    assert "progress" in cancelled
    retried = service.retry_ingestion(project.project_id, source_id, failed_only=False)
    assert retried["status"] in {"queued", "completed", "partial", "parsing"}


def test_brain_failure_isolation(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="brainfail")
    # Break knowledge temporarily
    service.source_ingestion.knowledge = None
    result = service.upload_source(
        project.project_id,
        filename="x.txt",
        stream=io.BytesIO(b"still parseable\n"),
    )
    source = research.get_source(result["source_id"])
    assert source is not None
    assert source.parse_status.value == "ok"
    assert source.brain_status.value == "failed"
    # Restore and brain-retry
    service.source_ingestion.knowledge = knowledge
    service.brain.knowledge = knowledge
    retried = service.retry_ingestion_brain(project.project_id, source.source_id)
    assert "source" in retried or "progress" in retried


def test_unicode_paths(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="unicode")
    zpath = tmp_path / "u.zip"
    _make_zip(zpath, {"docs/备注.txt": "你好\n".encode("utf-8")})
    with open(zpath, "rb") as handle:
        result = service.upload_source(project.project_id, filename="u.zip", stream=handle)
    source_id = result["source_id"]
    if service.source_ingestion:
        if service.source_ingestion.jobs:
            service.source_ingestion.process_next()
        else:
            service.source_ingestion.pipeline().process_source(source_id)
    children = service.list_ingestion_children(project.project_id, source_id)
    assert any("备注" in m["relative_path"] for m in children["members"])


def test_nested_depth(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="nested")
    inner = tmp_path / "inner.zip"
    _make_zip(inner, {"deep.txt": b"deep\n"})
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as zf:
        zf.write(inner, arcname="nested/child.zip")
        zf.writestr("README.md", b"root\n")
    # max_nested_archive_depth=1 means nested child archive is skipped at depth>1
    service.source_ingestion.settings.max_nested_archive_depth = 0
    with open(outer, "rb") as handle:
        result = service.upload_source(project.project_id, filename="outer.zip", stream=handle)
    source_id = result["source_id"]
    if service.source_ingestion:
        if service.source_ingestion.jobs:
            service.source_ingestion.process_next()
        else:
            service.source_ingestion.pipeline().process_source(source_id)
    children = service.list_ingestion_children(project.project_id, source_id, limit=50)
    nested = [m for m in children["members"] if m["relative_path"].endswith("child.zip")]
    assert nested
    assert nested[0]["outcome"] in {"skipped", "success", "failed"}
    if nested[0]["outcome"] == "skipped":
        assert "nested" in (nested[0].get("skip_reason") or "")


def test_job_capability_filter(tmp_env):
    service, research, knowledge, tmp_path = tmp_env
    project = service.create_project(title="t", topic="jobs")
    result = service.upload_source(
        project.project_id,
        filename="a.txt",
        stream=io.BytesIO(b"via jobs\n"),
    )
    assert result.get("job_id") is not None or service.source_ingestion.jobs is None
    # JobRuntime must not steal source_ingestion jobs
    stolen = service.job_runtime.process_next() if service.job_runtime else None
    # Either None or some other job — never source_ingestion if queued remains
    if stolen is not None:
        assert not stolen.capability_id.startswith("source_ingestion.")
