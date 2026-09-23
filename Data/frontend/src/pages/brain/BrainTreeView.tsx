import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { buildTree, type LiveBrainEdge, type LiveBrainNode, type TreeNode } from "./brain-live";
import { Panel } from "./brain-shared";
import "../../styles/brain-reference.css";

type ViewOptions = {
  labels: boolean;
  counts: boolean;
  icons: boolean;
  animate: boolean;
};

function findNode(node: TreeNode, id: string): TreeNode | null {
  if (node.id === id) return node;
  for (const child of node.children ?? []) {
    const hit = findNode(child, id);
    if (hit) return hit;
  }
  return null;
}

function findParent(node: TreeNode, id: string): TreeNode | null {
  for (const child of node.children ?? []) {
    if (child.id === id) return node;
    const hit = findParent(child, id);
    if (hit) return hit;
  }
  return null;
}

function pathTo(node: TreeNode, id: string, path: TreeNode[] = []): TreeNode[] | null {
  const next = [...path, node];
  if (node.id === id) return next;
  for (const child of node.children ?? []) {
    const hit = pathTo(child, id, next);
    if (hit) return hit;
  }
  return null;
}

function collectIds(node: TreeNode, out = new Set<string>()): Set<string> {
  out.add(node.id);
  for (const child of node.children ?? []) collectIds(child, out);
  return out;
}

function countLeaves(node: TreeNode): number {
  if (!node.children?.length) return node.kind === "node" ? 1 : 0;
  return node.children.reduce((sum, child) => sum + countLeaves(child), 0);
}

function maxDepth(node: TreeNode, depth = 0): number {
  if (!node.children?.length) return depth;
  return Math.max(depth, ...node.children.map((child) => maxDepth(child, depth + 1)));
}

function descendantCount(node: TreeNode): number {
  return (node.children ?? []).reduce((sum, child) => sum + 1 + descendantCount(child), 0);
}

function matchesQuery(node: TreeNode, query: string): boolean {
  if (!query) return true;
  const haystack = `${node.label} ${node.id} ${node.nodeType ?? ""}`.toLowerCase();
  if (haystack.includes(query)) return true;
  return (node.children ?? []).some((child) => matchesQuery(child, query));
}

function flattenVisible(
  node: TreeNode,
  expanded: Set<string>,
  query: string,
  depth = 0,
): Array<{ node: TreeNode; depth: number }> {
  if (query && !matchesQuery(node, query)) return [];
  const rows = [{ node, depth }];
  const shouldExpand = query.length > 0 || expanded.has(node.id);
  if (!shouldExpand) return rows;
  for (const child of node.children ?? []) rows.push(...flattenVisible(child, expanded, query, depth + 1));
  return rows;
}

function formatMetaValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function Chevron({ open = false }: { open?: boolean }) {
  return (
    <svg className="lv-bt-chevron" viewBox="0 0 12 12" aria-hidden="true">
      <path d={open ? "M2.5 4.25 6 7.75l3.5-3.5" : "M4.25 2.5 7.75 6l-3.5 3.5"} />
    </svg>
  );
}

function FolderIcon({ color = "currentColor" }: { color?: string }) {
  return (
    <svg className="lv-bt-folder-icon" viewBox="0 0 18 16" aria-hidden="true" style={{ color }}>
      <path d="M1.5 4.2h5.25l1.4-1.8h8.35v11.4h-15z" />
    </svg>
  );
}

function TridentIcon() {
  return (
    <svg className="lv-bt-trident" viewBox="0 0 32 38" aria-hidden="true">
      <path d="M16 3v28M7 6v7c0 5.4 3.6 9 9 9s9-3.6 9-9V6M4 9l3-3 3 3M22 9l3-3 3 3M13 6l3-3 3 3M12 31l4 4 4-4" />
    </svg>
  );
}

function DomainIcon({ id }: { id: string }) {
  if (id.includes("ai-models")) {
    return (
      <svg className="lv-bt-domain-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M9 4.5A3.5 3.5 0 0 0 5.5 8c0 .5.1 1 .3 1.4A3.8 3.8 0 0 0 4 12.5c0 1.5.8 2.8 2 3.5a3.5 3.5 0 0 0 6 2.4V6.2A3.5 3.5 0 0 0 9 4.5Zm6 0A3.5 3.5 0 0 1 18.5 8c0 .5-.1 1-.3 1.4a3.8 3.8 0 0 1 1.8 3.1c0 1.5-.8 2.8-2 3.5a3.5 3.5 0 0 1-6 2.4V6.2A3.5 3.5 0 0 1 15 4.5Z" />
      </svg>
    );
  }
  if (id.includes("data-information")) {
    return (
      <svg className="lv-bt-domain-icon" viewBox="0 0 24 24" aria-hidden="true">
        <ellipse cx="12" cy="5" rx="7" ry="3" />
        <path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7" />
      </svg>
    );
  }
  if (id.includes("tools-systems")) {
    return (
      <svg className="lv-bt-domain-icon" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="3.4" />
        <path d="M12 2.8v2.1M12 19.1v2.1M2.8 12h2.1M19.1 12h2.1M5.5 5.5 7 7M17 17l1.5 1.5M18.5 5.5 17 7M7 17l-1.5 1.5" />
      </svg>
    );
  }
  if (id.includes("research")) {
    return (
      <svg className="lv-bt-domain-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M9 3h6M10 3v6l-5 10.5A1.7 1.7 0 0 0 6.5 22h11a1.7 1.7 0 0 0 1.5-2.5L14 9V3M8.3 15h7.4" />
      </svg>
    );
  }
  return (
    <svg className="lv-bt-domain-icon" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="5" r="2" />
      <circle cx="5" cy="17" r="2" />
      <circle cx="19" cy="17" r="2" />
      <path d="M12 7v4M12 11 5 15M12 11l7 4" />
    </svg>
  );
}

function OptionToggle({ checked, onChange, children }: { checked: boolean; onChange: () => void; children: string }) {
  return (
    <button className="lv-bt-option" type="button" aria-pressed={checked} onClick={onChange}>
      <span className={`lv-bt-switch${checked ? " is-on" : ""}`} aria-hidden="true">
        <i />
      </span>
      <span>{children}</span>
    </button>
  );
}

export function BrainTreeView({
  nodes,
  onSelect,
  onToast,
}: {
  nodes: LiveBrainNode[];
  edges?: LiveBrainEdge[];
  onToast?: (msg: string) => void;
  onSelect?: (id: string) => void;
}) {
  const navigate = useNavigate();
  const root = useMemo(() => buildTree(nodes), [nodes]);
  const [selectedId, setSelectedId] = useState(root.id);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([root.id]));
  const [opts, setOpts] = useState<ViewOptions>({ labels: true, counts: true, icons: true, animate: true });
  const [depth, setDepth] = useState(3);
  const [compact, setCompact] = useState(false);
  const [hideEmpty, setHideEmpty] = useState(false);

  useEffect(() => {
    setExpanded((prev) => {
      const valid = collectIds(root);
      const next = new Set([...prev].filter((id) => valid.has(id)));
      next.add(root.id);
      for (const domain of root.children ?? []) next.add(domain.id);
      return next;
    });
    if (!findNode(root, selectedId)) setSelectedId(root.id);
  }, [root, selectedId]);

  const selected = findNode(root, selectedId) ?? root;
  const selectedPath = pathTo(root, selected.id) ?? [root];
  const parent = findParent(root, selected.id);
  const queryNormalized = query.trim().toLowerCase();
  const explorer = useMemo(
    () => flattenVisible(root, expanded, queryNormalized),
    [root, expanded, queryNormalized],
  );
  const domains = useMemo(
    () => (root.children ?? []).filter((domain) => !hideEmpty || domain.count > 0),
    [root, hideEmpty],
  );

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectNode = (node: TreeNode, expand = false) => {
    setSelectedId(node.id);
    onSelect?.(node.id);
    if (expand && node.children?.length) setExpanded((prev) => new Set(prev).add(node.id));
  };

  const expandAll = () => setExpanded(collectIds(root));
  const collapseAll = () => setExpanded(new Set([root.id]));

  const openInChat = () => {
    navigate(`/chat?context=${encodeURIComponent(selected.id)}&label=${encodeURIComponent(selected.label)}`);
  };

  const exploreBranch = () => {
    const branch = selected.kind === "node" && parent ? parent : selected;
    setSelectedId(branch.id);
    setExpanded((prev) => {
      const next = new Set(prev);
      for (const item of pathTo(root, branch.id) ?? [root]) next.add(item.id);
      next.add(branch.id);
      return next;
    });
    setQuery("");
  };

  const projectionMutationNotice = (action: string) => {
    onToast?.(`${action}: Brain is a read-only live projection. Mutate the authoritative Knowledge, Research or Dataset source instead.`);
  };

  const updatedAt = selected.meta?.updated_at ?? selected.meta?.modified_at ?? selected.meta?.last_modified;
  const relevance = selected.meta?.relevance_score ?? selected.meta?.score ?? selected.meta?.relevance;
  const typeLabel =
    selected.kind === "domain" ? "Category" : selected.kind === "root" ? "Root" : selected.nodeType ?? "Node";
  const visibleBranchCount = (root.children ?? []).filter((branch) => branch.count > 0).length;

  return (
    <div className={`lv-bt${opts.animate ? " is-animated" : ""}${compact ? " is-compact" : ""}`}>
      <div className="lv-bt-grid">
        <Panel title="Knowledge Tree" className="lv-bt-explorer">
          <div className="lv-bt-search-wrap">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="10.5" cy="10.5" r="6.5" />
              <path d="m15.5 15.5 5 5" />
            </svg>
            <input
              className="lv-br-input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search nodes..."
              aria-label="Search tree nodes"
            />
          </div>
          {nodes.length === 0 ? (
            <p className="lv-br-muted lv-bt-empty">No projection nodes yet.</p>
          ) : (
            <ul className="lv-bt-list">
              {explorer.map(({ node, depth: rowDepth }) => {
                const hasChildren = Boolean(node.children?.length);
                const open = expanded.has(node.id) || queryNormalized.length > 0;
                const isRoot = node.kind === "root";
                const isDomain = node.kind === "domain";
                return (
                  <li key={node.id} className={`lv-bt-row is-${node.kind}`} style={{ paddingLeft: rowDepth * 12 }}>
                    <button
                      type="button"
                      className={`lv-bt-item${selectedId === node.id ? " is-active" : ""}`}
                      onClick={() => {
                        selectNode(node);
                        if (hasChildren) toggleExpand(node.id);
                      }}
                    >
                      <span className="lv-bt-caret">{hasChildren ? <Chevron open={open} /> : null}</span>
                      {opts.icons ? (
                        <span className="lv-bt-tree-icon">
                          <FolderIcon color={isRoot ? "#F0C875" : isDomain ? node.color : "#D6A957"} />
                          {!isRoot ? <i style={{ background: node.color }} /> : null}
                        </span>
                      ) : null}
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
              <button type="button" className="lv-br-chip" onClick={expandAll}>Expand All</button>
              <button type="button" className="lv-br-chip" onClick={collapseAll}>Collapse All</button>
              <select
                className="lv-bt-tool-select"
                value={depth}
                onChange={(event) => setDepth(Number(event.target.value))}
                aria-label="Tree depth"
              >
                <option value={2}>Depth: 2</option>
                <option value={3}>Depth: 3</option>
                <option value={4}>Depth: 4</option>
              </select>
              <button
                type="button"
                className={`lv-br-chip${compact ? " is-active" : ""}`}
                onClick={() => setCompact((value) => !value)}
              >Tree Layout</button>
              <button
                type="button"
                className={`lv-br-chip${hideEmpty ? " is-active" : ""}`}
                onClick={() => setHideEmpty((value) => !value)}
              >Filters</button>
            </div>
          }
        >
          <div className="lv-bt-canvas-body">
            <button className="lv-bt-root-card" type="button" onClick={() => selectNode(root)}>
              {opts.icons ? <TridentIcon /> : null}
              <span>
                {opts.labels ? <strong>{root.label}</strong> : null}
                {opts.counts ? <span>{root.count.toLocaleString()} nodes</span> : null}
              </span>
            </button>

            <div className={`lv-bt-domain-grid is-${domains.length}`}>
              {domains.map((domain) => (
                <section className="lv-bt-domain-column" key={domain.id} style={{ color: domain.color }}>
                  <button
                    type="button"
                    className={`lv-bt-domain-card${selectedId === domain.id ? " is-active" : ""}`}
                    style={{ borderColor: domain.color }}
                    onClick={() => selectNode(domain, true)}
                  >
                    {opts.icons ? <DomainIcon id={domain.id} /> : null}
                    <span>
                      {opts.labels ? <strong>{domain.label}</strong> : null}
                      {opts.counts ? <small>{domain.count.toLocaleString()} nodes</small> : null}
                    </span>
                  </button>

                  {depth >= 3 ? (
                    <div className="lv-bt-domain-children">
                      {(domain.children ?? []).slice(0, compact ? 3 : 5).map((child) => (
                        <button
                          key={child.id}
                          type="button"
                          className={`lv-bt-child-card${selectedId === child.id ? " is-active" : ""}`}
                          onClick={() => selectNode(child, true)}
                        >
                          {opts.icons ? <FolderIcon color={domain.color} /> : null}
                          {opts.labels ? <span>{child.label}</span> : null}
                          {opts.counts ? <small>{child.count.toLocaleString()} nodes</small> : null}
                          <Chevron />
                        </button>
                      ))}
                      {(domain.children ?? []).length === 0 ? <div className="lv-bt-no-children">No live nodes</div> : null}
                      {(domain.children ?? []).length > (compact ? 3 : 5) ? (
                        <button type="button" className="lv-bt-more" onClick={() => selectNode(domain, true)}>
                          + {(domain.children ?? []).length - (compact ? 3 : 5)} more types
                        </button>
                      ) : null}
                      {depth >= 4 && selected.kind === "type" && selectedPath.some((part) => part.id === domain.id) ? (
                        <div className="lv-bt-depth-preview">
                          {(selected.children ?? []).slice(0, 3).map((leaf) => (
                            <button type="button" key={leaf.id} onClick={() => selectNode(leaf)}>{leaf.label}</button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              ))}
            </div>
          </div>
        </Panel>

        <Panel
          title="Node Details"
          className="lv-bt-detail"
          action={
            <button type="button" className="lv-bt-close" aria-label="Reset node details" onClick={() => selectNode(root)}>×</button>
          }
        >
          <div className="lv-bt-detail-head">
            <span className="lv-bt-detail-icon" style={{ borderColor: selected.color, color: selected.color }}>
              {selected.kind === "root" ? <TridentIcon /> : <FolderIcon color={selected.color} />}
            </span>
            <div>
              <h3>{selected.label}</h3>
              <span className="lv-bt-type-badge">{typeLabel}</span>
            </div>
          </div>

          <div className="lv-bt-breadcrumb">
            {selectedPath.map((part, index) => (
              <span key={part.id}>{index ? <i>›</i> : null}{part.label}</span>
            ))}
          </div>

          <p className="lv-bt-description">{selected.description || "Live LEVIATHAN Brain projection node."}</p>

          <dl className="lv-bt-meta">
            <div><dt>Type</dt><dd>{typeLabel}</dd></div>
            <div><dt>Node ID</dt><dd title={selected.id}>{selected.id}</dd></div>
            <div><dt>Parent</dt><dd>{parent?.label ?? "—"}</dd></div>
            <div><dt>Child Nodes</dt><dd>{(selected.children ?? []).length.toLocaleString()}</dd></div>
            <div><dt>Total Descendants</dt><dd>{descendantCount(selected).toLocaleString()}</dd></div>
            <div><dt>Depth Level</dt><dd>{Math.max(0, selectedPath.length - 1)}</dd></div>
            <div><dt>Created</dt><dd>{formatMetaValue(selected.createdAt)}</dd></div>
            <div><dt>Last Modified</dt><dd>{formatMetaValue(updatedAt)}</dd></div>
            <div><dt>Relevance Score</dt><dd>{formatMetaValue(relevance)}</dd></div>
          </dl>

          {selected.tags?.length ? (
            <div className="lv-bt-tags">
              {selected.tags.slice(0, 6).map((tag) => <span key={tag}>{tag}</span>)}
            </div>
          ) : null}

          <div className="lv-bt-actions">
            <button type="button" className="lv-br-btn is-gold" onClick={openInChat}>Open in Chat</button>
            <button type="button" className="lv-br-btn" onClick={exploreBranch}>Explore Branch</button>
            <button type="button" className="lv-br-btn" onClick={() => projectionMutationNotice("Add child node")}>Add Child Node</button>
            <button type="button" className="lv-br-btn" onClick={() => projectionMutationNotice("Create sibling")}>Create Sibling</button>
            <button type="button" className="lv-br-btn is-danger" onClick={() => projectionMutationNotice("Delete node")}>Delete Node</button>
          </div>
        </Panel>
      </div>

      <footer className="lv-bt-footer">
        <div className="lv-bt-overview-copy">
          <strong>Tree Overview</strong>
          <span>Hierarchical live knowledge structure for LEVIATHAN.</span>
        </div>
        <div className="lv-bt-footer-stats">
          <span><b>{root.count.toLocaleString()}</b> Total Nodes</span>
          <span><b>{visibleBranchCount}</b> Visible Branches</span>
          <span><b>{countLeaves(root).toLocaleString()}</b> Leaf Nodes</span>
          <span><b>{maxDepth(root)}</b> Max Depth Levels</span>
        </div>
        <div className="lv-bt-view-options">
          <strong>View Options</strong>
          <div>
            <OptionToggle checked={opts.labels} onChange={() => setOpts((value) => ({ ...value, labels: !value.labels }))}>Show Node Labels</OptionToggle>
            <OptionToggle checked={opts.icons} onChange={() => setOpts((value) => ({ ...value, icons: !value.icons }))}>Show Icons</OptionToggle>
            <OptionToggle checked={opts.counts} onChange={() => setOpts((value) => ({ ...value, counts: !value.counts }))}>Show Counts</OptionToggle>
            <OptionToggle checked={opts.animate} onChange={() => setOpts((value) => ({ ...value, animate: !value.animate }))}>Animate Expansion</OptionToggle>
          </div>
        </div>
      </footer>
    </div>
  );
}
