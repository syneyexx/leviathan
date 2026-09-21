"""Brain HTTP routes — layout, graph assembly, nodes/links (work package L / G)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from api_contracts import ApiErrorBody, PageMeta
from brain_graph import assemble_brain_graph, is_derived_entity_id
from brain_node_detail import build_brain_node_detail

router = APIRouter(tags=["brain"])

# Re-export for thin main.py compat layers / OpenAPI collectors.
__all__ = [
    "ApiErrorBody",
    "BrainGraphResponse",
    "BrainLayoutPositionInput",
    "BrainLinkInput",
    "BrainLinkUpdate",
    "BrainNodeInput",
    "BrainNodeUpdate",
    "BrainViewportInput",
    "PageMeta",
    "mount_brain_routes",
]

_EXTERNAL_ENTITY_PREFIXES = ("memory_", "knowledge_", "conversation_", "task_", "step_")


class BrainNodeInput(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["project", "memory", "model", "task", "tech", "note", "chat", "knowledge", "agent", "system"] = "note"
    description: str = Field(default="", max_length=2_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    connect_to: str | None = None
    pos_x: float | None = Field(default=None)
    pos_y: float | None = Field(default=None)


class BrainNodeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Literal["project", "memory", "model", "task", "tech", "note", "chat", "knowledge", "agent", "system"] | None = None
    description: str | None = Field(default=None, max_length=2_000)
    tags: list[str] | None = Field(default=None, max_length=20)
    pos_x: float | None = Field(default=None)
    pos_y: float | None = Field(default=None)


class BrainLinkInput(BaseModel):
    source_id: str = Field(min_length=1, max_length=120)
    target_id: str = Field(min_length=1, max_length=120)
    relation: str = Field(default="gerelateerd aan", max_length=80)


class BrainLinkUpdate(BaseModel):
    source_id: str = Field(min_length=1, max_length=120)
    target_id: str = Field(min_length=1, max_length=120)
    relation: str = Field(min_length=1, max_length=80)


class BrainLayoutPositionInput(BaseModel):
    entity_id: str = Field(min_length=1, max_length=160)
    pos_x: float
    pos_y: float
    pinned: bool | None = None
    view_id: str = Field(default="default", max_length=80)


class BrainViewportInput(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = Field(default=1, gt=0.05, le=8)
    view_id: str = Field(default="default", max_length=80)


class BrainCountsModel(BaseModel):
    """Explicit transport shape for Brain GET counts (OpenAPI / TS generation)."""

    nodes: int
    links: int
    available: dict[str, int]
    included: dict[str, int]
    visible_hint: int
    truncated: bool


class BrainGraphResponse(BaseModel):
    """Important Brain GET response — nullability and pagination/truncation explicit."""

    nodes: list[dict[str, Any]]
    links: list[dict[str, Any]]
    layout: dict[str, Any]
    view_id: str
    counts: BrainCountsModel
    relation_kinds: list[str]


def mount_brain_routes(ctx: dict[str, Any]) -> APIRouter:
    class _Svc:
        def __getattr__(self, name: str) -> Any:
            return ctx[name]

        def get(self, name: str, default: Any = None) -> Any:
            return ctx.get(name, default)

    s = _Svc()

    def _ensure() -> None:
        ensure = s.get("ensure_platform_services")
        if callable(ensure):
            ensure()

    def _current_entity_ids() -> set[str]:
        """Resolve every current Brain endpoint for mutation validation.

        Brain writes are rare compared with reads/drag layout writes. Building the full
        current graph here prevents user-created dangling links while keeping the hot
        layout-position endpoint lightweight.
        """
        settings = s.runtime_values()
        configured_cap = int(settings.get("brain_include_limit") or 2_000)
        soft_cap = max(
            50,
            configured_cap,
            int(s.database.count_memories(active_only=True)),
            int(s.platform_db.count_knowledge_sources()),
            int(s.database.count_conversations()),
            int(s.database.count_tasks()),
        )
        graph = assemble_brain_graph(
            database=s.database,
            platform_db=s.platform_db,
            soft_cap=soft_cap,
            view_id="default",
        )
        return {str(node.get("id")) for node in graph.get("nodes") or [] if node.get("id")}

    def _require_entities(*entity_ids: str) -> None:
        known = _current_entity_ids()
        missing = [entity_id for entity_id in entity_ids if entity_id not in known]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Brain-node bestaat niet of is niet beschikbaar: {', '.join(missing)}",
            )

    @router.get("/brain", response_model=BrainGraphResponse, response_model_exclude_unset=False)
    async def brain(
        view_id: str = Query(default="default"),
        include_limit: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        _ensure()
        settings = s.runtime_values()
        soft_cap = include_limit if include_limit is not None else int(settings.get("brain_include_limit") or 2_000)
        return await asyncio.to_thread(
            assemble_brain_graph,
            database=s.database,
            platform_db=s.platform_db,
            soft_cap=soft_cap,
            view_id=view_id,
        )

    @router.get("/brain/nodes/{node_id}/detail", include_in_schema=False)
    async def brain_node_detail(node_id: str) -> dict[str, Any]:
        """Load the durable content behind one graph node only when the user opens it."""
        _ensure()
        try:
            return await asyncio.to_thread(
                build_brain_node_detail,
                database=s.database,
                platform_db=s.platform_db,
                node_id=node_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Brain-node bestaat niet meer.") from exc

    @router.get("/brain/layout")
    async def get_brain_layout(view_id: str = Query(default="default")) -> dict[str, Any]:
        _ensure()
        return await asyncio.to_thread(s.database.list_brain_layout, view_id)

    @router.put("/brain/layout/position")
    async def put_brain_layout_position(values: BrainLayoutPositionInput) -> dict[str, Any]:
        _ensure()
        return await asyncio.to_thread(
            s.database.upsert_brain_layout_position,
            values.entity_id,
            pos_x=values.pos_x,
            pos_y=values.pos_y,
            pinned=values.pinned,
            view_id=values.view_id,
        )

    @router.put("/brain/layout/viewport")
    async def put_brain_viewport(values: BrainViewportInput) -> dict[str, Any]:
        _ensure()
        return await asyncio.to_thread(
            s.database.save_brain_viewport,
            x=values.x,
            y=values.y,
            zoom=values.zoom,
            view_id=values.view_id,
        )

    @router.post("/brain/nodes", status_code=status.HTTP_201_CREATED)
    async def create_brain_node(values: BrainNodeInput) -> dict[str, Any]:
        _ensure()

        def _create() -> dict[str, Any]:
            if values.connect_to:
                _require_entities(values.connect_to)
            external_target = (
                values.connect_to
                if values.connect_to and values.connect_to.startswith(_EXTERNAL_ENTITY_PREFIXES)
                else None
            )
            node = s.database.create_brain_node(
                values.label,
                values.kind,
                values.description,
                values.tags,
                None if external_target else values.connect_to,
                pos_x=values.pos_x,
                pos_y=values.pos_y,
            )
            if external_target:
                link = s.platform_db.add_brain_external_link(node["id"], external_target)
                if not link:
                    s.database.delete_brain_node(node["id"])
                    raise HTTPException(status_code=400, detail="Kon de nieuwe Brain-node niet aan het gekozen doel koppelen.")
            return node

        try:
            return await asyncio.to_thread(_create)
        except HTTPException:
            raise

    @router.put("/brain/nodes/{node_id}")
    async def update_brain_node(node_id: str, values: BrainNodeUpdate) -> dict[str, Any]:
        _ensure()

        def _update() -> dict[str, Any]:
            content_fields = any(v is not None for v in (values.label, values.description, values.tags, values.kind))
            layout_only = values.pos_x is not None or values.pos_y is not None
            is_derived = is_derived_entity_id(node_id)
            if is_derived and content_fields:
                raise HTTPException(
                    status_code=400,
                    detail="Inhoud van afgeleide of kernnodes is niet bewerkbaar; layout wel.",
                )
            if is_derived and layout_only:
                if values.pos_x is None or values.pos_y is None:
                    layout = s.database.list_brain_layout("default")
                    existing = next((row for row in layout["positions"] if row["entity_id"] == node_id), None)
                    pos_x = values.pos_x if values.pos_x is not None else (existing or {}).get("pos_x", 0)
                    pos_y = values.pos_y if values.pos_y is not None else (existing or {}).get("pos_y", 0)
                else:
                    pos_x, pos_y = values.pos_x, values.pos_y
                saved = s.database.upsert_brain_layout_position(node_id, pos_x=float(pos_x), pos_y=float(pos_y))
                return {
                    "id": node_id,
                    "pos_x": saved["pos_x"],
                    "pos_y": saved["pos_y"],
                    "pinned": saved["pinned"],
                    "layout_only": True,
                }
            updated = s.database.update_brain_node(
                node_id,
                label=values.label,
                description=values.description,
                tags=values.tags,
                kind=values.kind,
                pos_x=values.pos_x,
                pos_y=values.pos_y,
            )
            if not updated:
                raise HTTPException(
                    status_code=404,
                    detail="Brain-node niet gevonden of niet bewerkbaar (overlay-nodes zijn afgeleid).",
                )
            if values.pos_x is not None and values.pos_y is not None:
                s.database.upsert_brain_layout_position(node_id, pos_x=float(values.pos_x), pos_y=float(values.pos_y))
            return updated

        try:
            return await asyncio.to_thread(_update)
        except HTTPException:
            raise

    @router.delete("/brain/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_brain_node(node_id: str) -> Response:
        _ensure()
        deleted = await asyncio.to_thread(s.database.delete_brain_node, node_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Brain-node niet verwijderbaar.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/brain/links", status_code=status.HTTP_201_CREATED)
    async def create_brain_link(values: BrainLinkInput) -> dict[str, Any]:
        _ensure()

        def _create() -> dict[str, Any]:
            if values.source_id == values.target_id:
                raise HTTPException(status_code=400, detail="Zelfkoppeling is niet toegestaan.")
            _require_entities(values.source_id, values.target_id)
            if is_derived_entity_id(values.source_id) or is_derived_entity_id(values.target_id):
                # External / derived endpoints use platform_db; core_ prefix alone is not external.
                if values.source_id.startswith(_EXTERNAL_ENTITY_PREFIXES) or values.target_id.startswith(_EXTERNAL_ENTITY_PREFIXES):
                    link = s.platform_db.add_brain_external_link(values.source_id, values.target_id, values.relation)
                    if not link:
                        raise HTTPException(status_code=400, detail="Dubbele of ongeldige externe relatie.")
                    return {**link, "provenance": "user_explicit"}
            link = s.database.add_brain_link(values.source_id, values.target_id, values.relation)
            if not link:
                raise HTTPException(
                    status_code=400,
                    detail="Kan geen relatie maken tussen deze nodes (dubbel of ongeldig).",
                )
            return {**link, "provenance": "user_explicit"}

        try:
            return await asyncio.to_thread(_create)
        except HTTPException:
            raise

    @router.put("/brain/links")
    async def update_brain_link(values: BrainLinkUpdate) -> dict[str, Any]:
        _ensure()

        def _update() -> dict[str, Any]:
            updated = s.database.update_brain_link(values.source_id, values.target_id, values.relation)
            if updated:
                return {**updated, "provenance": "user_explicit"}
            updated = s.platform_db.update_brain_external_link(values.source_id, values.target_id, values.relation)
            if not updated:
                raise HTTPException(status_code=404, detail="Relatie niet gevonden.")
            return {**updated, "provenance": "user_explicit"}

        try:
            return await asyncio.to_thread(_update)
        except HTTPException:
            raise

    @router.delete("/brain/links", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_brain_link(source_id: str = Query(...), target_id: str = Query(...)) -> Response:
        _ensure()

        def _delete() -> bool:
            deleted = s.database.delete_brain_link(source_id, target_id)
            if not deleted:
                deleted = s.platform_db.delete_brain_external_link(source_id, target_id)
            return bool(deleted)

        deleted = await asyncio.to_thread(_delete)
        if not deleted:
            raise HTTPException(status_code=404, detail="Relatie niet gevonden.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
