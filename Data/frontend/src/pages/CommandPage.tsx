import { AppShell } from "../layouts/AppShell";
import { DashboardHero } from "../components/dashboard/DashboardHero";
import { DashboardMetrics } from "../components/dashboard/DashboardMetrics";
import { DashboardOperationsGrid } from "../components/dashboard/DashboardOperationsGrid";
import { DashboardActivityGrid } from "../components/dashboard/DashboardActivityGrid";
import { DashboardBottomGrid } from "../components/dashboard/DashboardBottomGrid";
import { useDashboardOverview } from "../hooks/useDashboardOverview";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/**
 * Leviathan V2 Command Center dashboard.
 * Live backend data only — Screen 1 fixture values are never production defaults.
 */
export function CommandPage() {
  const overview = useDashboardOverview({ enabled: true });
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="Dashboard / Command Center"
      v2Subtitle="Overzicht van je hele AI infrastructuur, agents en activiteiten."
      v2Online={overview.systemStatus.operational ? true : overview.systemStatus.tone === "danger" ? false : null}
      v2Refreshing={overview.refreshing}
      onV2Refresh={() => {
        void overview.refresh();
      }}
      v2StatusRows={overview.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page">
        <DashboardHero />
        <DashboardMetrics overview={overview} />
        <DashboardOperationsGrid overview={overview} />
        <DashboardActivityGrid overview={overview} />
        <DashboardBottomGrid overview={overview} />
      </main>
    </AppShell>
  );
}
