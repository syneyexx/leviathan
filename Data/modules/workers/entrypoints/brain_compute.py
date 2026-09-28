"""Worker Fabric entrypoint — brain_compute pool (derived compute only)."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _bind_facade(ctx: dict[str, Any]) -> None:
    """Attach a BrainQueryFacade over CONTROL/KNOWLEDGE stores when not injected."""
    if ctx.get("brain_facade") is not None:
        return
    settings = ctx.get("settings")
    if settings is None:
        return
    try:
        from Data.modules.brain import BrainQueryFacade
        from Data.modules.common.database_domains import (
            knowledge_path_from_settings,
            resolve_control_database_path,
        )
        from Data.modules.knowledge import KnowledgeStore
        from Data.modules.memory import MemoryStore
        from Data.modules.research.store import ResearchStore

        knowledge = KnowledgeStore(
            knowledge_path_from_settings(settings),
            data_root=getattr(getattr(settings, "knowledge", None), "data_root", None),
        )
        knowledge.initialize_schema()
        control = resolve_control_database_path(
            explicit=getattr(settings, "control_database_path", None)
            or getattr(settings, "database_path", None)
        )
        memory = MemoryStore(control)
        memory.initialize()
        research = ResearchStore(control)
        research.initialize()

        def _knowledge_list():
            return knowledge.list_documents(limit=250)

        def _memory_list():
            return memory.list(limit=200)

        def _research_list():
            return research.list_projects(limit=100)

        ctx["brain_facade"] = BrainQueryFacade(
            knowledge_list=_knowledge_list,
            memory_list=_memory_list,
            research_list=_research_list,
            max_nodes=1000,
            max_edges=2000,
        )
        ctx["knowledge_list"] = _knowledge_list
        ctx["memory_list"] = _memory_list
        ctx["research_list"] = _research_list
    except Exception:  # noqa: BLE001 — leave unbound; compute module builds empty facade
        return


def _handler(ctx, job):
    from Data.modules.brain.compute import process_brain_compute_job

    _bind_facade(ctx)
    return process_brain_compute_job(ctx, job)


def main(argv=None):
    return main_for_pool("brain_compute", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
