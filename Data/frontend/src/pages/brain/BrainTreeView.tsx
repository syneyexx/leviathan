import { useMemo, useState } from "react";
import { TREE_FOOTER, TREE_ROOT, type TreeNode } from "./brain-mock";
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

export function BrainTreeView({ onToast }: { onToast: (msg: string) => void }) {
  const [selectedId, setSelectedId] = useState("core");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(["leviathan", "core", "models", "data", "tools", "research"]),
  );
  const [opts, setOpts] = useState({ labels: true, icons: true, counts: true, animate: true });

  const selected = findNode(TREE_ROOT, selectedId) ?? TREE_ROOT;

  const explorer = useMemo(() => {
    const q = query.trim().toLowerCase();
    const categories = TREE_ROOT.children ?? [];
    return flatten(TREE_ROOT).filter(({ node, depth }) => {
      if (depth === 0) return true;
      if (depth > 1) {
        const parent = categories.find((c) => c.children?.some((ch) => ch.id === node.id));
        if (parent && !expanded.has(parent.id)) return false;
      }
      if (!q) return true;
      return node.label.toLowerCase().includes(q);
    });
  }, [expanded, query]);

  const categories = TREE_ROOT.children ?? [];

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
                      if (hasChildren) toggleExpand(node.id);
                    }}
                  >
                    {hasChildren ? <span className="lv-bt-caret">{open ? "▾" : "▸"}</span> : <span className="lv-bt-caret" />}
                    <span className="lv-bt-swatch" style={{ background: node.color }} />
                    <span className="lv-bt-label">{node.label}</span>
                    {opts.counts ? <span className="lv-bt-count">({node.count.toLocaleString()})</span> : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </Panel>

        <Panel
          className="lv-bt-canvas"
          title="LEVIATHAN Knowledge Tree"
          action={
            <div className="lv-bt-canvas-tools">
              <span className="lv-br-muted">Hierarchical View · 1,842 nodes</span>
              <button type="button" className="lv-br-chip" onClick={() => setExpanded(new Set(["leviathan", ...categories.map((c) => c.id)]))}>
                Expand All
              </button>
              <button type="button" className="lv-br-chip" onClick={() => setExpanded(new Set(["leviathan"]))}>
                Collapse All
              </button>
              <button type="button" className="lv-br-chip">
                Depth: 3
              </button>
              <button type="button" className="lv-br-chip">
                Tree Layout
              </button>
            </div>
          }
        >
          <div className="lv-bt-viz">
            <div className="lv-bt-root" style={{ borderColor: TREE_ROOT.color }}>
              <strong>{TREE_ROOT.label}</strong>
              <span>{TREE_ROOT.count.toLocaleString()} nodes</span>
            </div>
            <div className="lv-bt-branches">
              {categories.map((cat) => (
                <div key={cat.id} className="lv-bt-branch">
                  <button
                    type="button"
                    className={`lv-bt-branch-head${selectedId === cat.id ? " is-active" : ""}`}
                    style={{ borderColor: cat.color, boxShadow: `0 0 18px ${cat.color}33` }}
                    onClick={() => setSelectedId(cat.id)}
                  >
                    <strong>{cat.label}</strong>
                    <span>{cat.count} nodes</span>
                  </button>
                  <ul className="lv-bt-branch-kids">
                    {(cat.children ?? []).map((child) => (
                      <li key={child.id}>
                        <button
                          type="button"
                          className={`lv-bt-leaf${selectedId === child.id ? " is-active" : ""}`}
                          style={{ borderLeftColor: cat.color }}
                          onClick={() => setSelectedId(child.id)}
                        >
                          <span>{child.label}</span>
                          <em>{child.count} nodes</em>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </Panel>

        <Panel
          title="Node Details"
          className="lv-bt-details"
          action={
            <button type="button" className="lv-br-icon-btn" aria-label="Close" onClick={() => onToast("Close details")}>
              ×
            </button>
          }
        >
          <div className="lv-bt-detail-head">
            <span className="lv-bt-detail-icon" style={{ borderColor: selected.color }} />
            <div>
              <h3>{selected.label}</h3>
              <span className="lv-br-badge">Category</span>
            </div>
          </div>
          <p className="lv-br-crumb">LEVIATHAN › {selected.label}</p>
          <p className="lv-br-desc">
            {selected.description ?? "Linked knowledge node in the Leviathan hierarchy."}
          </p>
          <dl className="lv-br-meta">
            <div>
              <dt>Type</dt>
              <dd>Category</dd>
            </div>
            <div>
              <dt>Node ID</dt>
              <dd>{selected.id}</dd>
            </div>
            <div>
              <dt>Parent</dt>
              <dd>LEVIATHAN</dd>
            </div>
            <div>
              <dt>Child Nodes</dt>
              <dd>{selected.children?.length ?? 0}</dd>
            </div>
            <div>
              <dt>Total Descendants</dt>
              <dd>{selected.count}</dd>
            </div>
            <div>
              <dt>Depth Level</dt>
              <dd>1</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>Jan 12, 2024</dd>
            </div>
            <div>
              <dt>Last Modified</dt>
              <dd>Sep 17, 2024</dd>
            </div>
            <div>
              <dt>Relevance Score</dt>
              <dd>0.96</dd>
            </div>
          </dl>
          {selected.tags ? (
            <div className="lv-br-tags">
              {selected.tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
              <button type="button" onClick={() => onToast("Add tag")}>
                +
              </button>
            </div>
          ) : null}
          <div className="lv-bt-actions">
            <button type="button" className="lv-br-btn" onClick={() => onToast("Open in Chat")}>
              Open in Chat
            </button>
            <button type="button" className="lv-br-btn" onClick={() => onToast("Explore Branch")}>
              Explore Branch
            </button>
            <button type="button" className="lv-br-btn" onClick={() => onToast("Add Child Node")}>
              + Add Child Node
            </button>
            <button type="button" className="lv-br-btn" onClick={() => onToast("Create Sibling")}>
              Create Sibling
            </button>
            <button type="button" className="lv-br-btn is-danger" onClick={() => onToast("Delete Node")}>
              Delete Node
            </button>
          </div>
        </Panel>
      </div>

      <footer className="lv-bt-footer">
        <div>
          <strong>Tree Overview</strong>
          <span>Hierarchical knowledge structure for LEVIATHAN.</span>
        </div>
        <div className="lv-bt-footer-stats">
          <span>
            <strong>{TREE_FOOTER.total}</strong> Total Nodes
          </span>
          <span>
            <strong>{TREE_FOOTER.branches}</strong> Visible Branches
          </span>
          <span>
            <strong>{TREE_FOOTER.leaves}</strong> Leaf Nodes
          </span>
          <span>
            <strong>{TREE_FOOTER.depth}</strong> Max Depth Levels
          </span>
        </div>
        <div className="lv-bt-toggles">
          {(
            [
              ["labels", "Show Node Labels"],
              ["icons", "Show Icons"],
              ["counts", "Show Counts"],
              ["animate", "Animate Expansion"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`lv-br-toggle${opts[key] ? " is-on" : ""}`}
              onClick={() => setOpts((o) => ({ ...o, [key]: !o[key] }))}
            >
              <span />
              {label}
            </button>
          ))}
        </div>
      </footer>
    </div>
  );
}
