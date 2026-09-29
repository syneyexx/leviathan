import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BrainBottomGrid } from "../components/brain/BrainBottomGrid";
import { BrainHero } from "../components/brain/BrainHero";
import { BrainMetrics } from "../components/brain/BrainMetrics";
import { BrainNetworkSection } from "../components/brain/BrainNetworkSection";
import { Button } from "../components/ui";
import { useBrainOverview } from "../hooks/useBrainOverview";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import { BrainAnalyticsView } from "./brain/BrainAnalyticsView";
import { BrainClustersView } from "./brain/BrainClustersView";
import { BrainGraphCanvas } from "./brain/BrainGraphCanvas";
import { BrainSpaceCanvas } from "./brain/BrainSpaceCanvas";
import { BrainTimelineView } from "./brain/BrainTimelineView";
import { BrainTreeView } from "./brain/BrainTreeView";
import { BRAIN_VIEWS, type BrainView } from "./brain/brain-mock";
import {
  prefersReducedMotion,
  type BrainSpaceDomain,
  type BrainSpaceMode,
} from "./brain/brain-space";

type GraphPresentation = "dna" | "celestial" | "technical";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/**
 * Leviathan V2 Brain / Knowledge Network.
 * Default surface matches Screen 1; advanced graph modes remain reachable.
 */
export function BrainPage() {
  const toast = useAppToast();
  const overview = useBrainOverview({ enabled: true });
  const frozen = visualFixtureNow();

  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [view, setView] = useState<BrainView>("Graph");
  const [graphPresentation, setGraphPresentation] = useState<GraphPresentation>("dna");
  const [spaceMode, setSpaceMode] = useState<BrainSpaceMode>("galaxy");
  const [showLabels, setShowLabels] = useState(true);
  const [showClusters, setShowClusters] = useState(true);
  const [showDepth, setShowDepth] = useState(false);
  const [showRelations, setShowRelations] = useState(true);
  const [orbitMotion, setOrbitMotion] = useState(() => !prefersReducedMotion());
  const [knowledgeAge, setKnowledgeAge] = useState(1);
  const [isolatedDomain, setIsolatedDomain] = useState<BrainSpaceDomain | null>(null);

  const openAdvancedGraph = useCallback(() => {
    setAdvancedOpen(true);
    setView("Graph");
    setGraphPresentation("dna");
    const el = document.getElementById("brain-advanced-graph");
    el?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  }, []);

  const visibleNodeIds = useMemo(() => new Set(overview.nodes.map((n) => n.id)), [overview.nodes]);
  const visibleEdges = overview.edges.filter(
    (e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target),
  );

  return (
    <AppShell
      variant="v2"
      v2Title="Brain / Knowledge Network"
      v2Subtitle="Kennis, geheugen en redenering voor autonome intelligentie."
      v2Online={overview.online}
      v2Refreshing={overview.refreshing}
      onV2Refresh={() => {
        void overview.refresh();
      }}
      v2StatusRows={overview.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page lv-v2-page--brain">
        <BrainHero onOpenGraph={openAdvancedGraph} />
        <BrainMetrics overview={overview} />
        <BrainNetworkSection overview={overview} />
        <BrainBottomGrid overview={overview} />

        <section className="lv-v2-brain-advanced" id="brain-advanced-graph" aria-label="Geavanceerde Brain weergaven">
          <div className="lv-v2-brain-advanced__head">
            <h3>Geavanceerde kennisgrafiek</h3>
            <div className="lv-v2-brain-advanced__actions">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setAdvancedOpen((v) => !v)}
                aria-expanded={advancedOpen}
              >
                {advancedOpen ? "Verberg geavanceerd" : "Toon geavanceerd"}
              </Button>
              <Link className="lv-v2-brain-link" to="/knowledge">
                Knowledge Library
              </Link>
              <Link className="lv-v2-brain-link" to="/evidence">
                Evidence Vault
              </Link>
            </div>
          </div>

          {advancedOpen ? (
            <div className="lv-v2-brain-advanced__body">
              <div className="lv-v2-brain-advanced__tabs" role="tablist" aria-label="Brain weergaven">
                {BRAIN_VIEWS.map((v) => (
                  <button
                    key={v}
                    type="button"
                    role="tab"
                    aria-selected={view === v}
                    className={`lv-v2-dna__tab${view === v ? " is-active" : ""}`}
                    onClick={() => setView(v)}
                  >
                    {v}
                  </button>
                ))}
              </div>

              {view === "Tree" ? (
                <BrainTreeView
                  nodes={overview.nodes}
                  edges={overview.edges}
                  onToast={toast}
                  onSelect={overview.setSelectedId}
                />
              ) : null}
              {view === "Timeline" ? (
                <BrainTimelineView nodes={overview.nodes} edges={overview.edges} onToast={toast} />
              ) : null}
              {view === "Clusters" ? (
                <BrainClustersView
                  nodes={overview.nodes}
                  edges={overview.edges}
                  onToast={toast}
                />
              ) : null}
              {view === "Analytics" ? (
                <BrainAnalyticsView
                  nodes={overview.nodes}
                  edges={overview.edges}
                  stats={overview.stats}
                  onToast={toast}
                />
              ) : null}

              {view === "Graph" ? (
                <div className="lv-v2-brain-advanced__graph">
                  <div className="lv-v2-brain-advanced__pres" role="group" aria-label="Graph presentation">
                    {(
                      [
                        ["dna", "DNA"],
                        ["celestial", "Celestial"],
                        ["technical", "Technical"],
                      ] as const
                    ).map(([id, label]) => (
                      <button
                        key={id}
                        type="button"
                        className={graphPresentation === id ? "is-active" : ""}
                        aria-pressed={graphPresentation === id}
                        onClick={() => setGraphPresentation(id)}
                      >
                        {label}
                      </button>
                    ))}
                    <button type="button" aria-pressed={showLabels} onClick={() => setShowLabels((v) => !v)}>
                      Labels
                    </button>
                    <button type="button" aria-pressed={showClusters} onClick={() => setShowClusters((v) => !v)}>
                      Clusters
                    </button>
                    <button type="button" aria-pressed={showDepth} onClick={() => setShowDepth((v) => !v)}>
                      Depth
                    </button>
                    <button type="button" aria-pressed={orbitMotion} onClick={() => setOrbitMotion((v) => !v)}>
                      {graphPresentation === "technical" ? "Physics" : "Orbit"}
                    </button>
                  </div>

                  {graphPresentation === "celestial" ? (
                    <>
                      <div className="lv-v2-brain-advanced__pres" role="group" aria-label="Celestial mode">
                        {(["galaxy", "systems", "orbits"] as const).map((value) => (
                          <button
                            key={value}
                            type="button"
                            className={spaceMode === value ? "is-active" : ""}
                            aria-pressed={spaceMode === value}
                            onClick={() => {
                              setSpaceMode(value);
                              setIsolatedDomain(null);
                            }}
                          >
                            {value.charAt(0).toUpperCase() + value.slice(1)}
                          </button>
                        ))}
                        <button
                          type="button"
                          className={showRelations ? "is-active" : ""}
                          aria-pressed={showRelations}
                          onClick={() => setShowRelations((v) => !v)}
                        >
                          Relations
                        </button>
                      </div>
                      <div className="lv-v2-brain-advanced__canvas">
                        <BrainSpaceCanvas
                          nodes={overview.nodes}
                          edges={visibleEdges}
                          selectedId={overview.selectedId}
                          onSelect={overview.setSelectedId}
                          mode={spaceMode}
                          knowledgeAge={knowledgeAge}
                          paused={!orbitMotion}
                          showLabels={showLabels}
                          showClusters={showClusters}
                          showDepth={showDepth}
                          showRelations={showRelations}
                          isolatedDomain={isolatedDomain}
                          onIsolatedDomainChange={setIsolatedDomain}
                        />
                        <div className="lv-v2-brain-advanced__age">
                          <strong>KNOWLEDGE AGE</strong>
                          <input
                            type="range"
                            min={0}
                            max={100}
                            value={Math.round(knowledgeAge * 100)}
                            aria-label="Knowledge age"
                            onChange={(event) => setKnowledgeAge(Number(event.target.value) / 100)}
                          />
                          <b>{Math.round(knowledgeAge * 100)}%</b>
                        </div>
                      </div>
                    </>
                  ) : null}

                  {graphPresentation === "technical" ? (
                    <div className="lv-v2-brain-advanced__canvas">
                      <BrainGraphCanvas
                        nodes={overview.nodes}
                        edges={visibleEdges}
                        selectedId={overview.selectedId}
                        onSelect={overview.setSelectedId}
                        showLabels={showLabels}
                        showClusters={showClusters}
                        showDepth={showDepth}
                        physicsLayout={orbitMotion}
                      />
                    </div>
                  ) : null}

                  {graphPresentation === "dna" ? (
                    <p className="lv-v2-muted">
                      DNA is de standaard V2-visualisatie hierboven. Gebruik Celestial of Technical voor
                      legacy presentaties, of Tree / Timeline / Clusters / Analytics via de tabs.
                    </p>
                  ) : null}

                  <div className="lv-v2-brain-advanced__quick">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        toast("Brain is read-only; maak nodes via Knowledge, Research of Datasets.")
                      }
                    >
                      + Add Node
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => setView("Clusters")}>
                      Create Cluster
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setShowDepth(true);
                        setGraphPresentation("technical");
                      }}
                    >
                      Find Related
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => setView("Analytics")}>
                      Analyze Graph
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      </main>
    </AppShell>
  );
}
