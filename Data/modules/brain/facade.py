"""Bounded Brain graph projection over authoritative Leviathan stores.

Brain is a read/query facade — not a second source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class BrainNode:
    id: str
    type: str
    label: str
    created_at: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "created_at": self.created_at,
            "meta": self.meta,
        }


@dataclass
class BrainEdge:
    id: str
    source: str
    target: str
    relation: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
        }


class BrainQueryFacade:
    """Assemble a bounded graph from existing domain stores."""

    def __init__(
        self,
        *,
        knowledge_list: Callable[[], list[Any]] | None = None,
        evidence_list: Callable[[], list[Any]] | None = None,
        research_list: Callable[[], list[Any]] | None = None,
        dataset_list: Callable[[], list[Any]] | None = None,
        module_list: Callable[[], list[Any]] | None = None,
        capability_list: Callable[[], list[Any]] | None = None,
        mcp_servers: Callable[[], list[Any]] | None = None,
        mcp_tools: Callable[[], list[Any]] | None = None,
        workflow_list: Callable[[], list[Any]] | None = None,
        atlas_list: Callable[[], list[Any]] | None = None,
        max_nodes: int = 250,
        max_edges: int = 500,
    ) -> None:
        self.knowledge_list = knowledge_list
        self.evidence_list = evidence_list
        self.research_list = research_list
        self.dataset_list = dataset_list
        self.module_list = module_list
        self.capability_list = capability_list
        self.mcp_servers = mcp_servers
        self.mcp_tools = mcp_tools
        self.workflow_list = workflow_list
        self.atlas_list = atlas_list
        self.max_nodes = max(10, min(int(max_nodes), 1000))
        self.max_edges = max(10, min(int(max_edges), 2000))

    def query(
        self,
        *,
        types: list[str] | None = None,
        q: str | None = None,
        limit: int | None = None,
        root: str | None = None,
    ) -> dict[str, Any]:
        want = {t.lower() for t in (types or [])} if types else None
        limit_n = max(1, min(int(limit or self.max_nodes), self.max_nodes))
        nodes: dict[str, BrainNode] = {}
        edges: list[BrainEdge] = []

        def add_node(node: BrainNode) -> None:
            if len(nodes) >= limit_n:
                return
            if want and node.type not in want and not node.type.startswith(tuple(want)):
                # Allow prefix match e.g. type filter "knowledge" matches knowledge.document
                if not any(node.type.startswith(f"{t}.") or node.type == t for t in want):
                    return
            if q:
                hay = f"{node.label} {node.id} {node.type}".lower()
                if q.lower() not in hay:
                    return
            nodes[node.id] = node

        def add_edge(edge: BrainEdge) -> None:
            if len(edges) >= self.max_edges:
                return
            if edge.source not in nodes or edge.target not in nodes:
                return
            edges.append(edge)

        # Knowledge documents
        if self.knowledge_list:
            for doc in self.knowledge_list()[:limit_n]:
                d = doc.public_dict() if hasattr(doc, "public_dict") else dict(doc)
                nid = f"knowledge:document:{d.get('id')}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="knowledge.document",
                        label=str(d.get("title") or d.get("id")),
                        created_at=d.get("created_at"),
                        meta={"status": d.get("status"), "source": d.get("source")},
                    )
                )

        # Evidence
        if self.evidence_list:
            for ev in self.evidence_list()[:limit_n]:
                e = ev.public_dict() if hasattr(ev, "public_dict") else dict(ev)
                eid = e.get("evidence_id")
                nid = f"evidence:{eid}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="evidence",
                        label=str((e.get("claim") or eid) or "")[:120],
                        created_at=e.get("created_at"),
                        meta={"status": e.get("status"), "kind": e.get("kind")},
                    )
                )
                if e.get("run_id"):
                    rid = f"run:{e['run_id']}"
                    add_node(BrainNode(id=rid, type="run", label=str(e["run_id"])[:40]))
                    add_edge(BrainEdge(id=f"{nid}->run", source=nid, target=rid, relation="from_run"))

        # Research projects
        if self.research_list:
            for proj in self.research_list()[:limit_n]:
                p = proj.public_dict() if hasattr(proj, "public_dict") else dict(proj)
                pid = p.get("project_id")
                nid = f"research:project:{pid}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="research.project",
                        label=str(p.get("title") or p.get("topic") or pid),
                        created_at=p.get("created_at"),
                        meta={"status": p.get("status")},
                    )
                )

        # Datasets
        if self.dataset_list:
            for ds in self.dataset_list()[:limit_n]:
                d = ds.public_dict() if hasattr(ds, "public_dict") else dict(ds)
                did = d.get("dataset_id") or d.get("id")
                nid = f"dataset:{did}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="dataset",
                        label=str(d.get("name") or did),
                        created_at=d.get("created_at") or d.get("updated_at"),
                        meta={"status": d.get("status")},
                    )
                )

        # Modules + capabilities
        if self.module_list:
            for mod in self.module_list()[:limit_n]:
                m = mod.public_dict() if hasattr(mod, "public_dict") else dict(mod)
                manifest = m.get("manifest") or {}
                mid = manifest.get("module_id") or m.get("module_id")
                if not mid:
                    continue
                nid = f"module:{mid}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="module",
                        label=str(manifest.get("name") or mid),
                        meta={"status": m.get("status")},
                    )
                )
                for cap in manifest.get("capabilities") or []:
                    cid = cap.get("capability_id") if isinstance(cap, dict) else getattr(cap, "capability_id", None)
                    if not cid:
                        continue
                    cnid = f"capability:{cid}"
                    add_node(
                        BrainNode(
                            id=cnid,
                            type="capability",
                            label=str(
                                (cap.get("name") if isinstance(cap, dict) else None) or cid
                            ),
                        )
                    )
                    add_edge(
                        BrainEdge(
                            id=f"{nid}->{cnid}",
                            source=nid,
                            target=cnid,
                            relation="exports",
                        )
                    )

        if self.capability_list:
            for cap in self.capability_list()[:limit_n]:
                c = cap.public_dict() if hasattr(cap, "public_dict") else dict(cap)
                cid = c.get("id")
                nid = f"capability:{cid}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="capability",
                        label=str(c.get("name") or cid),
                        meta={
                            "provider_kind": c.get("provider_kind"),
                            "available": c.get("available"),
                        },
                    )
                )

        # MCP
        if self.mcp_servers:
            for srv in self.mcp_servers()[:limit_n]:
                s = srv if isinstance(srv, dict) else (srv.public_dict() if hasattr(srv, "public_dict") else {})
                sid = s.get("server_id") or s.get("id")
                if not sid:
                    continue
                nid = f"mcp:server:{sid}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="mcp.server",
                        label=str(s.get("name") or sid),
                        meta={"connection_state": s.get("connection_state") or s.get("state")},
                    )
                )

        if self.mcp_tools:
            for tool in self.mcp_tools()[:limit_n]:
                t = tool if isinstance(tool, dict) else (tool.public_dict() if hasattr(tool, "public_dict") else {})
                tid = t.get("tool_id") or t.get("name")
                sid = t.get("server_id")
                if not tid:
                    continue
                nid = f"mcp:tool:{sid}:{tid}" if sid else f"mcp:tool:{tid}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="mcp.tool",
                        label=str(t.get("name") or tid),
                    )
                )
                if sid:
                    snid = f"mcp:server:{sid}"
                    if snid in nodes:
                        add_edge(
                            BrainEdge(
                                id=f"{snid}->{nid}",
                                source=snid,
                                target=nid,
                                relation="exposes",
                            )
                        )

        # Workflows
        if self.workflow_list:
            for wf in self.workflow_list()[:limit_n]:
                w = wf.public_dict() if hasattr(wf, "public_dict") else dict(wf)
                wid = w.get("workflow_id")
                nid = f"workflow:{wid}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="workflow",
                        label=str(w.get("name") or wid),
                        created_at=w.get("created_at"),
                        meta={"state": w.get("state")},
                    )
                )
                for step in w.get("steps") or []:
                    cid = step.get("capability_id") if isinstance(step, dict) else None
                    if not cid:
                        continue
                    cnid = f"capability:{cid}"
                    if cnid not in nodes:
                        add_node(BrainNode(id=cnid, type="capability", label=str(cid)))
                    add_edge(
                        BrainEdge(
                            id=f"{nid}->{cnid}:{step.get('step_id')}",
                            source=nid,
                            target=cnid,
                            relation="uses",
                        )
                    )

        # Atlas (optional)
        if self.atlas_list:
            for rec in self.atlas_list()[:limit_n]:
                a = rec.public_dict() if hasattr(rec, "public_dict") else dict(rec)
                aid = a.get("atlas_id")
                nid = f"atlas:{aid}"
                add_node(
                    BrainNode(
                        id=nid,
                        type="atlas",
                        label=str(a.get("title") or aid),
                        meta={"scale": a.get("scale")},
                    )
                )
                for ref in a.get("evidence_record_refs") or []:
                    evid = f"evidence:{ref}"
                    if evid in nodes:
                        add_edge(
                            BrainEdge(
                                id=f"{nid}->{evid}",
                                source=nid,
                                target=evid,
                                relation="interprets",
                            )
                        )

        # Optional root neighbor filter
        if root and root in nodes:
            keep = {root}
            for edge in edges:
                if edge.source == root or edge.target == root:
                    keep.add(edge.source)
                    keep.add(edge.target)
            nodes = {k: v for k, v in nodes.items() if k in keep}
            edges = [e for e in edges if e.source in keep and e.target in keep]

        node_list = list(nodes.values())
        type_counts: dict[str, int] = {}
        for n in node_list:
            type_counts[n.type] = type_counts.get(n.type, 0) + 1
        rel_counts: dict[str, int] = {}
        for e in edges:
            rel_counts[e.relation] = rel_counts.get(e.relation, 0) + 1

        return {
            "nodes": [n.public_dict() for n in node_list],
            "edges": [e.public_dict() for e in edges],
            "stats": {
                "node_count": len(node_list),
                "edge_count": len(edges),
                "by_type": type_counts,
                "by_relation": rel_counts,
            },
            "truth": {
                "projection_only": True,
                "not_source_of_truth": True,
                "bounded": True,
                "max_nodes": self.max_nodes,
                "max_edges": self.max_edges,
            },
        }
