/** FINALBETA Brain — live brain graph via useHadesBrain (visual shell preserved). */
"use client";

import { useEffect, useMemo, useState } from "react";
import { useHadesBrain } from "@/components/hades/features/brain/hooks/useHadesBrain";
import {
  formatDate,
  type BrainLayout,
  type BrainLink,
  type BrainNode,
} from "@/lib/hades-api";
import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

type GraphNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  r: number;
  color: string;
  kind: "core" | "cluster" | "leaf";
  apiKind: string;
  description: string;
  tags: string[];
  source: string;
  updated: string;
  created: string;
};

type GraphLink = { from: string; to: string; kind: string; relation: string };

const CX = 520;
const CY = 290;
const VIEW_W = 1040;
const VIEW_H = 580;

const NODE_TYPES = [
  { label: "Concept", color: "#f0b429" },
  { label: "Persoon", color: "#9b5cff" },
  { label: "Locatie", color: "#20c8d4" },
  { label: "Organisatie", color: "#1aa4ff" },
  { label: "Document", color: "#5ec8ff" },
  { label: "Evidence", color: "#e85b5b" },
  { label: "Agent", color: "#20e38d" },
  { label: "Memory", color: "#f08a3a" },
];

const RELATIONS = [
  { label: "Direct", style: "solid" },
  { label: "Indirect", style: "thin" },
  { label: "Verwant", style: "dashed" },
  { label: "Causaal", style: "longdash" },
  { label: "Ondersteunt", style: "dotted" },
  { label: "Tegenstrijdig", style: "contradict" },
];

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = [
  "januari", "februari", "maart", "april", "mei", "juni",
  "juli", "augustus", "september", "oktober", "november", "december",
];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function colorForKind(kind: string): string {
  const k = kind.toLowerCase();
  if (k.includes("core")) return "#f0b429";
  if (k.includes("agent")) return "#20e38d";
  if (k.includes("memory")) return "#f08a3a";
  if (k.includes("evidence")) return "#e85b5b";
  if (k.includes("knowledge") || k.includes("document") || k.includes("note")) return "#5ec8ff";
  if (k.includes("person") || k.includes("user")) return "#9b5cff";
  if (k.includes("project") || k.includes("task") || k.includes("work")) return "#f08a3a";
  if (k.includes("model") || k.includes("language")) return "#20c8d4";
  if (k.includes("chat") || k.includes("system") || k.includes("module")) return "#1aa4ff";
  return "#5ec8ff";
}

function visualKind(kind: string, degree: number): GraphNode["kind"] {
  const k = kind.toLowerCase();
  if (k.includes("core") || kind === "hades") return "core";
  if (degree >= 3 || k.includes("project") || k.includes("module") || k.includes("agent")) return "cluster";
  return "leaf";
}

function relationKind(relation: string): string {
  const r = relation.toLowerCase();
  if (r.includes("contradict") || r.includes("tegen")) return "contradict";
  if (r.includes("support") || r.includes("ondersteun") || r.includes("bevat")) return "support";
  if (r.includes("causal") || r.includes("veroorzaak")) return "causal";
  if (r.includes("indirect")) return "indirect";
  if (r.includes("verwant") || r.includes("related") || r.includes("gerelateerd")) return "related";
  return "direct";
}

function layoutNodes(
  apiNodes: BrainNode[],
  apiLinks: BrainLink[],
  layout: BrainLayout | null | undefined,
): { nodes: GraphNode[]; links: GraphLink[] } {
  const degree = new Map<string, number>();
  for (const link of apiLinks) {
    degree.set(link.source_id, (degree.get(link.source_id) || 0) + 1);
    degree.set(link.target_id, (degree.get(link.target_id) || 0) + 1);
  }
  const posMap = new Map((layout?.positions || []).map((row) => [row.entity_id, row]));
  const hasAnyPos = apiNodes.some(
    (n) => posMap.has(n.id) || (typeof n.pos_x === "number" && typeof n.pos_y === "number"),
  );

  const nodes: GraphNode[] = apiNodes.map((node, index) => {
    const deg = degree.get(node.id) || 0;
    const vk = visualKind(node.kind, deg);
    const fromLayout = posMap.get(node.id);
    let x: number;
    let y: number;
    if (fromLayout) {
      x = fromLayout.pos_x;
      y = fromLayout.pos_y;
    } else if (typeof node.pos_x === "number" && typeof node.pos_y === "number") {
      x = node.pos_x;
      y = node.pos_y;
    } else if (!hasAnyPos) {
      if (vk === "core" || index === 0) {
        x = CX;
        y = CY;
      } else {
        const angle = ((index - 1) / Math.max(1, apiNodes.length - 1)) * Math.PI * 2 - Math.PI / 2;
        const radius = vk === "cluster" ? 165 : 250;
        x = CX + Math.cos(angle) * radius;
        y = CY + Math.sin(angle) * radius;
      }
    } else {
      x = CX + ((index % 8) - 3.5) * 70;
      y = CY + (Math.floor(index / 8) - 2) * 70;
    }

    return {
      id: node.id,
      label: node.label || node.id,
      x,
      y,
      r: vk === "core" ? 34 : vk === "cluster" ? 22 : 10,
      color: colorForKind(node.kind),
      kind: vk,
      apiKind: node.kind,
      description: node.description || "",
      tags: node.tags || [],
      source: node.source || "—",
      updated: node.updated_at || "",
      created: node.created_at || "",
    };
  });

  const links: GraphLink[] = apiLinks.map((link) => ({
    from: link.source_id,
    to: link.target_id,
    kind: relationKind(link.relation || link.relation_kind || ""),
    relation: link.relation || link.relation_kind || "gerelateerd",
  }));

  return { nodes, links };
}

export function BrainPage({ onNavigate }: Props) {
  const [now, setNow] = useState(() => new Date());
  const [selected, setSelected] = useState("");
  const [view, setView] = useState<"Grafiek" | "Lijst" | "Tijdlijn">("Grafiek");
  const [clusterMode, setClusterMode] = useState(true);
  const [evidenceOverlay, setEvidenceOverlay] = useState(false);
  const [depth, setDepth] = useState(2);
  const [zoom, setZoom] = useState(1);
  const [detailTab, setDetailTab] = useState<"related" | "evidence" | "memories">("related");
  const [query, setQuery] = useState("");

  const brain = useHadesBrain("default");
  const { nodes: apiNodes, links: apiLinks, layout, counts, stats, loading, error, refresh } = brain;

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const graph = useMemo(() => layoutNodes(apiNodes, apiLinks, layout), [apiNodes, apiLinks, layout]);

  const visibleNodes = useMemo(() => {
    const q = query.trim().toLowerCase();
    let nodes = graph.nodes;
    if (clusterMode) nodes = nodes.filter((n) => n.kind !== "leaf" || depth > 1);
    if (evidenceOverlay) {
      nodes = nodes.filter(
        (n) =>
          n.apiKind.toLowerCase().includes("evidence") ||
          n.kind === "core" ||
          graph.links.some((l) => l.from === n.id || l.to === n.id),
      );
    }
    if (!q) return nodes;
    return nodes.filter(
      (n) =>
        n.label.toLowerCase().includes(q) ||
        n.description.toLowerCase().includes(q) ||
        n.tags.some((t) => t.toLowerCase().includes(q)) ||
        n.apiKind.toLowerCase().includes(q),
    );
  }, [graph, query, clusterMode, depth, evidenceOverlay]);

  const visibleIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
  const visibleLinks = useMemo(
    () => graph.links.filter((l) => visibleIds.has(l.from) && visibleIds.has(l.to)),
    [graph.links, visibleIds],
  );

  useEffect(() => {
    if (!visibleNodes.length) {
      setSelected("");
      return;
    }
    setSelected((current) =>
      current && visibleNodes.some((n) => n.id === current)
        ? current
        : visibleNodes.find((n) => n.kind === "core")?.id || visibleNodes[0]!.id,
    );
  }, [visibleNodes]);

  const selectedNode = graph.nodes.find((n) => n.id === selected) || null;
  const related = useMemo(() => {
    if (!selectedNode) return [];
    return graph.links
      .filter((l) => l.from === selectedNode.id || l.to === selectedNode.id)
      .map((l) => {
        const otherId = l.from === selectedNode.id ? l.to : l.from;
        const other = graph.nodes.find((n) => n.id === otherId);
        return other ? { id: other.id, name: other.label, score: l.relation, color: other.color } : null;
      })
      .filter((row): row is { id: string; name: string; score: string; color: string } => Boolean(row));
  }, [graph, selectedNode]);

  const body = (
    <div className="brain-page" data-live="brain">
      <div className="brain-welcome">
        <div className="brain-welcome-copy">
          <h1>Brain</h1>
          <p>Mapt intelligentie, geheugen, kennis en verbanden. Van data naar inzicht.</p>
        </div>
        <div className="brain-welcome-mid">
          “Connections create clarity.
          <br />
          Knowledge creates power.”
        </div>
        <div className="brain-clock">
          <div>
            <div className="date">
              {DAYS[now.getDay()]} {now.getDate()} {MONTHS[now.getMonth()]} {now.getFullYear()}
            </div>
            <div className="time">
              {pad(now.getHours())}:{pad(now.getMinutes())}
            </div>
          </div>
          <FbIcon name="bolt" size={22} className="brain-sun" />
        </div>
      </div>

      {error ? (
        <div className="card" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Brain laden mislukt.</strong> {error.message}{" "}
          <button type="button" className="btn btn-sm btn-outline" onClick={() => void refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="brain-stats">
        {[
          ["Brain Nodes", loading ? "…" : String(stats.nodeCount), "brain"],
          ["Actieve Links", loading ? "…" : String(stats.linkCount), "link"],
          ["Memories", loading ? "…" : String(stats.memoryCount), "book"],
          ["Knowledge Items", loading ? "…" : String(stats.knowledgeCount), "database"],
          ["Evidence Records", loading ? "…" : String(stats.evidenceCount), "shield"],
        ].map(([label, value, icon]) => (
          <article className="brain-stat" key={label}>
            <span className="brain-stat-ico"><FbIcon name={icon} size={15} /></span>
            <div>
              <div className="brain-stat-label">{label}</div>
              <div className="brain-stat-value">{value}</div>
            </div>
          </article>
        ))}
        <article className="brain-stat sync">
          <span className="brain-stat-ico sync"><FbIcon name="refresh" size={15} /></span>
          <div>
            <div className="brain-stat-label">Sync Status</div>
            <div className={`brain-stat-value ${error ? "" : "green"}`}>{error ? "Fout" : loading ? "…" : "Online"}</div>
            <div className="brain-stat-hint">
              <button type="button" onClick={() => void refresh()}>Vernieuwen</button>
            </div>
          </div>
        </article>
      </div>

      <div className="brain-toolbar">
        <label className="brain-search">
          <FbIcon name="search" size={14} />
          <input type="search" placeholder="Zoek in de brain..." value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <button type="button" className="brain-filter" data-toast="Filter">Alle types <FbIcon name="chevron" size={12} /></button>
        <button type="button" className="brain-filter" data-toast="Filter">Alle clusters <FbIcon name="chevron" size={12} /></button>
        <button type="button" className="brain-filter" data-toast="Filter">Alle bronnen <FbIcon name="chevron" size={12} /></button>
        <button type="button" className={`brain-toggle${clusterMode ? " on" : ""}`} onClick={() => setClusterMode((v) => !v)}>Cluster mode</button>
        <button type="button" className={`brain-toggle${evidenceOverlay ? " on" : ""}`} onClick={() => setEvidenceOverlay((v) => !v)}>Evidence overlay</button>
        <label className="brain-depth">
          <span>Relatie diepte: {depth}</span>
          <input type="range" min={1} max={4} value={depth} onChange={(event) => setDepth(Number(event.target.value))} />
        </label>
        <div className="brain-view-tools">
          <button type="button" className="brain-icon-btn" aria-label="Fullscreen" data-toast="Fullscreen"><FbIcon name="grid" size={13} /></button>
          <button type="button" className="brain-icon-btn" aria-label="Zoom uit" onClick={() => setZoom((z) => Math.max(0.7, Number((z - 0.1).toFixed(1))))}>−</button>
          <button type="button" className="brain-icon-btn" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(1.4, Number((z + 0.1).toFixed(1))))}>+</button>
          <button type="button" className="brain-icon-btn" aria-label="Centreren" onClick={() => setZoom(1)}><FbIcon name="target" size={13} /></button>
        </div>
      </div>

      <section className="brain-canvas card">
        <div className="brain-legend nodes">
          <div className="brain-legend-title">Node types</div>
          {NODE_TYPES.map((item) => (
            <div key={item.label} className="brain-legend-row"><i style={{ background: item.color }} />{item.label}</div>
          ))}
        </div>
        <div className="brain-legend relations">
          <div className="brain-legend-title">Relaties</div>
          {RELATIONS.map((item) => (
            <div key={item.label} className="brain-legend-row"><span className={`brain-rel-swatch ${item.style}`} />{item.label}</div>
          ))}
        </div>
        <div className="brain-view-switch">
          {(["Grafiek", "Lijst", "Tijdlijn"] as const).map((item) => (
            <button key={item} type="button" className={view === item ? "active" : undefined} onClick={() => setView(item)}>{item}</button>
          ))}
        </div>
        <div className="brain-minimap" aria-hidden="true">
          <svg viewBox="0 0 200 120">
            {visibleLinks.map((link) => {
              const a = graph.nodes.find((n) => n.id === link.from);
              const b = graph.nodes.find((n) => n.id === link.to);
              if (!a || !b) return null;
              return <line key={`mm-${link.from}-${link.to}`} x1={a.x / 5.2} y1={a.y / 4.8} x2={b.x / 5.2} y2={b.y / 4.8} stroke="rgba(90,140,170,.45)" strokeWidth="0.6" />;
            })}
            {visibleNodes.map((node) => (
              <circle key={`mm-${node.id}`} cx={node.x / 5.2} cy={node.y / 4.8} r={node.kind === "core" ? 3.5 : node.kind === "cluster" ? 2.2 : 1.1} fill={node.color} />
            ))}
          </svg>
        </div>

        {loading && !graph.nodes.length ? (
          <div className="brain-alt-view"><p className="muted">Brain-graaf laden…</p></div>
        ) : !graph.nodes.length ? (
          <div className="brain-alt-view"><p className="muted">Geen brain-nodes. Voeg kennis, geheugen of taken toe om de graaf te vullen.</p></div>
        ) : view === "Grafiek" ? (
          <div className="brain-graph-wrap" style={{ transform: `scale(${zoom})` }}>
            <svg className="brain-graph" viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} role="img" aria-label="HADES knowledge graph">
              <defs>
                <radialGradient id="brainGlow" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="rgba(240,180,41,.28)" />
                  <stop offset="100%" stopColor="rgba(240,180,41,0)" />
                </radialGradient>
                <filter id="nodeGlow" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="2.2" result="coloredBlur" />
                  <feMerge><feMergeNode in="coloredBlur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              </defs>
              <circle cx={CX} cy={CY} r="78" fill="url(#brainGlow)" />
              {visibleLinks.map((link) => {
                const a = graph.nodes.find((n) => n.id === link.from);
                const b = graph.nodes.find((n) => n.id === link.to);
                if (!a || !b) return null;
                const stroke = link.kind === "contradict" ? "#e85b5b" : link.kind === "support" ? "rgba(32,227,141,.45)" : "rgba(120,170,195,.38)";
                const dash = link.kind === "related" ? "4 4" : link.kind === "indirect" ? "2 3" : link.kind === "causal" ? "8 4" : link.kind === "contradict" ? "5 3" : undefined;
                return <line key={`${link.from}-${link.to}-${link.relation}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={stroke} strokeWidth={link.kind === "direct" ? 1.6 : 1.1} strokeDasharray={dash} />;
              })}
              {visibleNodes.map((node) => (
                <g key={node.id} className={`brain-node ${node.kind}${selected === node.id ? " selected" : ""}`} onClick={() => setSelected(node.id)} style={{ cursor: "pointer" }}>
                  <circle cx={node.x} cy={node.y} r={node.r + (selected === node.id ? 3 : 0)} fill={`${node.color}22`} stroke={node.color} strokeWidth={selected === node.id ? 2.4 : 1.5} filter={node.kind !== "leaf" ? "url(#nodeGlow)" : undefined} />
                  <circle cx={node.x} cy={node.y} r={Math.max(3, node.r * 0.35)} fill={node.color} />
                  <text x={node.x} y={node.y + node.r + (node.kind === "leaf" ? 12 : 16)} textAnchor="middle" className={`brain-node-label ${node.kind}`}>{node.label}</text>
                </g>
              ))}
            </svg>
          </div>
        ) : (
          <div className="brain-alt-view">
            {view === "Lijst"
              ? visibleNodes.map((node) => (
                  <button key={node.id} type="button" className={`brain-list-row${selected === node.id ? " active" : ""}`} onClick={() => setSelected(node.id)}>
                    <i style={{ background: node.color }} /><span>{node.label}</span><em>{node.apiKind || node.kind}</em>
                  </button>
                ))
              : <p className="muted">Tijdlijn-updates volgen uit live brain-events (nog niet beschikbaar).</p>}
          </div>
        )}

        <div className="brain-graph-foot">
          <span>{counts.nodes ?? graph.nodes.length} nodes · {counts.links ?? graph.links.length} relaties{counts.truncated ? " · truncated" : ""}</span>
          <span className="brain-live"><i />{error ? "Sync fout" : loading ? "Laden…" : "Live sync actief"}</span>
        </div>
      </section>
    </div>
  );

  const inspector = selectedNode ? (
    <>
      <div className="brain-detail-head">
        <h3>Node details</h3>
        <button type="button" className="brain-icon-btn" aria-label="Sluiten" data-toast="Gesloten">×</button>
      </div>
      <section className="insp-section">
        <div className="brain-profile">
          <span className="brain-profile-ico" style={{ borderColor: `${selectedNode.color}88`, color: selectedNode.color }}>
            <FbIcon name={selectedNode.kind === "core" ? "trident" : "brain"} size={18} />
          </span>
          <div>
            <div className="brain-profile-name">{selectedNode.label}</div>
            <div className="brain-profile-badge">{selectedNode.kind === "core" ? "Kern concept" : selectedNode.kind === "cluster" ? "Cluster" : selectedNode.apiKind || "Node"}</div>
          </div>
        </div>
        <p className="brain-profile-copy">{selectedNode.description || `${selectedNode.label} is gekoppeld in de brain-graaf (${selectedNode.apiKind || selectedNode.kind}).`}</p>
        <div className="brain-tags">
          {(selectedNode.tags.length ? selectedNode.tags : ["#brain"]).map((tag) => (
            <span key={tag}>{tag.startsWith("#") ? tag : `#${tag}`}</span>
          ))}
        </div>
        <div className="insp-card" style={{ marginTop: 10 }}>
          <div className="detail-row"><span className="k">Type</span><span className="v">{selectedNode.apiKind || selectedNode.kind}</span></div>
          <div className="detail-row"><span className="k">Status</span><span className="v green">● Actief</span></div>
          <div className="detail-row"><span className="k">Bron</span><span className="v">{selectedNode.source}</span></div>
          <div className="detail-row"><span className="k">Eerste vermelding</span><span className="v">{formatDate(selectedNode.created || null)}</span></div>
          <div className="detail-row"><span className="k">Laatst bijgewerkt</span><span className="v">{formatDate(selectedNode.updated || null)}</span></div>
          <div className="detail-row"><span className="k">Gekoppelde items</span><span className="v">{related.length}</span></div>
        </div>
        <div className="brain-detail-actions">
          <button type="button" className="btn btn-outline" data-fb-page="knowledge"><FbIcon name="book" size={13} /> Open in library</button>
          <button type="button" className="btn btn-outline" data-toast="Meer">Meer acties</button>
        </div>
      </section>
      <section className="insp-section">
        <div className="brain-detail-tabs">
          <button type="button" className={detailTab === "related" ? "active" : undefined} onClick={() => setDetailTab("related")}>Gerelateerde nodes ({related.length})</button>
          <button type="button" className={detailTab === "evidence" ? "active" : undefined} onClick={() => setDetailTab("evidence")}>Evidence</button>
          <button type="button" className={detailTab === "memories" ? "active" : undefined} onClick={() => setDetailTab("memories")}>Memories</button>
        </div>
        <div className="insp-card brain-related">
          {(detailTab === "related" ? related : detailTab === "evidence" ? related.filter((r) => /evidence/i.test(r.score + r.name)) : related.filter((r) => /memory/i.test(r.score + r.name))).map((row) => (
            <button key={row.id} type="button" className="brain-related-row" onClick={() => setSelected(row.id)}>
              <i style={{ background: row.color }} /><span>{row.name}</span><em>{row.score}</em>
            </button>
          ))}
          {!related.length ? <p className="muted">Geen gerelateerde nodes.</p> : null}
        </div>
      </section>
      <p className="quote brain-footer-quote">“Discipline creates freedom.<br />Intelligence multiplies it.”</p>
      <div className="brain-footer-motto">Build a smarter tomorrow. <b>━━</b></div>
    </>
  ) : (
    <>
      <div className="brain-detail-head"><h3>Node details</h3></div>
      <section className="insp-section"><div className="insp-card"><p className="muted">{loading ? "Laden…" : "Geen node geselecteerd."}</p></div></section>
    </>
  );

  return (
    <FinalBetaShell page="brain" body={body} inspector={inspector} onNavigate={onNavigate} appClassName="brain-app" mainClassName="brain-main" />
  );
}
