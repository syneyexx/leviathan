/**
 * Leviathan V2 Geheugen — canonical `/memory`.
 * Screen 1 production Memory control plane. No page-local CSS.
 */

import { useNavigate } from "react-router-dom";
import { MemoryBottomRow, MemoryRightColumn } from "../components/memory/MemoryRightColumn";
import { MemoryDialogs } from "../components/memory/MemoryDialogs";
import { MemoryHero } from "../components/memory/MemoryHero";
import { MemoryMetrics } from "../components/memory/MemoryMetrics";
import { MemorySearchAndTable } from "../components/memory/MemorySearchAndTable";
import { ErrorState } from "../components/ui";
import { useMemoryWorkspace } from "../hooks/useMemoryWorkspace";
import { AppShell } from "../layouts/AppShell";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

export function GeheugenPage() {
  const ws = useMemoryWorkspace();
  const navigate = useNavigate();
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="Onderzoek & Kennis / Geheugen"
      v2Subtitle="Beheer, doorzoek en analyseer het langetermijngeheugen van Leviathan."
      v2Online={ws.online}
      v2Refreshing={ws.refreshing}
      onV2Refresh={() => {
        void ws.refresh();
      }}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page lv-v2-page--memory">
        {ws.stale ? (
          <p className="lv-v2-warn" role="status">
            Stale — laatste succesvolle update {ws.lastUpdated || "—"}.
          </p>
        ) : null}

        <MemoryHero
          onNewNote={() => ws.setCreateOpen(true)}
          onBrain={() => navigate("/brain?types=memory")}
        />
        <MemoryMetrics ws={ws} />

        {ws.loadError ? <ErrorState title="Geheugen laden mislukt" detail={ws.loadError} /> : null}

        <section className="lv-v2-memory-workspace" aria-label="Geheugen workspace">
          <MemorySearchAndTable ws={ws} />
          <MemoryRightColumn ws={ws} />
        </section>

        <MemoryBottomRow ws={ws} />
        <MemoryDialogs ws={ws} />
      </main>
    </AppShell>
  );
}
