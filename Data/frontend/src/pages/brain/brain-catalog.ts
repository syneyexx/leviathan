import type { LiveBrainNode, LiveBrainEdge } from './brain-live';

export type CatalogCursor = { source: number; offset: number };
export type BrainCatalogPage = {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  page: { next_source: number; next_offset: number; complete: boolean };
};

/** Traverse bounded owner pages, retaining real cross-page edges and authoritative metadata. */
export async function loadBrainCatalog(
  fetchPage: (cursor: CatalogCursor, signal: AbortSignal) => Promise<BrainCatalogPage>,
  signal: AbortSignal,
  progress?: (nodes: LiveBrainNode[], edges: LiveBrainEdge[]) => void,
) {
  const nodes = new Map<string, LiveBrainNode>();
  const edges = new Map<string, LiveBrainEdge>();
  const seen = new Set<string>();
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
    for (const node of page.nodes) {
      const previous = nodes.get(node.id);
      if (!previous || !node.meta?.catalog_reference || previous.meta?.catalog_reference) nodes.set(node.id, node);
    }
    for (const edge of page.edges) edges.set(edge.id, edge);
    progress?.([...nodes.values()], [...edges.values()]);
    if (page.page.complete) break;
    const {next_source: source, next_offset: offset} = page.page;
    if (!Number.isInteger(source) || !Number.isInteger(offset) || source < cursor.source || offset < 0 || (source === cursor.source && offset <= cursor.offset)) {
      throw new Error('Ongeldige vervolgpagina in Brain catalogus.');
    }
    cursor = { source, offset };
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}
