/**
 * Leviathan V2 Console — canonical `/console`.
 * ObservabilityHub control plane. No page-local CSS file.
 */

import { ConsoleBottomAnalytics } from "../../components/console/ConsoleBottomAnalytics";
import { ConsoleFiltersPanel } from "../../components/console/ConsoleFiltersPanel";
import { ConsoleCommandsDialog, ConsoleResourcesDialog } from "../../components/console/ConsoleModals";
import { ConsoleMetrics } from "../../components/console/ConsoleMetrics";
import { ConsolePanel } from "../../components/console/ConsolePanel";
import { ConsoleServicesPanel } from "../../components/console/ConsoleServicesPanel";
import { ErrorState, LoadingState } from "../../components/ui";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { useConsoleWorkspace } from "./useConsoleWorkspace";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

export function ConsolePage() {
  const ws = useConsoleWorkspace();
  const toast = useAppToast();
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="Runtime & Tools / Console"
      v2Subtitle="Live logs, systeemoutput en runtime monitoring van alle services, agents en workers."
      v2Online={ws.connection === "open"}
      v2Refreshing={ws.refreshing}
      onV2Refresh={() => {
        void ws.refresh();
      }}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page lv-v2-page--console">
        {ws.stale ? (
          <p className="lv-v2-warn" role="status">
            Stale — aggregates vernieuwen mislukt; laatste goede snapshot behouden.
          </p>
        ) : null}

        <ConsoleMetrics
          overview={ws.overview}
          loading={ws.loading && !ws.overview}
          unmeasured={Boolean(ws.overviewError && !ws.overview?.stats.totals)}
        />

        {ws.overviewError && !ws.overview ? (
          <ErrorState title="Console aggregates laden mislukt" detail={ws.overviewError} />
        ) : null}
        {ws.loading && !ws.overview ? <LoadingState label="Console laden…" /> : null}

        <section className="lv-v2-console-workspace" aria-label="Console werkruimte">
          <ConsolePanel
            events={ws.events}
            connection={ws.connection}
            paused={ws.paused}
            onTogglePause={() => {
              ws.setPaused((v) => !v);
              toast(ws.paused ? "Console hervat" : "Console gepauzeerd");
            }}
            onClear={ws.clearView}
            onExport={() => {
              void ws.exportLogs();
            }}
            exportBusy={ws.exportBusy}
            autoScroll={ws.autoScroll}
            onAutoScrollChange={ws.setAutoScroll}
            search={ws.search}
            onSearch={ws.setSearch}
            level={ws.level}
            onLevel={ws.setLevel}
            service={ws.service}
            onService={ws.setService}
            category={ws.category}
            onCategory={ws.setCategory}
            serviceOptions={ws.serviceOptions}
            categoryOptions={ws.categoryOptions}
            severityChip={ws.severityChip}
            onSeverityChip={ws.setSeverityChip}
            focusSequence={ws.focusSequence}
            menuOpen={ws.menuOpen}
            onMenuOpen={ws.setMenuOpen}
            onOpenCommands={() => ws.setCommandsOpen(true)}
            onOpenResources={() => ws.setResourcesOpen(true)}
            liveError={ws.liveError}
          />

          <aside className="lv-v2-console-side" aria-label="Filters en services">
            <ConsoleFiltersPanel
              quickFilter={ws.quickFilter}
              onQuickFilter={ws.setQuickFilter}
              errorCount={ws.bufferCounts.errors}
              warningCount={ws.bufferCounts.warnings}
              overviewErrors={ws.overview?.metrics.errors_24h ?? null}
              overviewWarnings={ws.overview?.metrics.warnings_24h ?? null}
              timeRange={ws.timeRange}
              timeRangeOptions={ws.timeRangeOptions}
              onTimeRange={ws.setTimeRange}
              autoScroll={ws.autoScroll}
              onAutoScroll={ws.setAutoScroll}
              regexText={ws.regexText}
              onRegexText={ws.setRegexText}
              regexError={ws.regexError}
            />
            <ConsoleServicesPanel services={ws.overview?.services ?? []} />
          </aside>
        </section>

        <ConsoleBottomAnalytics
          overview={ws.overview}
          onFocusError={(seq) => {
            ws.applyErrorFocus(seq);
            toast("Foutfilter actief — event gefocust");
          }}
        />
      </main>

      <ConsoleCommandsDialog
        open={ws.commandsOpen}
        onClose={() => ws.setCommandsOpen(false)}
        command={ws.command}
        onCommand={ws.setCommand}
        commands={ws.commands}
        busy={ws.cmdBusy}
        history={ws.history}
        onRun={(raw) => {
          void ws.runCommand(raw);
        }}
      />
      <ConsoleResourcesDialog
        open={ws.resourcesOpen}
        onClose={() => ws.setResourcesOpen(false)}
        sample={ws.telemetrySample}
        error={ws.telemetryError}
      />
    </AppShell>
  );
}
