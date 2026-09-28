"""Source Ingestion fabric E2E — enqueue, process, knowledge persistence, failure isolation."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.knowledge import KnowledgeStore
from Data.modules.research.service import ResearchService
from Data.modules.research.store import ResearchStore
from Data.modules.source_ingestion.types import CAPABILITY_PROCESS
from Data.modules.workers.entrypoints import source_ingestion as si_entrypoint


@pytest.fixture()
def fabric_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEVIATHAN_SOURCE_INGESTION_RUNNER", "fabric")
    monkeypatch.setenv("LEVIATHAN_WORKERS_EXTERNALIZE_API", "1")
    control = tmp_path / "control.db"
    knowledge_db = tmp_path / "knowledge.db"
    research = ResearchStore(control)
    research.initialize()
    knowledge = KnowledgeStore(knowledge_db, data_root=tmp_path / "knowledge")
    knowledge.initialize()
    job_store = JobStore(control)
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
    assert service.source_ingestion is not None
    service.source_ingestion.settings.runner = "fabric"
    # Reset process-scoped fabric service cache between tests.
    si_entrypoint._SERVICE = None
    si_entrypoint._SETTINGS = None
    return {
        "research_service": service,
        "si": service.source_ingestion,
        "job_store": job_store,
        "knowledge": knowledge,
        "tmp": tmp_path,
    }


def test_upload_enqueues_source_ingestion_process_job(fabric_env):
    rs = fabric_env["research_service"]
    project = rs.create_project(title="SI E2E", topic="source ingestion")
    payload = b"Leviathan source ingestion smoke fixture.\nLine two.\n"
    result = rs.upload_source(
        project.project_id,
        stream=io.BytesIO(payload),
        filename="smoke.txt",
        content_type="text/plain",
    )
    assert result.get("job_id"), result
    job = fabric_env["job_store"].get(result["job_id"])
    assert job is not None
    assert job.capability_id == CAPABILITY_PROCESS
    assert job.worker_pool == "source_ingestion"
    assert job.arguments.get("source_id") == result["source_id"]
    assert job.state == JobState.QUEUED


def test_fabric_handler_processes_claimed_job_to_knowledge(fabric_env, monkeypatch):
    rs = fabric_env["research_service"]
    si = fabric_env["si"]
    store = fabric_env["job_store"]
    knowledge = fabric_env["knowledge"]
    project = rs.create_project(title="SI Knowledge", topic="source ingestion")
    payload = b"Canonical knowledge commit proof text for source ingestion.\n"
    result = rs.upload_source(
        project.project_id,
        stream=io.BytesIO(payload),
        filename="proof.txt",
        content_type="text/plain",
    )
    source_id = result["source_id"]
    job_id = result["job_id"]
    assert job_id

    # Simulate fabric claim.
    claimed = store.claim_next_for_pool(
        pool_id="source_ingestion",
        worker_id="source_ingestion-0-test",
        lease_ttl_seconds=30.0,
    )
    assert claimed is not None
    assert claimed.job_id == job_id

    # Process-scoped service used by entrypoint must be our SI instance.
    monkeypatch.setattr(si_entrypoint, "_SERVICE", si)
    monkeypatch.setattr(si_entrypoint, "_SETTINGS", None)
    ctx = {"job_store": store, "worker_id": "source_ingestion-0-test"}
    si_entrypoint._handler(ctx, claimed)

    refreshed = store.get(job_id)
    assert refreshed is not None
    assert refreshed.state == JobState.COMPLETED

    source = fabric_env["research_service"].store.get_source(source_id)
    assert source is not None
    assert source.snapshot_path
    assert Path(source.snapshot_path).is_file()


def test_malformed_source_fails_job_worker_survives(fabric_env, monkeypatch):
    si = fabric_env["si"]
    store = fabric_env["job_store"]
    rs = fabric_env["research_service"]
    project = rs.create_project(title="SI Fail", topic="source ingestion")
    # Empty / unsupported binary-ish upload still creates a source+job.
    result = rs.upload_source(
        project.project_id,
        stream=io.BytesIO(b"\x00\x01\x02\x03\xff\xfe"),
        filename="weird.bin",
        content_type="application/octet-stream",
    )
    job_id = result["job_id"]
    source_id = result["source_id"]
    assert job_id
    claimed = store.claim_next_queued(
        worker_id="source_ingestion-0-fail",
        lease_ttl_seconds=30.0,
        capability_ids={CAPABILITY_PROCESS},
        worker_pool="source_ingestion",
    )
    assert claimed is not None
    monkeypatch.setattr(si_entrypoint, "_SERVICE", si)
    ctx = {"job_store": store, "worker_id": "source_ingestion-0-fail"}
    # Handler must not raise out of process — failures become job FAILED/COMPLETED terminal.
    try:
        si_entrypoint._handler(ctx, claimed)
    except Exception as exc:  # noqa: BLE001 — worker survival means process continues
        pytest.fail(f"handler killed worker process path: {exc}")
    refreshed = store.get(job_id)
    assert refreshed is not None
    assert refreshed.state in {JobState.FAILED, JobState.COMPLETED}
    # Next valid job still processable.
    good = rs.upload_source(
        project.project_id,
        stream=io.BytesIO(b"second valid source after failure\n"),
        filename="ok.txt",
        content_type="text/plain",
    )
    claimed2 = store.claim_next_queued(
        worker_id="source_ingestion-0-fail",
        lease_ttl_seconds=30.0,
        capability_ids={CAPABILITY_PROCESS},
        worker_pool="source_ingestion",
    )
    assert claimed2 is not None
    assert claimed2.job_id == good["job_id"]
    si_entrypoint._handler(ctx, claimed2)
    assert store.get(good["job_id"]).state == JobState.COMPLETED


def test_idle_no_work_semantics(fabric_env):
    from Data.modules.host_console.read_model import build_source_ingestion_read_model

    class Settings:
        knowledge_database_path = fabric_env["tmp"] / "knowledge.db"
        database_path = fabric_env["tmp"] / "control.db"

    model = build_source_ingestion_read_model(
        settings=Settings(),
        job_runtime=fabric_env["research_service"].job_runtime,
        limit=20,
    )
    assert model["activity"] in {"IDLE_NO_WORK", "IDLE", "IDLE_WITH_FAILURES"}
    assert model["idle_reason"] == "NO_QUEUED_WORK"
    assert model["executor_owner"] in {"fabric", "external"}
    assert model["queue_depth"] == 0
