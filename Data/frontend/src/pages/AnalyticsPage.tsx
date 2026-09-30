/**
 * Leviathan V2 Statistieken — canonical `/analytics` under LLM.
 * Dense operational dashboard. Fixture is test-only.
 */

import { useEffect } from "react";
import { AnalyticsBottomRow } from "../components/analytics/AnalyticsBottomRow";
import { AnalyticsChartsRow } from "../components/analytics/AnalyticsChartsRow";
import { AnalyticsDistributionsRow } from "../components/analytics/AnalyticsDistributionsRow";
import { AnalyticsHero } from "../components/analytics/AnalyticsHero";
import { AnalyticsKpiRow } from "../components/analytics/AnalyticsKpiRow";
import { AnalyticsRankingsRow } from "../components/analytics/AnalyticsRankingsRow";
import { ErrorState } from "../components/ui";
import { AppShell } from "../layouts/AppShell";
import { useAnalyticsWorkspace } from "./analytics/useAnalyticsWorkspace";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

function AnalyticsSearch({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        const el = document.getElementById("lv-an-search") as HTMLInputElement | null;
        el?.focus();
        el?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <form
      className="lv-v2-topbar-search lv-an-topbar-search"
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(value);
      }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <circle cx="11" cy="11" r="6" />
        <path d="M16 16l4 4" />
      </svg>
      <input
        id="lv-an-search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Zoek statistieken, metrics, tijdsperiode..."
        aria-label="Zoek statistieken"
      />
      <kbd>Ctrl + K</kbd>
    </form>
  );
}

export function AnalyticsPage() {
  const ws = useAnalyticsWorkspace();
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="LLM / Statistieken"
      v2Subtitle="Uitgebreide statistieken en inzichten over modellen, agents, datasets, kennis, onderzoek en systeemgebruik."
      v2Online={ws.online}
      v2Refreshing={ws.refreshing || ws.loading}
      onV2Refresh={() => {
        void ws.refresh();
      }}
      v2Now={frozen ? () => frozen : undefined}
      v2Actions={
        <AnalyticsSearch
          value={ws.search}
          onChange={ws.setSearch}
          onSubmit={ws.runSearch}
        />
      }
    >
      <main className="lv-v2-page lv-v2-page--analytics lv-an-main">
        {ws.stale ? (
          <p className="lv-v2-warn" role="status">
            Stale — laatste succesvolle snapshot behouden.
          </p>
        ) : null}

        <AnalyticsHero />
        <AnalyticsKpiRow ws={ws} />

        {ws.error && !ws.dashboard ? (
          <ErrorState title="Statistieken laden mislukt" detail={ws.error} />
        ) : null}
        {ws.error && ws.dashboard ? (
          <p className="lv-v2-warn" role="status">
            {ws.error}
          </p>
        ) : null}

        <AnalyticsChartsRow
          dashboard={ws.dashboard}
          chartRange={ws.chartRange}
          onChartRange={ws.setChartRange}
        />
        <AnalyticsDistributionsRow dashboard={ws.dashboard} />
        <AnalyticsRankingsRow
          dashboard={ws.dashboard}
          rankingRange={ws.rankingRange}
          onRankingRange={ws.setRankingRange}
        />
        <AnalyticsBottomRow dashboard={ws.dashboard} />
      </main>
    </AppShell>
  );
}
