/** Derive Brain secondary views from live /api/brain/graph projection. */

export type LiveBrainNode = {
  id: string;
  type: string;
  label: string;
  created_at?: string | null;
  meta?: Record<string, unknown>;
};

export type LiveBrainEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
};

const TYPE_COLORS: Record<string, string> = {
  "knowledge.document": "#F0C875",
  evidence: "#22C9D6",
  "research.project": "#D6A957",
  dataset: "#E45959",
  module: "#9B8CFF",
  capability: "#DB8A34",
  "mcp.server": "#4285E8",
  "mcp.tool": "#60A5FA",
  workflow: "#20DC8C",
  atlas: "#F472B6",
  run: "#94A3B8",
  memory: "#22C9D6",
  conversation: "#A1A1AA",
  project: "#D6A957",
  concept: "#F0C875",
  model: "#B45CFF",
  agent: "#8E63FF",
  tool: "#DB8A34",
  code: "#20DC8C",
};

export function colorForType(type: string): string {
  return TYPE_COLORS[type] || TYPE_COLORS[type.split(".")[0]] || "#A1A1AA";
}

export type TreeNodeKind = "root" | "domain" | "type" | "node";

export type TreeNode = {
  id: string;
  label: string;
  count: number;
  color: string;
  kind: TreeNodeKind;
  children?: TreeNode[];
  description?: string;
  tags?: string[];
  nodeType?: string;
  createdAt?: string | null;
  meta?: Record<string, unknown>;
};

type TreeDomain = {
  id: string;
  label: string;
  color: string;
  description: string;
};

const TREE_DOMAINS: readonly TreeDomain[] = [
  {
    id: "core-concepts",
    label: "Core Concepts",
    color: "#F0C875",
    description: "Foundational knowledge, memory and concepts that form LEVIATHAN's working intelligence.",
  },
  {
    id: "ai-models",
    label: "AI Models",
    color: "#B45CFF",
    description: "Models, agents, training and evaluation structures available to LEVIATHAN.",
  },
  {
    id: "data-information",
    label: "Data & Information",
    color: "#22C9D6",
    description: "Datasets, evidence, embeddings and other information-bearing stores.",
  },
  {
    id: "tools-systems",
    label: "Tools & Systems",
    color: "#DB8A34",
    description: "Capabilities, MCP integrations, workflows and operational tooling.",
  },
  {
    id: "research",
    label: "Research",
    color: "#20DC8C",
    description: "Research projects, runs, findings and project knowledge.",
  },
] as const;

function domainIdForType(type: string): string {
  const t = type.toLowerCase();
  if (
    t.includes("research") ||
    t === "run" ||
    t === "project" ||
    t.includes("experiment") ||
    t.includes("hypothesis") ||
    t.includes("finding")
  ) {
    return "research";
  }
  if (
    t.includes("dataset") ||
    t.includes("evidence") ||
    t.includes("vector") ||
    t.includes("embedding") ||
    t.includes("atlas") ||
    t.includes("data.") ||
    t.includes("information")
  ) {
    return "data-information";
  }
  if (
    t.includes("mcp") ||
    t.includes("capability") ||
    t.includes("workflow") ||
    t === "tool" ||
    t.includes("automation") ||
    t.includes("integration") ||
    t.includes("api") ||
    t === "code"
  ) {
    return "tools-systems";
  }
  if (
    t.includes("model") ||
    t.includes("agent") ||
    t.includes("llm") ||
    t.includes("training") ||
    t.includes("fine") ||
    t.includes("evaluation") ||
    t === "module"
  ) {
    return "ai-models";
  }
  return "core-concepts";
}

function prettyTypeLabel(type: string): string {
  return type
    .split(/[._-]+/g)
    .filter(Boolean)
    .map((part) => {
      const upper = part.toUpperCase();
      if (["AI", "API", "LLM", "MCP", "RAG"].includes(upper)) return upper;
      return `${part.charAt(0).toUpperCase()}${part.slice(1)}`;
    })
    .join(" ");
}

export function buildTree(nodes: LiveBrainNode[]): TreeNode {
  const byType = new Map<string, LiveBrainNode[]>();
  for (const n of nodes) {
    const list = byType.get(n.type) ?? [];
    list.push(n);
    byType.set(n.type, list);
  }

  const grouped = new Map<string, TreeNode[]>();
  for (const domain of TREE_DOMAINS) grouped.set(domain.id, []);

  for (const [type, group] of [...byType.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))) {
    const domainId = domainIdForType(type);
    const typeNode: TreeNode = {
      id: `type:${type}`,
      label: prettyTypeLabel(type),
      count: group.length,
      color: colorForType(type),
      kind: "type",
      nodeType: type,
      description: `${group.length} live projection node${group.length === 1 ? "" : "s"} of type ${type}.`,
      tags: [type.split(".")[0], "live"],
      children: group
        .slice()
        .sort((a, b) => a.label.localeCompare(b.label))
        .map((n) => ({
          id: n.id,
          label: n.label,
          count: 1,
          color: colorForType(n.type),
          kind: "node" as const,
          nodeType: n.type,
          createdAt: n.created_at,
          meta: n.meta,
          description:
            typeof n.meta?.description === "string"
              ? n.meta.description
              : n.created_at
                ? `Created ${n.created_at}`
                : "Live Brain projection node.",
          tags: [n.type, ...Object.keys(n.meta || {}).slice(0, 4)],
        })),
    };
    grouped.get(domainId)?.push(typeNode);
  }

  const children: TreeNode[] = TREE_DOMAINS.map((domain) => {
    const domainChildren = grouped.get(domain.id) ?? [];
    return {
      id: `domain:${domain.id}`,
      label: domain.label,
      count: domainChildren.reduce((sum, child) => sum + child.count, 0),
      color: domain.color,
      kind: "domain",
      description: domain.description,
      tags: [domain.id, "category"],
      children: domainChildren,
    };
  });

  return {
    id: "leviathan",
    label: "LEVIATHAN",
    count: nodes.length,
    color: "#D4AF37",
    kind: "root",
    description: "Bounded Brain projection over LEVIATHAN's authoritative stores.",
    tags: ["brain", "knowledge", "live"],
    children,
  };
}

export type TimelineEvent = {
  id: string;
  type: string;
  title: string;
  body: string;
  at: string;
  relevance?: boolean;
  color: string;
};

export function buildTimeline(nodes: LiveBrainNode[]): TimelineEvent[] {
  return nodes
    .filter((n) => n.created_at)
    .slice()
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
    .map((n) => ({
      id: n.id,
      type: n.type,
      title: n.label,
      body: `${n.type}${n.meta?.status ? ` · ${String(n.meta.status)}` : ""}`,
      at: String(n.created_at),
      relevance: Boolean(n.meta?.status === "READY" || n.meta?.status === "VERIFIED" || n.meta?.status === "completed"),
      color: colorForType(n.type),
    }));
}

export type ClusterRow = {
  id: string;
  label: string;
  nodes: number;
  color: string;
  sample: string[];
  internalEdges?: number;
};

export function buildClusters(nodes: LiveBrainNode[], edges: LiveBrainEdge[]): ClusterRow[] {
  const byType = new Map<string, LiveBrainNode[]>();
  for (const n of nodes) {
    const list = byType.get(n.type) ?? [];
    list.push(n);
    byType.set(n.type, list);
  }
  return [...byType.entries()]
    .map(([type, group]) => {
      const ids = new Set(group.map((g) => g.id));
      const internal = edges.filter((e) => ids.has(e.source) && ids.has(e.target)).length;
      return {
        id: type,
        label: type,
        nodes: group.length,
        color: colorForType(type),
        sample: group.slice(0, 5).map((g) => g.label),
        internalEdges: internal,
      };
    })
    .sort((a, b) => b.nodes - a.nodes);
}

export function buildAnalytics(
  nodes: LiveBrainNode[],
  edges: LiveBrainEdge[],
  stats: Record<string, unknown> | null,
) {
  const byType = (stats?.by_type as Record<string, number> | undefined) ?? {};
  const typeEntries =
    Object.keys(byType).length > 0
      ? Object.entries(byType)
      : [...nodes.reduce((m, n) => m.set(n.type, (m.get(n.type) ?? 0) + 1), new Map<string, number>())];

  const total = nodes.length || 1;
  const composition = typeEntries
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([label, count], i) => ({
      label,
      value: Math.round((count / total) * 100),
      color: colorForType(label),
      count,
      index: i,
    }));

  const dated = nodes
    .filter((n) => n.created_at)
    .map((n) => String(n.created_at).slice(0, 10))
    .sort();
  const buckets = new Map<string, number>();
  for (const d of dated) buckets.set(d, (buckets.get(d) ?? 0) + 1);
  const labels = [...buckets.keys()].slice(-12);
  let running = dated.length - labels.reduce((s, d) => s + (buckets.get(d) ?? 0), 0);
  const series = labels.map((d) => {
    running += buckets.get(d) ?? 0;
    return running;
  });

  const relationCounts = new Map<string, number>();
  for (const e of edges) relationCounts.set(e.relation, (relationCounts.get(e.relation) ?? 0) + 1);

  return {
    nodeCount: (stats?.node_count as number | undefined) ?? nodes.length,
    edgeCount: (stats?.edge_count as number | undefined) ?? edges.length,
    typeCount: typeEntries.length,
    composition,
    growth: { labels, series: series.length ? series : [0] },
    relations: [...relationCounts.entries()].sort((a, b) => b[1] - a[1]),
    typeEntries: typeEntries.sort((a, b) => b[1] - a[1]),
  };
}
