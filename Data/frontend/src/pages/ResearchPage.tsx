import { ResearchAgentsPanel } from "../components/research/ResearchAgentsPanel";
import { ResearchComposer } from "../components/research/ResearchComposer";
import { ResearchHero } from "../components/research/ResearchHero";
import { ResearchHistory } from "../components/research/ResearchHistory";
import { ResearchKnowledgeStatus } from "../components/research/ResearchKnowledgeStatus";
import { ResearchMetrics } from "../components/research/ResearchMetrics";
import { ResearchRunWorkspace } from "../components/research/ResearchRunWorkspace";
import { ResearchStats } from "../components/research/ResearchStats";
import { ResearchTemplates } from "../components/research/ResearchTemplates";
import { ErrorState } from "../components/ui";
import { useResearchWorkspace } from "../hooks/useResearchWorkspace";
import { AppShell } from "../layouts/AppShell";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/**
 * Leviathan V2 Knowledge Research — canonical `/research`.
 * Screen 1 overview + preserved active-run workspace. No page-local CSS.
 */
export function ResearchPage() {
  const ws = useResearchWorkspace();
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="Kennis / Research"
      v2Subtitle="Diepgaand onderzoek, web research en kennisverzameling voor je AI agents."
      v2Online={ws.online}
      v2Refreshing={ws.refreshing}
      onV2Refresh={() => {
        void ws.refresh();
      }}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page lv-v2-page--research">
        <ResearchHero onNewResearch={ws.focusComposer} onTemplates={ws.focusTemplates} />
        <ResearchMetrics overview={ws} />

        {ws.loadError ? (
          <ErrorState title="Research laden mislukt" detail={ws.loadError} />
        ) : null}

        {ws.workspaceMode === "run" && ws.project ? (
          <div className="lv-v2-research-workspace lv-v2-research-workspace--run">
            <ResearchHistory ws={ws} />
            <div className="lv-v2-research-workspace__run-main">
              <ResearchRunWorkspace ws={ws} />
            </div>
          </div>
        ) : (
          <section className="lv-v2-research-workspace" aria-label="Research overzicht">
            <ResearchHistory ws={ws} />
            <ResearchComposer ws={ws} />
            <ResearchTemplates ws={ws} />
          </section>
        )}

        <section className="lv-v2-research-bottom" aria-label="Research operationeel overzicht">
          <ResearchAgentsPanel ws={ws} />
          <ResearchKnowledgeStatus ws={ws} />
          <ResearchStats ws={ws} />
        </section>
      </main>
    </AppShell>
  );
}
