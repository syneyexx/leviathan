import { ModelsActionsCard } from "../../components/models/ModelsActionsCard";
import { ModelsAdvancedCard } from "../../components/models/ModelsAdvancedCard";
import { ModelsCatalogList } from "../../components/models/ModelsCatalogList";
import { ModelsHardwareCard } from "../../components/models/ModelsHardwareCard";
import { ModelsLoadConfigCard } from "../../components/models/ModelsLoadConfigCard";
import { ModelsMultiGpuCard } from "../../components/models/ModelsMultiGpuCard";
import { ModelsOptimizationPanel } from "../../components/models/ModelsOptimizationPanel";
import { ModelsPerformanceCard } from "../../components/models/ModelsPerformanceCard";
import { ModelsResourceEstimateCard } from "../../components/models/ModelsResourceEstimateCard";
import { ModelsRuntimeProviderCard } from "../../components/models/ModelsRuntimeProviderCard";
import { ModelsVramReserveCard } from "../../components/models/ModelsVramReserveCard";
import { Button, Dialog } from "../../components/ui";
import { useModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { AppShell } from "../../layouts/AppShell";
import { ModelGatewayPanel } from "./ModelGatewayPanel";
import { ModelImportDialog } from "./ModelImportDialog";
import { ModelResidencyPanel } from "./ModelResidencyPanel";
import { ModelRouterPanel } from "./ModelRouterPanel";
import { ProviderManager } from "./ProviderManager";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/**
 * Leviathan V2 LM / Models — canonical `/models`.
 * Screen 1 runtime + hardware + load configuration + optimizer workspace.
 * No page-local CSS — layout lives in `styles/leviathan-v2.css` under
 * `.lv-v2-page--models`.
 */
export function ModelsPage() {
  const ws = useModelsWorkspace();
  const frozen = visualFixtureNow();

  const actions = (
    <>
      <Button variant="secondary" size="sm" loading={ws.refreshing} onClick={() => void ws.refresh()}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M20 12a8 8 0 1 1-2.2-5.5" />
          <path d="M20 4v5h-5" />
        </svg>
        Refresh
      </Button>
      <Button variant="primary" size="sm" onClick={() => ws.setShowImport(true)}>
        + Model toevoegen
      </Button>
    </>
  );

  return (
    <AppShell
      variant="v2"
      v2Title="LM / Models"
      v2Subtitle="Beheer, configureer en optimaliseer lokale modellen"
      v2Online={ws.online}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
      v2Actions={actions}
      v2HideRefresh
    >
      <main className="lv-v2-page lv-v2-page--models">
        <section className="lv-v2-models-row lv-v2-models-row--1" aria-label="Runtime en hardware">
          <ModelsRuntimeProviderCard ws={ws} onOpenProviders={() => ws.openDrawer("providers")} />
          <ModelsHardwareCard ws={ws} />
          <ModelsVramReserveCard ws={ws} />
        </section>

        <section className="lv-v2-models-row lv-v2-models-row--2" aria-label="Model en load configuratie">
          <ModelsCatalogList ws={ws} />
          <ModelsLoadConfigCard ws={ws} />
          <ModelsMultiGpuCard ws={ws} />
          <ModelsAdvancedCard ws={ws} />
        </section>

        <section className="lv-v2-models-row lv-v2-models-row--3" aria-label="Optimalisatie">
          <ModelsOptimizationPanel ws={ws} onManageProfiles={() => ws.openDrawer("residency")} />
        </section>

        <section className="lv-v2-models-row lv-v2-models-row--4" aria-label="Resources, performance en acties">
          <ModelsResourceEstimateCard ws={ws} />
          <ModelsPerformanceCard ws={ws} />
          <ModelsActionsCard ws={ws} />
        </section>

        {ws.error ? (
          <p className="lv-v2-models-cap-note" role="alert">
            {ws.error}
          </p>
        ) : null}

        <section className="lv-v2-models-manage" aria-label="Beheer en diagnostiek">
          <button type="button" className="lv-v2-models-manage__link" onClick={() => ws.openDrawer("providers")}>
            Providers beheren
          </button>
          <button type="button" className="lv-v2-models-manage__link" onClick={() => ws.openDrawer("gateway")}>
            Model Gateway
          </button>
          <button type="button" className="lv-v2-models-manage__link" onClick={() => ws.openDrawer("router")}>
            Router
          </button>
          <button type="button" className="lv-v2-models-manage__link" onClick={() => ws.openDrawer("residency")}>
            Residency-beleid
          </button>
        </section>
      </main>

      {ws.showImport ? (
        <ModelImportDialog
          providers={ws.providers}
          onClose={() => ws.setShowImport(false)}
          onDone={async () => {
            ws.setShowImport(false);
            await ws.refresh();
          }}
        />
      ) : null}

      <Dialog
        open={ws.drawer === "providers"}
        title="Providers beheren"
        onClose={ws.closeDrawer}
        cancelLabel="Sluiten"
      >
        <ProviderManager providers={ws.providers} onChanged={() => ws.refresh()} />
      </Dialog>

      <Dialog open={ws.drawer === "gateway"} title="Model Gateway" onClose={ws.closeDrawer} cancelLabel="Sluiten">
        <ModelGatewayPanel gateway={ws.gateway} />
      </Dialog>

      <Dialog open={ws.drawer === "router"} title="Router" onClose={ws.closeDrawer} cancelLabel="Sluiten">
        {ws.router ? (
          <ModelRouterPanel router={ws.router} models={ws.models} onSave={ws.saveRouter} />
        ) : (
          <p className="lv-v2-muted">Router configuratie onbeschikbaar.</p>
        )}
      </Dialog>

      <Dialog
        open={ws.drawer === "residency"}
        title="Residency-beleid & geteste profielen"
        onClose={ws.closeDrawer}
        cancelLabel="Sluiten"
      >
        <ModelResidencyPanel
          residency={ws.residency}
          binding={ws.runtimeBinding}
          policy={ws.residencyPolicy}
          busy={ws.busy != null}
          onSavePolicy={ws.saveResidencyPolicy}
        />
      </Dialog>
    </AppShell>
  );
}
