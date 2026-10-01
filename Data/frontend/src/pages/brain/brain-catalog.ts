import type { LiveBrainNode, LiveBrainEdge } from './brain-live';

export type CatalogCursor = { source: number; offset: number };
export type BrainCatalogPage = {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  page: { next_source: number; next_offset: number; complete: boolean };
  /** Backend truth flags — preserved separately from client pagination state. */
  truth?: Record<string, boolean>;
};

export type BrainCatalogResult = {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  /** Merged backend truth plus client `pagination_complete` (never invents catalog_complete/bounded_projection). */
  truth: Record<string, boolean>;
};

/** Traverse bounded owner pages, retaining real cross-page edges and authoritative metadata. */
export async function loadBrainCatalog(
  fetchPage: (cursor: CatalogCursor, signal: AbortSignal) => Promise<BrainCatalogPage>,
  signal: AbortSignal,
  progress?: (nodes: LiveBrainNode[], edges: LiveBrainEdge[], truth: Record<string, boolean>) => void,
): Promise<BrainCatalogResult> {
  const nodes = new Map<string, LiveBrainNode>();
  const edges = new Map<string, LiveBrainEdge>();
  const seen = new Set<string>();
  let backendTruth: Record<string, boolean> = {};
  let cursor: CatalogCursor = { source: 0, offset: 0 };
  for (;;) {
    signal.throwIfAborted();
    const key = `${cursor.source}:${cursor.offset}`;
    if (seen.has(key)) throw new Error('Brain catalogus herhaalt een pagina; laden gestopt.');
    seen.add(key);
    const page = await fetchPage(cursor, signal);
    signal.throwIfAborted();
    if (!Array.isArray(page.nodes) || !Array.isArray(page.edges) || typeof page.page?.complete !== 'boolean') {
      throw new Error('Brain catalogus niet beschikbaar. Werk ook de backend bij.');
    }
    if (page.truth && typeof page.truth === 'object') {
      backendTruth = { ...backendTruth, ...page.truth };
    }
    for (const node of page.nodes) {
      const previous = nodes.get(node.id);
      if (!previous || !node.meta?.catalog_reference || previous.meta?.catalog_reference) nodes.set(node.id, node);
    }
    for (const edge of page.edges) edges.set(edge.id, edge);
    progress?.([...nodes.values()], [...edges.values()], {
      ...backendTruth,
      pagination_complete: false,
    });
    if (page.page.complete) break;
    const {next_source: source, next_offset: offset} = page.page;
    if (!Number.isInteger(source) || !Number.isInteger(offset) || source < cursor.source || offset < 0 || (source === cursor.source && offset <= cursor.offset)) {
      throw new Error('Ongeldige vervolgpagina in Brain catalogus.');
    }
    cursor = { source, offset };
  }
  return {
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    truth: {
      ...backendTruth,
      pagination_complete: true,
    },
  };
}
