/**
 * Leviathan V2 Tools — canonical `/tools`.
 * CapabilityCatalog + ExecutionGateway control plane. No page-local CSS.
 */

import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { ToolsBottomPanels } from "../components/tools/ToolsBottomPanels";
import { ToolsDetail } from "../components/tools/ToolsDetail";
import { ToolsHero } from "../components/tools/ToolsHero";
import { ToolsLibrary } from "../components/tools/ToolsLibrary";
import { ToolsMetrics } from "../components/tools/ToolsMetrics";
import {
  ToolsEditDialog,
  ToolsHistoryDialog,
  ToolsMcpAddDialog,
  ToolsNewToolDialog,
  ToolsTestDialog,
} from "../components/tools/ToolsModals";
import { ErrorState, LoadingState } from "../components/ui";
import { AppShell } from "../layouts/AppShell";
import { useToolsWorkspace } from "./tools/useToolsWorkspace";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

function ToolsTopbarSearch({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
      if (e.key === "Escape" && document.activeElement === inputRef.current) {
        onChange("");
        inputRef.current?.blur();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onChange]);

  return (
    <form
      className="lv-v2-topbar-search lv-v2-tools-topbar-search"
      role="search"
      onSubmit={(e) => e.preventDefault()}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <circle cx="11" cy="11" r="6" />
        <path d="M16 16l4 4" />
      </svg>
      <input
        id="lv-tools-search"
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Zoek tools, categorieën, plugin..."
        aria-label="Zoek tools"
      />
      <kbd>Ctrl + K</kbd>
    </form>
  );
}

export function ToolsPage() {
  const ws = useToolsWorkspace();
  const navigate = useNavigate();
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="Runtime & Tools / Tools"
      v2Subtitle="Beheer, test en monitor alle beschikbare tools voor agents, runtimes en MCP."
      v2Online={!ws.loadError}
      v2Refreshing={ws.refreshing}
      onV2Refresh={() => {
        void ws.load();
      }}
      v2Now={frozen ? () => frozen : undefined}
      v2Actions={<ToolsTopbarSearch value={ws.topbarQuery} onChange={ws.setTopbarQuery} />}
    >
      <main className="lv-v2-page lv-v2-page--tools">
        {ws.stale ? (
          <p className="lv-v2-warn" role="status">
            Stale — vernieuwen mislukt; laatste goede snapshot behouden.
          </p>
        ) : null}

        <ToolsHero />

        <ToolsMetrics overview={ws.overview} loading={ws.loading && !ws.overview} />

        {ws.loadError ? <ErrorState title="Tools laden mislukt" detail={ws.loadError} /> : null}
        {ws.loading && !ws.overview ? <LoadingState label="Tools laden…" /> : null}

        <section className="lv-v2-tools-workspace" aria-label="Tools werkruimte">
          <ToolsLibrary
            rows={ws.tools}
            total={ws.toolsTotal}
            selectedId={ws.selectedId}
            onSelect={ws.selectTool}
            query={ws.query}
            onQuery={ws.setQuery}
            category={ws.category}
            onCategory={ws.setCategory}
            source={ws.source}
            onSource={ws.setSource}
            sort={ws.sort}
            onSort={ws.setSort}
            categories={ws.categories}
            loading={ws.loading}
            onNewTool={() => ws.setNewToolOpen(true)}
            onCopyId={ws.copyId}
            onOpenLogs={(id) => {
              ws.selectTool(id);
              ws.setDetailTab("logs");
            }}
            onTest={(id) => {
              ws.selectTool(id);
              ws.setTestOpen(true);
            }}
          />
          <ToolsDetail
            selected={ws.selected}
            detail={ws.detail}
            loading={ws.detailLoading}
            tab={ws.detailTab}
            onTab={ws.setDetailTab}
            testArgs={ws.testArgs}
            onTestArgs={ws.setTestArgs}
            onTest={() => ws.setTestOpen(true)}
            onEdit={() => ws.setEditOpen(true)}
            testing={ws.testing}
            testResult={ws.testResult}
          />
        </section>

        <ToolsBottomPanels
          overview={ws.overview}
          recentCalls={ws.recentCalls}
          mcpStale={ws.mcpStale}
          pluginsStale={ws.pluginsStale}
          onAddMcp={() => ws.setMcpAddOpen(true)}
          onLoadPlugin={() => navigate("/modules")}
          onReconnectMcp={(id) => void ws.reconnectMcp(id)}
          onTogglePlugin={(id, enable) => void ws.togglePlugin(id, enable)}
          onViewAllCalls={() => ws.setHistoryOpen(true)}
        />

        <ToolsNewToolDialog
          open={ws.newToolOpen}
          onClose={() => ws.setNewToolOpen(false)}
          busy={ws.creating}
          wrapCandidates={ws.tools.filter((t) => t.origin !== "custom")}
          onCreateWrapper={(payload) => void ws.createCustomTool(payload)}
          onOpenMcp={() => ws.setMcpAddOpen(true)}
          onOpenModules={() => navigate("/modules")}
        />
        <ToolsTestDialog
          open={ws.testOpen}
          onClose={() => ws.setTestOpen(false)}
          detail={ws.detail}
          args={ws.testArgs}
          onArgs={ws.setTestArgs}
          onExecute={() => void ws.runTest()}
          busy={ws.testing}
          result={ws.testResult}
        />
        <ToolsEditDialog
          open={ws.editOpen}
          onClose={() => ws.setEditOpen(false)}
          detail={ws.detail}
          onSave={(payload) => void ws.updateCustomTool(payload)}
          onDelete={() => void ws.deleteCustomTool()}
        />
        <ToolsMcpAddDialog
          open={ws.mcpAddOpen}
          onClose={() => ws.setMcpAddOpen(false)}
          onCreate={(payload) => void ws.createMcpServer(payload)}
        />
        <ToolsHistoryDialog
          open={ws.historyOpen}
          onClose={() => ws.setHistoryOpen(false)}
          calls={ws.recentCalls}
        />
      </main>
    </AppShell>
  );
}
