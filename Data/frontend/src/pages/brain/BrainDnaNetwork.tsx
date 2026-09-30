/**
 * Kennis Netwerk DNA surface — helix canvas, activation, controls, workbench.
 * Keeps .lv-v2-dna for existing E2E selectors.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import {
  BRAIN_FILTER_TABS,
  filterNodesByCategory,
  type BrainCategoryFilter,
} from "./brain-categories";
import { BrainLivingNetworkCanvas } from "./BrainLivingNetworkCanvas";
import {
  BrainNetworkWorkbench,
  startResearchFromGap,
  type ResearchActionState,
} from "./BrainNetworkWorkbench";
import type { KnowledgeActivationState } from "./brain-activation";
import { findKnowledgeGaps, memoryScopeLabel, scopeFromNode } from "./brain-knowledge-model";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";
import { api } from "../../api/client";

export type BrainDnaNetworkProps = {
  nodes: readonly LiveBrainNode[];
  edges: readonly LiveBrainEdge[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  categoryFilter: BrainCategoryFilter;
  onCategoryFilterChange: (filter: BrainCategoryFilter) => void;
  preferredFocalId?: string | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  reducedMotion?: boolean;
  className?: string;
  /** Chat→Brain activation projection (optional). */
  activation?: KnowledgeActivationState | null;
  onFollowRequest?: (requestId: string) => void;
  graphTruncated?: boolean;
  graphMaxNodes?: number | null;
  searchQuery?: string;
};

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

const MEMORY_SCOPES = [
  { id: "all", label: "Alles" },
  { id: "CONVERSATION", label: "Gesprek" },
  { id: "PROJECT", label: "Project" },
  { id: "USER", label: "Persoonlijk" },
  { id: "ORCHESTRATOR_SHARED", label: "Gedeeld" },
  { id: "GLOBAL", label: "Globaal" },
] as const;

export function BrainDnaNetwork({
  nodes,
  edges,
  selectedId,
  onSelect,
  categoryFilter,
  onCategoryFilterChange,
  loading = false,
  error = null,
  onRetry,
  reducedMotion,
  className = "",
  activation = null,
  onFollowRequest,
  graphTruncated = false,
  graphMaxNodes = null,
}: BrainDnaNetworkProps) {
  const shellRef = useRef<HTMLDivElement>(null);
  const motionOff = reducedMotion ?? prefersReducedMotion();
  const [mode, setMode] = useState<"dna" | "network">("dna");
  const [paused, setPaused] = useState(motionOff);
  const pausePref = useRef(motionOff);
  const [speed, setSpeed] = useState(0.24);
  const [twist, setTwist] = useState(1.6);
  const [showRelations, setShowRelations] = useState(false);
  const [showLabels, setShowLabels] = useState(true);
  const [scopeFilter, setScopeFilter] = useState<string>("all");
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [researchAction, setResearchAction] = useState<ResearchActionState>({
    status: "idle",
    jobId: null,
    projectId: null,
    message: "Nog geen onderzoekstaak gestart.",
  });

  const filteredNodes = useMemo(() => {
    let list = filterNodesByCategory(nodes, categoryFilter);
    if (scopeFilter !== "all") {
      list = list.filter((n) => {
        const scope = scopeFromNode(n);
        if (!scope) return false;
        return scope.toUpperCase() === scopeFilter;
      });
    }
    return list;
  }, [nodes, categoryFilter, scopeFilter]);

  const filteredIds = useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes]);
  const filteredEdges = useMemo(
    () => edges.filter((e) => filteredIds.has(e.source) && filteredIds.has(e.target)),
    [edges, filteredIds],
  );

  const activeNodeIds = useMemo(
    () => new Set(activation?.activeNodeIds ?? []),
    [activation?.activeNodeIds],
  );

  const gaps = useMemo(
    () => findKnowledgeGaps(filteredNodes, filteredEdges, { truncated: graphTruncated, maxNodes: graphMaxNodes }),
    [filteredNodes, filteredEdges, graphTruncated, graphMaxNodes],
  );
  const gapNodeIds = useMemo(() => new Set(gaps.map((g) => g.nodeId).filter(Boolean)), [gaps]);

  const [resetToken, setResetToken] = useState(0);
  const focused = useRef(false);
  const visibleActiveCount = [...activeNodeIds].filter((id) => filteredIds.has(id)).length;

  const onSelectNode = useCallback(
    (id: string | null) => {
      onSelect(id);
      if (id) {
        if (!focused.current) pausePref.current = paused;
        focused.current = true;
        setPaused(true);
      } else {
        focused.current = false;
        setPaused(pausePref.current);
      }
    },
    [onSelect, paused],
  );

  const clearFocus = useCallback(() => {
    onSelect(null);
    focused.current = false;
    setSelectedEdgeId(null);
    setPaused(pausePref.current);
  }, [onSelect]);

  const enterFullscreen = useCallback(async () => {
    const el = shellRef.current;
    if (!el) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await el.requestFullscreen();
    } catch {
      // non-fatal
    }
  }, []);

  const resetView = useCallback(() => {
    setResetToken((n) => n + 1);
    focused.current = false;
    onSelect(null);
    setSelectedEdgeId(null);
    setSpeed(0.24);
    setTwist(1.6);
    setMode("dna");
    setPaused(motionOff);
    pausePref.current = motionOff;
  }, [motionOff, onSelect]);

  const phaseTitle = (() => {
    if (!activation || activation.phase === "standby") return "Het geheugen wacht op een vraag";
    if (activation.phase === "retrieving") return "Bezig met retrieval";
    if (activation.phase === "cancelled") return "Retrieval geannuleerd";
    if (activation.phase === "unavailable") return "Retrieval niet beschikbaar";
    if (!activation.identifiersAvailable) return "Activatie zonder node-ids";
    if (activation.activeNodeIds.length) return "Kennis geactiveerd";
    return "Retrieval afgerond";
  })();

  const phaseTag = (activation?.phase ?? "standby").toUpperCase();

  const hasScopeMeta = nodes.some((n) => scopeFromNode(n));

  const rootClass = ["lv-v2-dna", motionOff ? "is-reduced-motion" : "", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={rootClass} ref={shellRef}>
      <div className="lv-v2-dna__tabs" role="tablist" aria-label="Kennisnetwerk filters">
        {BRAIN_FILTER_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={categoryFilter === tab.id}
            className={`lv-v2-dna__tab${categoryFilter === tab.id ? " is-active" : ""}`}
            onClick={() => onCategoryFilterChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="lv-v2-dna__research-bar">
        <div className="lv-v2-dna__display-switch" role="group" aria-label="Netwerkweergave">
          <button
            type="button"
            className={mode === "dna" ? "is-active" : undefined}
            aria-pressed={mode === "dna"}
            onClick={() => setMode("dna")}
          >
            DNA
          </button>
          <button
            type="button"
            className={mode === "network" ? "is-active" : undefined}
            aria-pressed={mode === "network"}
            onClick={() => setMode("network")}
          >
            Relaties
          </button>
        </div>
        <button type="button" className="lv-v2-dna__relations-toggle"
          aria-pressed={showRelations} aria-label="Relatielijnen tonen"
          onClick={() => { setShowRelations((value) => !value); setSelectedEdgeId(null); }}>
          Relatielijnen: {showRelations ? "aan" : "uit"}
        </button>
        {hasScopeMeta ? (
          <label className="lv-v2-dna__scope">
            Geheugen
            <select
              aria-label="Geheugenscope"
              value={scopeFilter}
              onChange={(e) => setScopeFilter(e.target.value)}
            >
              {MEMORY_SCOPES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="lv-v2-muted lv-v2-dna__scope-note">
            Scopefilter wanneer Memory-scope in projectie aanwezig is
          </span>
        )}
        {graphTruncated ? (
          <span className="lv-v2-dna__cap">
            Begrensde projectie{graphMaxNodes != null ? ` · max ${graphMaxNodes}` : ""} ·{" "}
            {filteredNodes.length} zichtbaar
          </span>
        ) : (
          <span className="lv-v2-dna__cap">{filteredNodes.length} nodes</span>
        )}
      </div>

      <div className="lv-v2-dna__stage">
        {error ? (
          <div className="lv-v2-dna__overlay" role="alert">
            <p>{error}</p>
            {onRetry ? (
              <button type="button" className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm" onClick={onRetry}>
                Opnieuw proberen
              </button>
            ) : null}
          </div>
        ) : null}
        {!error && loading && filteredNodes.length === 0 ? (
          <div className="lv-v2-dna__overlay" aria-busy="true">
            <p>Kennisnetwerk laden…</p>
          </div>
        ) : null}
        {!error && !loading && filteredNodes.length === 0 ? (
          <div className="lv-v2-dna__overlay">
            <p>Geen kennisnodes in deze projectie</p>
            {categoryFilter !== "all" || scopeFilter !== "all" ? (
              <button
                type="button"
                className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm"
                onClick={() => {
                  onCategoryFilterChange("all");
                  setScopeFilter("all");
                }}
              >
                Reset filter
              </button>
            ) : null}
          </div>
        ) : null}

        <div className="lv-v2-dna__canvas-heading" aria-hidden="true">
          <span>
            DOUBLE HELIX <b>V3</b>
          </span>
          <span>LIVE VIEW</span>
        </div>
        <div className="lv-v2-dna__strand-key" aria-hidden="true">
          <span>
            <i className="lv-v2-dna__dot lv-v2-dna__dot--source" /> Bronnen &amp; observaties
          </span>
          <span>
            <i className="lv-v2-dna__dot lv-v2-dna__dot--insight" /> Inzichten &amp; hypotheses
          </span>
        </div>

        {selectedId ? (
          <div className="lv-v2-dna__focus-pill">
            <span>Focus actief</span>
            <button type="button" onClick={clearFocus}>
              Verlaat focus ×
            </button>
          </div>
        ) : null}

        <BrainLivingNetworkCanvas
          nodes={nodes}
          edges={edges}
          selectedId={selectedId}
          onSelect={onSelectNode}
          selectedEdgeId={selectedEdgeId}
          onSelectEdge={setSelectedEdgeId}
          activeNodeIds={activeNodeIds}
          gapNodeIds={gapNodeIds}
          mode={mode}
          paused={paused}
          resetToken={resetToken}
          speed={speed}
          twist={twist}
          showLabels={showLabels}
          showRelations={showRelations}
          reducedMotion={motionOff}
          filterPredicate={(n) => filteredIds.has(n.id)}
        />

        <div className="lv-v2-dna__controls" role="toolbar" aria-label="Netwerk bediening">
          <button
            type="button"
            aria-label="Labels tonen of verbergen"
            aria-pressed={showLabels}
            onClick={() => setShowLabels((v) => !v)}
          >
            Aa
          </button>
          <button
            type="button"
            aria-label={paused ? "Rotatie hervatten" : "Rotatie pauzeren"}
            disabled={motionOff}
            title={motionOff ? "Rotatie uit: verminderde beweging ingeschakeld" : undefined}
            aria-pressed={paused}
            onClick={() => {
              setPaused((p) => {
                const next = !p;
                pausePref.current = next;
                return next;
              });
            }}
          >
            {paused ? "▶" : "Ⅱ"}
          </button>
          <button type="button" aria-label="Reset weergave" onClick={resetView} title="Reset">
            ⌖
          </button>
          <button type="button" aria-label="Volledig scherm" onClick={() => void enterFullscreen()}>
            ↗
          </button>
        </div>
      </div>

      <div className="lv-v2-dna__query-status" role="status">
        <div className="lv-v2-dna__query-icon" aria-hidden="true">
          ◎
        </div>
        <div>
          <strong>{phaseTitle}</strong>
          {activation?.connectionNote ? <p>{activation.connectionNote}</p> : null}
          {activeNodeIds.size > 0 ? <p>{visibleActiveCount} van {activeNodeIds.size} opgehaalde kennisnodes zichtbaar; overige nodes vallen buiten deze graaf of filters.</p> : null}
          <p>{activation?.detail ?? "Stel in /chat een vraag; open /brain parallel om activatie te zien."}</p>
        </div>
        <span className="lv-v2-dna__phase-tag">{phaseTag}</span>
      </div>

      {activation && activation.requests.length > 1 ? (
        <label className="lv-v2-dna__request-pick">
          Gevolgde request
          <select
            value={activation.followedRequestId ?? ""}
            onChange={(e) => onFollowRequest?.(e.target.value)}
            aria-label="Kies gevolgd retrieval-request"
          >
            {activation.requests.map((r) => (
              <option key={r.requestId} value={r.requestId}>
                {r.requestId.slice(0, 12)}… · {r.phase}
                {r.conversationId ? ` · ${r.conversationId.slice(0, 8)}` : ""}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <div className="lv-v2-dna__sliders">
        <label>
          Rotatie
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round(speed * 100)}
            onChange={(e) => setSpeed(Number(e.target.value) / 100)}
          />
          <output>{speed.toFixed(2)}×</output>
        </label>
        <label>
          Twist
          <input
            type="range"
            min={100}
            max={240}
            value={Math.round(twist * 100)}
            onChange={(e) => setTwist(Number(e.target.value) / 100)}
          />
          <output>{twist.toFixed(2)}</output>
        </label>
      </div>

      <div className="lv-v2-dna__timeline">
        <div className="lv-v2-dna__timeline-title">
          <span className="lv-v2-eyebrow">Geheugen door de tijd</span>
          <span className="lv-v2-muted">Live</span>
        </div>
        <p className="lv-v2-muted">
          Historische snapshots: niet beschikbaar in het huidige Brain-graphcontract. Geen
          verzonnen reconstructie uit created_at.
        </p>
      </div>

      <BrainNetworkWorkbench
        nodes={filteredNodes}
        edges={filteredEdges}
        selectedId={selectedId}
        selectedEdgeId={selectedEdgeId}
        onSelectNode={onSelectNode}
        onSelectEdge={setSelectedEdgeId}
        graphTruncated={graphTruncated}
        graphMaxNodes={graphMaxNodes}
        historyAvailable={false}
        researchAction={researchAction}
        onStartResearch={(gap, action) => {
          setResearchAction({
            status: "pending",
            jobId: null,
            projectId: null,
            message: "Research aanvraag wordt gestart…",
          });
          void startResearchFromGap(gap, action).then(setResearchAction);
        }}
        onMemoryAction={async (action, memoryId) => {
          try {
            if (action === "archive") {
              await api.archiveMemory(memoryId);
              onRetry?.();
              return { ok: true, message: `Geheugen ${memoryId} gearchiveerd.` };
            }
            await api.revokeMemory(memoryId);
            onRetry?.();
            return { ok: true, message: `Geheugen ${memoryId} ingetrokken.` };
          } catch (err) {
            return {
              ok: false,
              message: err instanceof Error ? err.message : "Memory-mutatie mislukt",
            };
          }
        }}
      />

      {selectedId ? (
        <p className="lv-v2-dna__scope-foot lv-v2-muted">
          Selectie scope: {memoryScopeLabel(scopeFromNode(nodes.find((n) => n.id === selectedId) ?? null))}
        </p>
      ) : null}
    </div>
  );
}
