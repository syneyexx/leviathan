import { useMemo, useState } from "react";
import { buildTree, type LiveBrainEdge, type LiveBrainNode, type TreeNode } from "./brain-live";
import { Panel } from "./brain-shared";

function flatten(node: TreeNode, depth = 0): { node: TreeNode; depth: number }[] {
  const rows = [{ node, depth }];
  for (const child of node.children ?? []) rows.push(...flatten(child, depth + 1));
  return rows;
}

function findNode(node: TreeNode, id: string): TreeNode | null {
  if (node.id === id) return node;
  for (const child of node.children ?? []) {
    const hit = findNode(child, id);
    if (hit) return hit;
  }
  return null;
}

export function BrainTreeView({
  nodes,
  onSelect,
}: {
  nodes: LiveBrainNode[];
  edges?: LiveBrainEdge[];
  onToast?: (msg: string) => void;
  onSelect?: (id: string) => void;
}) {
  const root = useMemo(() => buildTree(nodes), [nodes]);
  const [selectedId, setSelectedId] = useState(root.id);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([root.id]));
  const [opts, setOpts] = useState({ labels: true, counts: true });

  const selected = findNode(root, selectedId) ?? root;
  const categories = useMemo(() => root.children ?? [], [root]);

  const explorer = useMemo(() => {
    const q = query.trim().toLowerCase();
    return flatten(root).filter(({ node, depth }) => {
      if (depth === 0) return true;
      if (depth === 1) return !q || node.label.toLowerCase().includes(q);
      const parent = categories.find((c) => c.children?.some((ch) => ch.id === node.id));
      if (parent && !expanded.has(parent.id)) return false;
      if (!q) return true;
      return node.label.toLowerCase().includes(q);
    });
  }, [root, expanded, query, categories]);

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="lv-bt">
      <div className="lv-bt-grid">
        <Panel title="Knowledge Tree" className="lv-bt-explorer">
          <input
            className="lv-br-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search nodes..."
            aria-label="Search tree nodes"
          />
          {nodes.length === 0 ? (
            <p className="lv-br-muted" style={{ padding: 8 }}>
              No projection nodes yet.
            </p>
          ) : (
            <ul className="lv-bt-list">
              {explorer.map(({ node, depth }) => {
                const hasChildren = Boolean(node.children?.length);
                const open = expanded.has(node.id);
                return (
                  <li key={node.id} style={{ paddingLeft: depth * 14 }}>
                    <button
                      type="button"
                      className={`lv-bt-item${selectedId === node.id ? " is-active" : ""}`}
                      onClick={() => {
                        setSelectedId(node.id);
                        onSelect?.(node.id);
                        if (hasChildren) toggleExpand(node.id);
                      }}
                    >
                      {hasChildren ? (
                        <span className="lv-bt-caret">{open ? "▾" : "▸"}</span>
                      ) : (
                        <span className="lv-bt-caret" />
                      )}
                      <span className="lv-bt-swatch" style={{ background: node.color }} />
                      <span className="lv-bt-label">{node.label}</span>
                      {opts.counts ? <span className="lv-bt-count">({node.count.toLocaleString()})</span> : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel
          className="lv-bt-canvas"
          title="LEVIATHAN Knowledge Tree"
          action={
            <div className="lv-bt-canvas-tools">
              <span className="lv-br-muted">Live · {nodes.length} nodes</span>
              <button
                type="button"
                className="lv-br-chip"
                onClick={() => setExpanded(new Set([root.id, ...categories.map((c) => c.id)]))}
              >
                Expand All
              </button>
              <button type="button" className="lv-br-chip" onClick={() => setExpanded(new Set([root.id]))}>
                Collapse
              </button>
            </div>
          }
        >
          <div className="lv-bt-canvas-body">
            <div className="lv-bt-hub" style={{ borderColor: root.color }}>
              <strong>{root.label}</strong>
              <span>{root.count} nodes</span>
            </div>
            <div className="lv-bt-rings">
              {categories.map((cat) => (
                <button
                  key={cat.id}
                  type="button"
                  className={`lv-bt-ring${selectedId === cat.id ? " is-active" : ""}`}
                  style={{ borderColor: cat.color }}
                  onClick={() => {
                    setSelectedId(cat.id);
                    setExpanded((prev) => new Set(prev).add(cat.id));
                  }}
                >
                  <strong>{cat.label}</strong>
                  <span>{cat.count}</span>
                </button>
              ))}
            </div>
          </div>
        </Panel>

        <Panel title="Node Detail" className="lv-bt-detail">
          <h3>{selected.label}</h3>
          <p className="lv-br-muted">{selected.description || "Projection node"}</p>
          <dl className="lv-bt-meta">
            <div>
              <dt>Count</dt>
              <dd>{selected.count}</dd>
            </div>
            <div>
              <dt>Id</dt>
              <dd style={{ fontSize: 11 }}>{selected.id}</dd>
            </div>
          </dl>
          {selected.tags?.length ? (
            <div className="lv-br-chip-row">
              {selected.tags.map((tag) => (
                <span key={tag} className="lv-br-chip is-active">
                  {tag}
                </span>
              ))}
            </div>
          ) : null}
          <label className="lv-br-field" style={{ marginTop: 12 }}>
            <span>Show counts</span>
            <input
              type="checkbox"
              checked={opts.counts}
              onChange={(e) => setOpts((o) => ({ ...o, counts: e.target.checked }))}
            />
          </label>
        </Panel>
      </div>
    </div>
  );
}
