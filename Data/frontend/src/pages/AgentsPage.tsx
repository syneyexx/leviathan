/**
 * Leviathan V2 Agents — canonical `/agents` orchestration console.
 * Screen 1 presentation + preserved Fleet / Worker Fabric / mission control.
 * No page-local CSS; styles live in leviathan-v2.css under `.lv-v2-page--agents`.
 */

import { AgentDirectoryPanel } from "../components/agents/AgentDirectoryPanel";
import { AgentsActivityFeed } from "../components/agents/AgentsActivityFeed";
import { AgentsArchitecturePanel } from "../components/agents/AgentsArchitecturePanel";
import { AgentsHero } from "../components/agents/AgentsHero";
import { AgentsMetrics } from "../components/agents/AgentsMetrics";
import { AgentsMissionsPanel } from "../components/agents/AgentsMissionsPanel";
import { AgentsStatusBar } from "../components/agents/AgentsStatusBar";
import { AgentsToolPermissions } from "../components/agents/AgentsToolPermissions";
import { SelectedAgentInspector } from "../components/agents/SelectedAgentInspector";
import { Button, ErrorState } from "../components/ui";
import { useAgentsWorkspace } from "../hooks/useAgentsWorkspace";
import { AppShell } from "../layouts/AppShell";
import { Modal } from "./agents/agentsUi";
import { AgentArchitecturePanel } from "./agents/AgentArchitecturePanel";
import { AgentEditorModal } from "./agents/AgentEditorModal";
import { AgentPerformancePanel } from "./agents/AgentPerformancePanel";
import { FailureRetryPanel } from "./agents/FailureRetryPanel";
import { LaunchMissionModal } from "./agents/LaunchMissionModal";
import { LeviathanCoreModal } from "./agents/LeviathanCoreModal";
import { MissionDetailModal } from "./agents/MissionQueuePanel";
import { SignalsPanel } from "./agents/SignalsPanel";
import { SpawnWorkerModal } from "./agents/SpawnWorkerModal";
import { TeamDistributionPanel } from "./agents/TeamDistributionPanel";
import { TradeOrchestraSection } from "./agents/TradeOrchestraSection";
import { WorkerPoolsPanel } from "./agents/WorkerPoolsPanel";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

export function AgentsPage() {
  const ws = useAgentsWorkspace();
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="LLM / Agents"
      v2Subtitle="Autonome agents, samenwerking, missies en uitvoering."
      v2Online={ws.live}
      v2Refreshing={ws.refreshing}
      onV2Refresh={() => {
        void ws.loadAll({ manual: true });
      }}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
      v2Actions={
        <>
          <Button variant="secondary" size="sm" disabled={ws.busy} onClick={ws.openCreate}>
            + Agent toevoegen
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={ws.busy}
            onClick={() => ws.setAdvancedOpen(true)}
            title="Worker Fabric, Signal Fabric, performance, trade orchestra"
          >
            Geavanceerd
          </Button>
        </>
      }
    >
      <main className="lv-v2-page lv-v2-page--agents">
        <AgentsHero
          onNewMission={() => ws.setLaunchOpen(true)}
          onOpenRegistry={ws.focusDirectory}
          canLaunch={ws.anyLaunchable}
        />

        {ws.summary && !ws.summary.agentsEnabled ? (
          <div className="lv-v2-banner is-warn" role="status">
            Agents feature flag is OFF (`LEVIATHAN_FEATURE_AGENTS`). Definitions remain manageable;
            mission execution is unavailable.
          </div>
        ) : null}
        {ws.loadError ? (
          <ErrorState title="Agent fleet laden mislukt" detail={ws.loadError} />
        ) : null}
        {ws.dashboardError && !ws.loadError ? (
          <div className="lv-v2-banner is-warn" role="status">
            Dashboard: {ws.dashboardError}. Fleet data blijft beschikbaar; KPI&apos;s tonen — / UNMEASURED.
          </div>
        ) : null}

        <AgentsMetrics ws={ws} />

        <section className="lv-v2-agents-main" aria-label="Agents werkruimte">
          <AgentDirectoryPanel ws={ws} />
          <AgentsArchitecturePanel ws={ws} />
          <SelectedAgentInspector ws={ws} />
        </section>

        <section className="lv-v2-agents-lower" aria-label="Missies en activiteit">
          <AgentsActivityFeed ws={ws} />
          <AgentsMissionsPanel ws={ws} />
          <AgentsToolPermissions ws={ws} />
        </section>

        <AgentsStatusBar ws={ws} />

        <div className="lv-v2-agents-ops" aria-label="Fleet operator acties">
          <Button variant="ghost" size="sm" disabled={ws.busy} onClick={() => void ws.onStartAll()}>
            Start all (USER)
          </Button>
          <Button variant="ghost" size="sm" disabled={ws.busy} onClick={() => void ws.onPauseAll()}>
            Pause all (USER)
          </Button>
          <Button variant="ghost" size="sm" disabled={ws.busy} onClick={() => void ws.onReconcile()}>
            Reconcile
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={ws.busy}
            onClick={() => ws.setSpawnPoolId(ws.pools[0]?.poolId ?? "")}
          >
            Worker pools
          </Button>
          <Button variant="ghost" size="sm" disabled={ws.busy} onClick={() => ws.setTradeOpen(true)}>
            Trade Orchestra
          </Button>
        </div>
      </main>

      {ws.archView ? (
        <div
          className="lv-v2-agents-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="Agent Architecture volledig overzicht"
          onClick={() => ws.setArchView(false)}
        >
          <div className="lv-v2-agents-overlay__inner" onClick={(e) => e.stopPropagation()}>
            <AgentArchitecturePanel
              agents={ws.archFleet}
              systemEntries={ws.systemEntries}
              pools={ws.pools}
              workersAvailable={Boolean(ws.workersSummary?.available)}
              infra={ws.infra}
              selectedId={ws.selectedAgentId}
              live={ws.live}
              focused
              onSelect={ws.setSelectedAgentId}
              onOpenCore={() => ws.setCoreOpen(true)}
              onOpenPool={(pid) => ws.setSpawnPoolId(pid)}
              onClose={() => ws.setArchView(false)}
            />
          </div>
        </div>
      ) : null}

      {ws.advancedOpen ? (
        <div
          className="lv-v2-agents-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="Geavanceerde Agents panelen"
          onClick={() => ws.setAdvancedOpen(false)}
        >
          <div className="lv-v2-agents-overlay__inner is-wide" onClick={(e) => e.stopPropagation()}>
            <div className="lv-v2-agents-advanced">
              <header className="lv-v2-agents-advanced__head">
                <h2>Geavanceerd · Worker Fabric / Signals / Performance</h2>
                <Button variant="ghost" size="sm" onClick={() => ws.setAdvancedOpen(false)}>
                  Sluiten
                </Button>
              </header>
              <WorkerPoolsPanel
                workers={ws.workersSummary}
                fabric={ws.fabricDashboard}
                busy={ws.busy}
                onScale={(pid, n) => void ws.onScale(pid, n)}
                onManage={(pid) => ws.setSpawnPoolId(pid ?? ws.pools[0]?.poolId ?? "")}
              />
              <SignalsPanel
                compact
                selectedAgentId={ws.selectedAgentId || null}
                selectedMissionId={ws.selectedMissionId || null}
                agentNameById={ws.agentNameById}
              />
              <div className="lv-v2-agents-advanced__grid">
                <AgentPerformancePanel
                  dashboard={ws.dashboard}
                  windowHours={ws.windowHours}
                  onWindow={ws.setWindowHours}
                />
                <TeamDistributionPanel dashboard={ws.dashboard} />
                <FailureRetryPanel
                  dashboard={ws.dashboard}
                  windowHours={ws.failureWindowHours}
                  onWindow={ws.setFailureWindowHours}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {ws.coreOpen ? (
        <LeviathanCoreModal
          systemEntries={ws.systemEntries}
          agents={ws.agents}
          summary={ws.summary}
          dashboard={ws.dashboard}
          failureWindowHours={ws.failureWindowHours}
          modelsCount={ws.models.length}
          capabilitiesCount={ws.capabilities.length}
          onSelectEntry={(id) => {
            ws.setSelectedAgentId(id);
            ws.setShowAll(true);
            ws.setCoreOpen(false);
          }}
          onClose={() => ws.setCoreOpen(false)}
        />
      ) : null}

      {ws.spawnPoolId !== null ? (
        <SpawnWorkerModal
          pools={ws.pools}
          initialPoolId={ws.spawnPoolId || undefined}
          supervisorHealth={ws.workersSummary?.supervisorHealth ?? null}
          busy={ws.busy}
          onScale={(pid, n) => void ws.onScale(pid, n)}
          onClose={() => ws.setSpawnPoolId(null)}
        />
      ) : null}

      {ws.launchOpen ? (
        <LaunchMissionModal
          agents={ws.liveFleet}
          initialAgentId={ws.selectedLaunchable ? ws.selectedAgentId : ""}
          agentsEnabled={ws.summary?.agentsEnabled}
          busy={ws.busy}
          onLaunch={(id, payload) => void ws.onLaunch(id, payload)}
          onClose={() => ws.setLaunchOpen(false)}
        />
      ) : null}

      {ws.displayedMissionDetail ? (
        <MissionDetailModal
          detail={ws.displayedMissionDetail}
          missions={ws.missions}
          agentById={ws.agentById}
          busy={ws.busy}
          onSelectMission={ws.selectMission}
          onCancel={(id) => void ws.onCancelMission(id)}
          onClose={() => ws.setMissionDetailOpen(false)}
        />
      ) : null}

      {ws.editorOpen ? (
        <AgentEditorModal
          mode={ws.editorMode}
          draft={ws.draft}
          setDraft={ws.setDraft}
          agents={ws.agents}
          models={ws.models}
          capabilities={ws.capabilities}
          knowledgeDocs={ws.knowledgeDocs}
          editingId={ws.editorMode === "edit" ? ws.selectedAgentId : undefined}
          busy={ws.busy}
          onSave={() => void ws.onSaveEditor()}
          onClose={() => ws.setEditorOpen(false)}
        />
      ) : null}

      {ws.tradeOpen ? (
        <Modal wide title="Trade Orchestra / Trading Agents (paper)" onClose={() => ws.setTradeOpen(false)}>
          <TradeOrchestraSection
            onSelectAgent={(id) => {
              ws.setSelectedAgentId(id);
              ws.setTradeOpen(false);
            }}
            onChanged={() => void ws.loadAll()}
          />
        </Modal>
      ) : null}
    </AppShell>
  );
}
