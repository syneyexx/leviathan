import { formatDate, type BrainLink as ApiBrainLink, type BrainNode as ApiBrainNode } from "@/lib/hades-api";

export type NodeKind =
  | "core"
  | "module"
  | "data"
  | "agent"
  | "language"
  | "system"
  | "other"
  | "memory"
  | "task"
  | "chat"
  | "knowledge"
  | "project"
  | "tech"
  | "note"
  | "work_step"
  | "model";

export type IconKind =
  | "core"
  | "settings"
  | "chat"
  | "task"
  | "model"
  | "memory"
  | "api"
  | "db"
  | "react"
  | "doc"
  | "language"
  | "architecture";

export type GraphNode = {
  id: string;
  label: string;
  kind: NodeKind;
  icon: IconKind;
  x: number;
  y: number;
  cluster: string;
  description: string;
  source: string;
  persistent: boolean;
  createdAt: string;
  updatedAt: string;
  tags: string[];
  openHref?: string;
  relationKindHints?: string[];
  /** Content (label/description/tags) may be edited. */
  contentEditable: boolean;
  /** Position/pin may be changed even when content is read-only (derived/core/…). */
  layoutMovable: boolean;
  pinned: boolean;
};

export type GraphLink = {
  id: string;
  source: string;
  target: string;
  relation: string;
  relationKind?: string;
  external?: boolean;
};

export type Viewport = { x: number; y: number; zoom: number };
export type DragState =
  | { mode: "pan"; pointerId: number; startX: number; startY: number; originX: number; originY: number }
  | { mode: "node"; pointerId: number; nodeId: string; offsetX: number; offsetY: number }
  | null;

/** @deprecated Prefer GraphNode — compatibility alias. */
export type MockNode = GraphNode;
/** @deprecated Prefer GraphLink */
export type MockLink = GraphLink;

export const KIND_LABELS: Record<NodeKind, string> = {
  core: "Kern",
  module: "Module",
  data: "Data",
  agent: "Agent",
  language: "Taal",
  system: "Systeem",
  other: "Overig",
  memory: "Geheugen",
  task: "Taak",
  chat: "Chat",
  knowledge: "Kennis",
  project: "Project",
  tech: "Techniek",
  note: "Notitie",
  work_step: "Werkstap",
  model: "Model",
};

export const RELATION_OPTIONS = [
  "gerelateerd aan",
  "bevat",
  "verwijst naar",
  "afhankelijk van",
  "vervangt",
  "produceert",
  "ondersteunt",
] as const;

export const INITIAL_NODES: GraphNode[] = [];
export const INITIAL_LINKS: GraphLink[] = [];
export const CLUSTERS: Array<{
  id: string;
  label: string;
  count: string;
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  tone: string;
}> = [];

export const DRAW_WIDTH = 1000;
export const DRAW_HEIGHT = 650;
export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 3;

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function isDerivedEntityId(id: string): boolean {
  return (
    id.startsWith("memory_")
    || id.startsWith("knowledge_")
    || id.startsWith("conversation_")
    || id.startsWith("task_")
    || id.startsWith("step_")
  );
}

export function isCoreEntityId(id: string): boolean {
  return id.startsWith("core_");
}

/** Content edit rights are separate from layout (move/pin) rights. */
export function contentEditableForId(id: string): boolean {
  return !isDerivedEntityId(id) && !isCoreEntityId(id);
}

export function layoutMovableForId(_id: string): boolean {
  return true;
}

function mapKind(raw: string): NodeKind {
  const value = (raw || "other").toLowerCase();
  if (value in KIND_LABELS) return value as NodeKind;
  if (value === "tech") return "tech";
  return "other";
}

function mapIcon(kind: NodeKind, id: string): IconKind {
  if (id === "core_hades" || kind === "core") return "core";
  if (id.includes("chat") || kind === "chat") return "chat";
  if (id.includes("task") || kind === "task" || kind === "work_step") return "task";
  if (id.includes("model") || kind === "model") return "model";
  if (id.includes("memory") || kind === "memory") return "memory";
  if (id.includes("sqlite") || id.includes("db")) return "db";
  if (id.includes("fastapi") || id.includes("api")) return "api";
  if (id.includes("react")) return "react";
  if (kind === "knowledge" || kind === "note" || kind === "project") return "doc";
  if (kind === "system" || kind === "tech") return "architecture";
  if (kind === "agent") return "chat";
  return "doc";
}

function mapCluster(kind: NodeKind, id: string): string {
  if (id.startsWith("core_")) return "Architectuur";
  if (kind === "memory" || kind === "knowledge") return "Geheugen & Kennis";
  if (kind === "chat") return "Gesprekken";
  if (kind === "task" || kind === "work_step") return "Werk";
  if (kind === "model") return "AI Integratie";
  if (kind === "agent") return "Agents";
  return "Overig";
}

function layoutPosition(
  index: number,
  total: number,
  existingX?: number | null,
  existingY?: number | null,
): { x: number; y: number } {
  if (typeof existingX === "number" && typeof existingY === "number" && Number.isFinite(existingX) && Number.isFinite(existingY)) {
    return { x: existingX, y: existingY };
  }
  if (total <= 1) return { x: 500, y: 325 };
  const ring = index < 10 ? 1 : index < 28 ? 2 : 3;
  const ringStart = ring === 1 ? 0 : ring === 2 ? 10 : 28;
  const ringCount = ring === 1 ? Math.min(10, total) : ring === 2 ? Math.min(18, Math.max(1, total - 10)) : Math.max(1, total - 28);
  const ringIndex = index - ringStart;
  const angle = (ringIndex / ringCount) * Math.PI * 2 - Math.PI / 2;
  const radiusX = ring === 1 ? 230 : ring === 2 ? 360 : 470;
  const radiusY = ring === 1 ? 170 : ring === 2 ? 250 : 300;
  return { x: 500 + Math.cos(angle) * radiusX, y: 325 + Math.sin(angle) * radiusY };
}

export type LayoutEntry = { entity_id: string; pos_x: number; pos_y: number; pinned?: boolean };

/** Fit viewport to visible node bounds (not a fixed zoom). */
export function fitViewportToNodes(
  nodes: Array<{ x: number; y: number }>,
  viewWidth = DRAW_WIDTH,
  viewHeight = DRAW_HEIGHT,
  padding = 48,
): Viewport {
  if (!nodes.length) return { x: 0, y: 0, zoom: 1 };
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const node of nodes) {
    minX = Math.min(minX, node.x);
    maxX = Math.max(maxX, node.x);
    minY = Math.min(minY, node.y);
    maxY = Math.max(maxY, node.y);
  }
  const width = Math.max(maxX - minX, 80);
  const height = Math.max(maxY - minY, 80);
  const zoom = clamp(
    Math.min((viewWidth - 2 * padding) / width, (viewHeight - 2 * padding) / height),
    ZOOM_MIN,
    ZOOM_MAX,
  );
  const contentW = width * zoom;
  const contentH = height * zoom;
  const x = padding + (viewWidth - 2 * padding - contentW) / 2 - minX * zoom;
  const y = padding + (viewHeight - 2 * padding - contentH) / 2 - minY * zoom;
  return { x, y, zoom };
}

export function apiNodesToGraph(
  nodes: ApiBrainNode[],
  layoutById?: Map<string, LayoutEntry> | Record<string, LayoutEntry>,
): GraphNode[] {
  const layoutMap =
    layoutById instanceof Map
      ? layoutById
      : new Map(Object.entries(layoutById || {}).map(([id, entry]) => [id, entry]));
  const coreIndex = nodes.findIndex((node) => node.id === "core_hades");
  const ordered = coreIndex >= 0 ? [nodes[coreIndex], ...nodes.filter((_, index) => index !== coreIndex)] : nodes;
  return ordered.map((node, index) => {
    const kind = mapKind(node.kind);
    const layout = layoutMap.get(node.id);
    const posX = layout?.pos_x ?? node.pos_x;
    const posY = layout?.pos_y ?? node.pos_y;
    const pos = layoutPosition(index, ordered.length, posX, posY);
    return {
      id: node.id,
      label: node.label,
      kind,
      icon: mapIcon(kind, node.id),
      x: node.id === "core_hades" && posX == null ? 500 : pos.x,
      y: node.id === "core_hades" && posY == null ? 325 : pos.y,
      cluster: mapCluster(kind, node.id),
      description: node.description || "",
      source: node.source || "HADES",
      persistent: node.persistent !== false,
      createdAt: formatDate(node.created_at),
      updatedAt: formatDate(node.updated_at),
      tags: node.tags || [],
      openHref: node.open_href,
      contentEditable:
        typeof node.content_editable === "boolean" ? node.content_editable : contentEditableForId(node.id),
      layoutMovable:
        typeof node.layout_movable === "boolean" ? node.layout_movable : layoutMovableForId(node.id),
      pinned: Boolean(layout?.pinned ?? node.pinned),
    };
  });
}

export function apiLinksToGraph(links: ApiBrainLink[]): GraphLink[] {
  return links.map((link, index) => ({
    id: `${link.source_id}->${link.target_id}:${link.relation}:${index}`,
    source: link.source_id,
    target: link.target_id,
    relation: link.relation,
    relationKind: link.relation_kind,
    external: Boolean((link as { external?: boolean }).external),
  }));
}

export function validateRelationCreate(
  sourceId: string,
  targetId: string,
  existing: Array<{ source: string; target: string }>,
): string | null {
  if (!sourceId || !targetId) return "Bron en doel zijn verplicht.";
  if (sourceId === targetId) return "Een node kan niet aan zichzelf gekoppeld worden.";
  if (existing.some((link) => (link.source === sourceId && link.target === targetId) || (link.source === targetId && link.target === sourceId))) {
    return "Deze relatie bestaat al.";
  }
  return null;
}