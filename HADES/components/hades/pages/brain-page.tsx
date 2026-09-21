"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Filter, Focus, Loader2, Network, Plus, RefreshCw, Search, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { hadesApi } from "@/lib/hades-api";
import { BrainGraph } from "./brain-graph";
import { BrainInspector } from "./brain-inspector";
import {
  DRAW_HEIGHT,
  DRAW_WIDTH,
  KIND_LABELS,
  RELATION_OPTIONS,
  ZOOM_MAX,
  ZOOM_MIN,
  apiLinksToGraph,
  apiNodesToGraph,
  clamp,
  fitViewportToNodes,
  validateRelationCreate,
} from "./brain-graph-adapter";
import type { DragState, GraphLink, GraphNode, NodeKind, Viewport } from "./brain-graph-adapter";
import "./brain-page.css";
import "./brain-graph.css";
import "./brain-inspector.css";
import "./brain-responsive.css";

type BrainCounts = {
  nodes: number;
  links: number;
  available?: Record<string, number>;
  included?: Record<string, number>;
  truncated?: boolean;
};

type DragOrigin = { nodeId: string; x: number; y: number };

export function BrainPage() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<GraphLink[]>([]);
  const [counts, setCounts] = useState<BrainCounts>({ nodes: 0, links: 0 });
  const [selectedId, setSelectedId] = useState<string>("");
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<NodeKind | "all">("all");
  const [animated, setAnimated] = useState(true);
  const [focusMode, setFocusMode] = useState(false);
  const [viewMode, setViewMode] = useState("relations");
  const [viewId] = useState("default");
  const [graphMenuOpen, setGraphMenuOpen] = useState(false);
  const [detailsTab, setDetailsTab] = useState<"overview" | "relations" | "metadata">("overview");
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, zoom: 1 });
  const [drag, setDrag] = useState<DragState>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draftLabel, setDraftLabel] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [relationTargetId, setRelationTargetId] = useState("");
  const [relationType, setRelationType] = useState<string>(RELATION_OPTIONS[0]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const loadSeq = useRef(0);
  const nodesRef = useRef<GraphNode[]>([]);
  const viewportRef = useRef(viewport);
  const viewportHydratedRef = useRef(false);
  const dragOriginRef = useRef<DragOrigin | null>(null);
  nodesRef.current = nodes;
  viewportRef.current = viewport;

  const applyGraph = useCallback((nextNodes: GraphNode[], nextLinks: GraphLink[], preferSelected?: string) => {
    setNodes(nextNodes);
    setLinks(nextLinks);
    setSelectedId((current) => {
      const preferred = preferSelected || current;
      if (preferred && nextNodes.some((node) => node.id === preferred)) return preferred;
      return nextNodes.find((node) => node.id === "core_hades")?.id || nextNodes[0]?.id || "";
    });
  }, []);

  const loadBrain = useCallback(async (preferSelected?: string) => {
    const seq = ++loadSeq.current;
    setLoading(true);
    setError(null);
    try {
      const payload = await hadesApi.brain(viewId);
      if (seq !== loadSeq.current) return;
      const layoutMap = new Map(
        (payload.layout?.positions || []).map((row) => [row.entity_id, row]),
      );
      applyGraph(apiNodesToGraph(payload.nodes || [], layoutMap), apiLinksToGraph(payload.links || []), preferSelected);
      setCounts(payload.counts || { nodes: 0, links: 0 });
      if (payload.layout?.viewport && typeof payload.layout.viewport.zoom === "number") {
        const vp = payload.layout.viewport;
        if (vp.updated_at) {
          setViewport({
            x: Number(vp.x) || 0,
            y: Number(vp.y) || 0,
            zoom: clamp(Number(vp.zoom) || 1, ZOOM_MIN, ZOOM_MAX),
          });
        }
      }
      viewportHydratedRef.current = true;
    } catch (exc) {
      if (seq !== loadSeq.current) return;
      setError(exc instanceof Error ? exc.message : "Brain kon niet worden geladen.");
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, [applyGraph, viewId]);

  useEffect(() => {
    void loadBrain();
    return () => {
      loadSeq.current += 1;
    };
  }, [loadBrain]);

  useEffect(() => {
    setEditing(false);
    setDraftLabel("");
    setDraftDescription("");
    setRelationTargetId("");
  }, [selectedId]);

  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const selectedNode = nodeMap.get(selectedId) ?? nodes[0];
  const selectedLinks = useMemo(
    () => links.filter((link) => link.source === selectedId || link.target === selectedId),
    [links, selectedId],
  );
  const neighborIds = useMemo(() => {
    const set = new Set<string>([selectedId]);
    selectedLinks.forEach((link) => set.add(link.source === selectedId ? link.target : link.source));
    return set;
  }, [selectedId, selectedLinks]);

  const visibleNodes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return nodes.filter((node) => {
      const matchesQuery = !needle || `${node.label} ${node.description} ${node.tags.join(" ")}`.toLowerCase().includes(needle);
      const matchesKind = kindFilter === "all" || node.kind === kindFilter;
      const matchesFocus = !focusMode || neighborIds.has(node.id);
      return matchesQuery && matchesKind && matchesFocus;
    });
  }, [focusMode, kindFilter, neighborIds, nodes, query]);

  const visibleIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleLinks = useMemo(
    () => links.filter((link) => visibleIds.has(link.source) && visibleIds.has(link.target)),
    [links, visibleIds],
  );
  const relatedNodes = useMemo(
    () =>
      selectedLinks
        .map((link) => nodeMap.get(link.source === selectedId ? link.target : link.source))
        .filter((node): node is GraphNode => Boolean(node)),
    [nodeMap, selectedId, selectedLinks],
  );

  const relationCandidates = useMemo(
    () =>
      nodes.filter(
        (node) =>
          node.id !== selectedId
          && !selectedLinks.some(
            (link) =>
              (link.source === selectedId && link.target === node.id)
              || (link.target === selectedId && link.source === node.id),
          ),
      ),
    [nodes, selectedId, selectedLinks],
  );

  const svgMetrics = () => {
    const svg = svgRef.current;
    if (!svg) return { width: DRAW_WIDTH, height: DRAW_HEIGHT, left: 0, top: 0 };
    const rect = svg.getBoundingClientRect();
    return {
      width: Math.max(rect.width, 1),
      height: Math.max(rect.height, 1),
      left: rect.left,
      top: rect.top,
    };
  };

  /** Map pointer to logical draw space using live aspect ratio (not a hard content boundary). */
  const svgPoint = (clientX: number, clientY: number) => {
    const { width, height, left, top } = svgMetrics();
    return {
      x: ((clientX - left) / width) * DRAW_WIDTH,
      y: ((clientY - top) / height) * DRAW_HEIGHT,
    };
  };

  const worldPoint = (clientX: number, clientY: number) => {
    const point = svgPoint(clientX, clientY);
    const vp = viewportRef.current;
    return { x: (point.x - vp.x) / vp.zoom, y: (point.y - vp.y) / vp.zoom };
  };

  const resetView = () => setViewport({ x: 0, y: 0, zoom: 1 });
  const setZoom = (next: number) => setViewport((current) => ({ ...current, zoom: clamp(next, ZOOM_MIN, ZOOM_MAX) }));
  const fitView = () => {
    setViewport(fitViewportToNodes(visibleNodes.length ? visibleNodes : nodes, DRAW_WIDTH, DRAW_HEIGHT));
  };

  const openNodeTarget = (node?: GraphNode) => {
    if (!node?.openHref) return;
    window.location.hash = node.openHref.replace(/^#/, "");
  };

  const handleWheel: React.WheelEventHandler<SVGSVGElement> = (event) => {
    event.preventDefault();
    if (loading) return;
    const point = svgPoint(event.clientX, event.clientY);
    setViewport((current) => {
      const nextZoom = clamp(current.zoom * (event.deltaY > 0 ? 0.9 : 1.1), ZOOM_MIN, ZOOM_MAX);
      const worldX = (point.x - current.x) / current.zoom;
      const worldY = (point.y - current.y) / current.zoom;
      return { x: point.x - worldX * nextZoom, y: point.y - worldY * nextZoom, zoom: nextZoom };
    });
  };

  const handleSurfacePointerDown: React.PointerEventHandler<SVGSVGElement> = (event) => {
    if (event.button !== 0 || loading) return;
    const point = svgPoint(event.clientX, event.clientY);
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ mode: "pan", pointerId: event.pointerId, startX: point.x, startY: point.y, originX: viewport.x, originY: viewport.y });
  };

  const handleNodePointerDown = (event: React.PointerEvent<SVGGElement>, node: GraphNode) => {
    if (event.button !== 0 || loading) return;
    event.stopPropagation();
    if (!node.layoutMovable || node.pinned) {
      setSelectedId(node.id);
      return;
    }
    svgRef.current?.setPointerCapture(event.pointerId);
    const world = worldPoint(event.clientX, event.clientY);
    dragOriginRef.current = { nodeId: node.id, x: node.x, y: node.y };
    setSelectedId(node.id);
    setDrag({ mode: "node", pointerId: event.pointerId, nodeId: node.id, offsetX: world.x - node.x, offsetY: world.y - node.y });
  };

  const handlePointerMove: React.PointerEventHandler<SVGSVGElement> = (event) => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (drag.mode === "pan") {
      const point = svgPoint(event.clientX, event.clientY);
      setViewport((current) => ({ ...current, x: drag.originX + point.x - drag.startX, y: drag.originY + point.y - drag.startY }));
      return;
    }
    const world = worldPoint(event.clientX, event.clientY);
    setNodes((current) =>
      current.map((node) =>
        node.id === drag.nodeId
          ? { ...node, x: world.x - drag.offsetX, y: world.y - drag.offsetY }
          : node,
      ),
    );
  };

  const persistNodePosition = async (
    nodeId: string,
    x: number,
    y: number,
    previous: { x: number; y: number },
  ) => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node?.layoutMovable) return;
    try {
      await hadesApi.saveBrainLayoutPosition({ entity_id: nodeId, pos_x: x, pos_y: y, view_id: viewId, pinned: node.pinned });
    } catch (exc) {
      setNodes((current) =>
        current.map((item) =>
          item.id === nodeId && item.x === x && item.y === y
            ? { ...item, x: previous.x, y: previous.y }
            : item,
        ),
      );
      setError(exc instanceof Error ? exc.message : "Positie opslaan mislukt.");
    }
  };

  const handlePointerEnd: React.PointerEventHandler<SVGSVGElement> = (event) => {
    if (drag?.pointerId === event.pointerId) {
      if (drag.mode === "node") {
        const node = nodesRef.current.find((item) => item.id === drag.nodeId);
        const origin = dragOriginRef.current?.nodeId === drag.nodeId ? dragOriginRef.current : null;
        if (event.type === "pointercancel") {
          if (origin) {
            setNodes((current) =>
              current.map((item) =>
                item.id === drag.nodeId ? { ...item, x: origin.x, y: origin.y } : item,
              ),
            );
          }
        } else if (node && origin) {
          void persistNodePosition(node.id, node.x, node.y, { x: origin.x, y: origin.y });
        }
        dragOriginRef.current = null;
      }
      setDrag(null);
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const togglePinSelected = async () => {
    if (!selectedNode?.layoutMovable) return;
    setBusy(true);
    setError(null);
    const nextPinned = !selectedNode.pinned;
    try {
      await hadesApi.saveBrainLayoutPosition({
        entity_id: selectedNode.id,
        pos_x: selectedNode.x,
        pos_y: selectedNode.y,
        pinned: nextPinned,
        view_id: viewId,
      });
      setNodes((current) => current.map((node) => (node.id === selectedNode.id ? { ...node, pinned: nextPinned } : node)));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Pin opslaan mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const createNode = async () => {
    setBusy(true);
    setError(null);
    try {
      const index = nodes.filter((node) => node.source === "Handmatig").length + 1;
      const created = await hadesApi.createBrainNode({
        label: `Nieuwe node ${index}`,
        kind: "note",
        description: "Handmatige Brain-node.",
        tags: ["handmatig"],
        connect_to: selectedNode?.id,
        pos_x: (selectedNode?.x ?? 500) + 120,
        pos_y: (selectedNode?.y ?? 325) + 75,
      });
      await loadBrain(created.id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Node aanmaken mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const addRelation = async () => {
    if (!selectedNode) return;
    const targetId = relationTargetId || relationCandidates[0]?.id || "";
    const validation = validateRelationCreate(selectedId, targetId, links);
    if (validation) {
      setError(validation);
      return;
    }
    if (!relationType.trim()) {
      setError("Kies een relatietype vóór het aanmaken.");
      return;
    }
    setBusy(true);
    setError(null);
    const optimistic: GraphLink = {
      id: `tmp-${selectedId}-${targetId}`,
      source: selectedId,
      target: targetId,
      relation: relationType,
    };
    setLinks((current) => [...current, optimistic]);
    try {
      await hadesApi.createBrainLink({ source_id: selectedId, target_id: targetId, relation: relationType });
      setRelationTargetId("");
      await loadBrain(selectedId);
    } catch (exc) {
      setLinks((current) => current.filter((link) => link.id !== optimistic.id));
      setError(exc instanceof Error ? exc.message : "Relatie maken mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const updateRelation = async (link: GraphLink, nextRelation: string) => {
    setBusy(true);
    setError(null);
    const previous = link.relation;
    setLinks((current) => current.map((item) => (item.id === link.id ? { ...item, relation: nextRelation } : item)));
    try {
      await hadesApi.updateBrainLink({ source_id: link.source, target_id: link.target, relation: nextRelation });
    } catch (exc) {
      setLinks((current) => current.map((item) => (item.id === link.id ? { ...item, relation: previous } : item)));
      setError(exc instanceof Error ? exc.message : "Relatie bijwerken mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const deleteRelation = async (link: GraphLink) => {
    setBusy(true);
    setError(null);
    const originalIndex = links.findIndex((item) => item.id === link.id);
    setLinks((current) => current.filter((item) => item.id !== link.id));
    try {
      await hadesApi.deleteBrainLink(link.source, link.target);
    } catch (exc) {
      setLinks((current) => {
        if (current.some((item) => item.id === link.id)) return current;
        const next = [...current];
        next.splice(Math.max(0, Math.min(originalIndex, next.length)), 0, link);
        return next;
      });
      setError(exc instanceof Error ? exc.message : "Relatie verwijderen mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const startEditing = () => {
    if (!selectedNode?.contentEditable) return;
    setDraftLabel(selectedNode.label);
    setDraftDescription(selectedNode.description);
    setEditing(true);
  };

  const saveEditing = async () => {
    if (!selectedNode?.contentEditable) return;
    setBusy(true);
    setError(null);
    try {
      await hadesApi.updateBrainNode(selectedNode.id, {
        label: draftLabel.trim() || selectedNode.label,
        description: draftDescription.trim(),
      });
      setEditing(false);
      await loadBrain(selectedNode.id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Opslaan mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const deleteSelected = async () => {
    if (!selectedNode?.contentEditable) return;
    const deletedId = selectedNode.id;
    setBusy(true);
    setError(null);
    try {
      await hadesApi.deleteBrainNode(deletedId);
      setEditing(false);
      setNodes((current) => current.filter((node) => node.id !== deletedId));
      setLinks((current) => current.filter((link) => link.source !== deletedId && link.target !== deletedId));
      setSelectedId("");
      await loadBrain();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Verwijderen mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const enterFullscreen = async () => {
    try {
      if (!document.fullscreenElement) await surfaceRef.current?.requestFullscreen();
      else await document.exitFullscreen();
    } catch {
      // Browser policy may block fullscreen; the graph remains usable.
    }
  };

  const persistViewport = async () => {
    if (!viewportHydratedRef.current) return;
    try {
      await hadesApi.saveBrainViewport({ ...viewportRef.current, view_id: viewId });
    } catch {
      // Viewport autosave is non-blocking; node/layout persistence remains authoritative.
    }
  };

  useEffect(() => {
    if (!viewportHydratedRef.current) return;
    const timer = window.setTimeout(() => void persistViewport(), 600);
    return () => window.clearTimeout(timer);
  }, [viewport.x, viewport.y, viewport.zoom]);

  const availableTotal = counts.available
    ? Object.values(counts.available).reduce((sum, value) => sum + Number(value || 0), 0)
    : counts.nodes;

  return (
    <div className={`page brain-redesign-page ${animated ? "is-animated" : "no-motion"}`}>
      <div className="b2-header">
        <div>
          <h1>Brain</h1>
          <p>Live relatiegrafiek van geheugen, kennis, gesprekken, taken en handmatige nodes.</p>
        </div>
        <div className="b2-header-actions">
          <Button variant="outline" onClick={() => void loadBrain(selectedId)} disabled={loading || busy}>
            {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            Vernieuwen
          </Button>
          <Button variant={focusMode ? "default" : "outline"} onClick={() => setFocusMode((value) => !value)}>
            <Focus />
            Focusmodus
          </Button>
          <Button onClick={() => void createNode()} disabled={busy}>
            <Plus />
            Nieuwe node
          </Button>
        </div>
      </div>

      {error ? <div className="b2-error" role="alert">{error}</div> : null}

      <div className="b2-toolbar">
        <div className="b2-search">
          <Search />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Zoek nodes, tags of inhoud..." />
        </div>
        <Select value={kindFilter} onValueChange={(value) => setKindFilter(value as NodeKind | "all")}>
          <SelectTrigger className="b2-type-select">
            <Filter />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Alle types</SelectItem>
            {Object.entries(KIND_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="b2-animation">
          <Sparkles />
          Animatie
          <Switch checked={animated} onCheckedChange={setAnimated} />
        </label>
        <span className="b2-count">
          {loading
            ? "Laden…"
            : `${visibleNodes.length} zichtbaar · ${counts.nodes} geladen · ${availableTotal} beschikbaar${counts.truncated ? " (afgekapt)" : ""} · ${visibleLinks.length} relaties`}
        </span>
        <div className="b2-view-controls">
          <Select value={viewMode} onValueChange={setViewMode}>
            <SelectTrigger className="b2-view-select">
              <Network />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="relations">Weergave: Relaties</SelectItem>
              <SelectItem value="clusters">Weergave: Clusters</SelectItem>
              <SelectItem value="compact">Weergave: Compact</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            aria-label="Meer graph-opties"
            aria-expanded={graphMenuOpen}
            onClick={() => setGraphMenuOpen((value) => !value)}
          >
            •••
          </Button>
          {graphMenuOpen ? (
            <div className="b2-graph-menu">
              <button
                type="button"
                onClick={() => {
                  resetView();
                  setGraphMenuOpen(false);
                }}
              >
                Weergave centreren
              </button>
              <button
                type="button"
                onClick={() => {
                  fitView();
                  setGraphMenuOpen(false);
                }}
              >
                Passend op inhoud
              </button>
              <button type="button" onClick={() => setAnimated((value) => !value)}>
                {animated ? "Animatie uitschakelen" : "Animatie inschakelen"}
              </button>
              <button
                type="button"
                onClick={() => {
                  void loadBrain(selectedId);
                  setGraphMenuOpen(false);
                }}
              >
                Live data herladen
              </button>
            </div>
          ) : null}
        </div>
      </div>

      <div className="b2-layout">
        <BrainGraph
          nodes={nodes}
          links={links}
          visibleNodes={visibleNodes}
          visibleLinks={visibleLinks}
          selectedId={selectedId}
          hoveredId={hoveredId}
          viewport={viewport}
          drag={drag}
          viewMode={viewMode}
          kindFilter={kindFilter}
          surfaceRef={surfaceRef}
          svgRef={svgRef}
          onWheel={handleWheel}
          onSurfacePointerDown={handleSurfacePointerDown}
          onPointerMove={handlePointerMove}
          onPointerEnd={handlePointerEnd}
          onNodePointerDown={handleNodePointerDown}
          onSelectNode={setSelectedId}
          onHoverNode={setHoveredId}
          onZoom={setZoom}
          onResetView={resetView}
          onFitView={fitView}
          onFullscreen={enterFullscreen}
          onLegendFilter={(kind) => setKindFilter((current) => (current === kind ? "all" : kind))}
        />
        <BrainInspector
          selectedNode={selectedNode}
          selectedLinks={selectedLinks}
          relatedNodes={relatedNodes}
          totalLinks={links.length}
          zoom={viewport.zoom}
          detailsTab={detailsTab}
          editing={editing}
          draftLabel={draftLabel}
          draftDescription={draftDescription}
          busy={busy}
          relationTargetId={relationTargetId}
          relationType={relationType}
          relationCandidates={relationCandidates}
          onSelectNode={setSelectedId}
          onDetailsTab={setDetailsTab}
          onRelationTargetId={setRelationTargetId}
          onRelationType={setRelationType}
          onAddRelation={() => void addRelation()}
          onUpdateRelation={(link, next) => void updateRelation(link, next)}
          onDeleteRelation={(link) => void deleteRelation(link)}
          onTogglePin={() => void togglePinSelected()}
          onStartEditing={startEditing}
          onCancelEditing={() => setEditing(false)}
          onSaveEditing={() => void saveEditing()}
          onDraftLabel={setDraftLabel}
          onDraftDescription={setDraftDescription}
          onDelete={() => void deleteSelected()}
          onOpenTarget={() => openNodeTarget(selectedNode)}
        />
      </div>
    </div>
  );
}

/** Exported for component tests. */
export const __brainTestUtils = {
  fitViewportToNodes,
  validateRelationCreate,
  clamp,
  ZOOM_MIN,
  ZOOM_MAX,
};