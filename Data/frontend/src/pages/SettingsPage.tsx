/**
 * Leviathan V2 Settings / Systeem Instellingen — canonical `/settings`.
 * Settings Control Plane + Model Control Plane + telemetry. No page-local CSS file.
 */

import { SettingsCategoryContent } from "../components/settings/SettingsCategoryContent";
import { SettingsCategoryNav } from "../components/settings/SettingsCategoryNav";
import { SettingsHero } from "../components/settings/SettingsHero";
import { SettingsMetrics } from "../components/settings/SettingsMetrics";
import { ErrorState } from "../components/ui";
import { useSettingsWorkspace } from "../hooks/useSettingsWorkspace";
import { AppShell } from "../layouts/AppShell";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

export function SettingsPage() {
  const ws = useSettingsWorkspace();
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="Settings / Systeem Instellingen"
      v2Subtitle="Beheer en configureer alle aspecten van je Leviathan AI infrastructuur."
      v2Online={ws.online}
      v2Refreshing={ws.refreshing}
      onV2Refresh={() => {
        void ws.refresh();
      }}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
      pageClass="lv-app--settings-v2"
    >
      <main className="lv-v2-page lv-v2-page--settings">
        {ws.stale ? (
          <p className="lv-v2-warn" role="status">
            Stale — laatste succesvolle update {ws.lastUpdated || "—"}.
          </p>
        ) : null}

        <SettingsHero ws={ws} />
        <SettingsMetrics ws={ws} />

        {ws.loadError ? <ErrorState title="Settings laden mislukt" detail={ws.loadError} /> : null}

        <section className="lv-v2-settings-body" aria-label="Settings workspace">
          <SettingsCategoryNav ws={ws} />
          <div className="lv-v2-settings-body__content">
            <SettingsCategoryContent ws={ws} />
          </div>
        </section>
      </main>
    </AppShell>
  );
}
