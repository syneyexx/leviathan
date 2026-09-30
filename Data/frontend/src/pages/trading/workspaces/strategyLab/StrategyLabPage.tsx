/**
 * Strategy Lab (WAVE 5) — native pixel-exact page.
 *
 * Absorbs Research Lab + Strategieën + Simulatie into ONE page via progressive
 * disclosure. NO legacy page embedding. Live trading stays BLOCKED.
 */
import { useMemo, useState } from "react";
import { AppShell } from "../../../../layouts/AppShell";
import { TradingContextBar } from "../TradingContextBar";
import { tradingCenterStatusRows } from "../tradingStatusRows";
import { useTradingContext } from "../useTradingContext";
import { CompareDrawer, CreateLabRunDrawer, AdvancedDrawer } from "./StrategyLabDrawers";
import { StrategyLabView } from "./StrategyLabView";
import type { DiscoveryRow } from "./useStrategyLabData";
import { useStrategyLabData } from "./useStrategyLabData";
import "../../../../styles/trading-workspaces.css";
import "../../../../styles/trading-strategy-lab.css";

export function StrategyLabPage() {
  const ctx = useTradingContext();
  const data = useStrategyLabData();

  const [selectedRowId, setSelectedRowId] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showCreateRun, setShowCreateRun] = useState(false);
  const [showCompare, setShowCompare] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advancedLabId, setAdvancedLabId] = useState<string | null>(null);

  const selectedRow = useMemo<DiscoveryRow | null>(
    () => data.discovery.find((r) => r.id === selectedRowId) ?? null,
    [data.discovery, selectedRowId],
  );

  const compareRows = useMemo(
    () => data.discovery.filter((r) => compareIds.includes(r.id)),
    [data.discovery, compareIds],
  );

  async function refreshAll() {
    await Promise.all([data.refresh(), ctx.refresh()]);
  }

  function selectRow(row: DiscoveryRow) {
    setSelectedRowId(row.id);
  }

  function toggleCompare(id: string) {
    setCompareIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function openAdvanced() {
    const matchedLab = data.matchLabForStrategy(selectedRow?.strategyId ?? null);
    const rawLabId = selectedRow?.labId ?? (matchedLab ? matchedLab.lab_id : null);
    setAdvancedLabId(rawLabId != null ? String(rawLabId) : null);
    setShowAdvanced(true);
  }

  return (
    <AppShell
      variant="v2"
      v2Title="Trading Center / Strategy Lab"
      v2Subtitle="Onderzoek, ontdek en valideer trading strategieën met autonome AI agents."
      v2Online={!ctx.loading && !data.loading}
      v2Refreshing={ctx.loading || data.loading}
      onV2Refresh={() => void refreshAll()}
      v2StatusRows={tradingCenterStatusRows(ctx)}
      pageClass="lv-app--trading-strategy-lab"
      v2ScrollableMain
    >
      <main className="lv-v2-page lv-sl-page" aria-label="Strategy Lab">
        <TradingContextBar ctx={ctx} />

        {data.error ? (
          <p className="lv-sl-error" role="alert">
            {data.error}
            <button type="button" className="lv-tc-btn" onClick={() => void data.refresh()}>
              Opnieuw proberen
            </button>
          </p>
        ) : null}

        <StrategyLabView
          data={data}
          selectedRow={selectedRow}
          onSelectRow={selectRow}
          compareIds={compareIds}
          onToggleCompare={toggleCompare}
          onOpenCreateRun={() => setShowCreateRun(true)}
          onOpenCompare={() => setShowCompare(true)}
          onOpenAdvanced={openAdvanced}
        />

        {showCreateRun ? (
          <CreateLabRunDrawer
            data={data}
            onClose={() => setShowCreateRun(false)}
            onCreated={(labId) => {
              setAdvancedLabId(labId);
              setShowAdvanced(true);
            }}
          />
        ) : null}

        {showCompare && compareRows.length >= 2 ? (
          <CompareDrawer rows={compareRows} onClose={() => setShowCompare(false)} onClear={() => setCompareIds([])} />
        ) : null}

        {showAdvanced ? (
          <AdvancedDrawer
            data={data}
            labId={advancedLabId}
            strategyId={selectedRow?.strategyId ?? null}
            onClose={() => setShowAdvanced(false)}
          />
        ) : null}
      </main>
    </AppShell>
  );
}
