/**
 * ChatPage V2 — thin shell over useChatWorkspace.
 * Visual fixture hooks and layout structure are preserved.
 */
import { Dialog } from "../components/ui";
import { AppShell } from "../layouts/AppShell";
import { ChatComposer } from "./chat/ChatComposer";
import { ChatInspector } from "./chat/ChatInspector";
import { ConversationHistoryPanel } from "./chat/ConversationHistoryPanel";
import { HadesConfigStrip } from "./chat/HadesConfigStrip";
import { MessageList } from "./chat/MessageList";
import { useChatWorkspace } from "./chat/hooks/useChatWorkspace";

export function ChatPage() {
  const ws = useChatWorkspace();
  const pinned = Boolean(ws.activeConversation?.pinned);

  const v2Actions = (
    <>
      <div style={{ position: "relative" }} ref={ws.newChatMenuRef}>
        <div className="lv-v2-topbar__action-split">
          <button
            type="button"
            className="lv-v2-topbar__action-btn lv-v2-topbar__action-btn--primary"
            disabled={ws.turn.busy || !ws.bootstrapped}
            onClick={() => ws.startDraftChat()}
          >
            + Nieuwe chat
          </button>
          <button
            type="button"
            className="lv-v2-topbar__action-split__chevron"
            aria-label="Nieuwe chat opties"
            aria-expanded={ws.newChatMenuOpen}
            disabled={ws.turn.busy || !ws.bootstrapped}
            onClick={() => {
              ws.setManageMenuOpen(false);
              ws.setNewChatMenuOpen((open) => !open);
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="currentColor" d="M7 10l5 5 5-5" />
            </svg>
          </button>
        </div>
        {ws.newChatMenuOpen ? (
          <div className="lv-v2-topbar__action-menu" role="menu">
            <button type="button" role="menuitem" onClick={() => ws.startDraftChat()}>
              Nieuwe lege chat
            </button>
            {ws.config.selectedModelId ? (
              <button
                type="button"
                role="menuitem"
                onClick={() => ws.startDraftChat()}
                title={`Model blijft: ${ws.modelLabel}`}
              >
                met huidig model ({ws.modelLabel})
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div style={{ position: "relative" }} ref={ws.manageMenuRef}>
        <button
          type="button"
          className="lv-v2-topbar__action-btn"
          aria-expanded={ws.manageMenuOpen}
          disabled={!ws.conversationId}
          onClick={() => {
            ws.setNewChatMenuOpen(false);
            ws.setManageMenuOpen((open) => !open);
          }}
        >
          Manage
        </button>
        {ws.manageMenuOpen ? (
          <div className="lv-v2-topbar__action-menu" role="menu">
            <button type="button" role="menuitem" onClick={ws.openRenameDialog}>
              Rename
            </button>
            <button type="button" role="menuitem" onClick={() => void ws.togglePinned()}>
              {pinned ? "Unpin" : "Pin"}
            </button>
            <button type="button" role="menuitem" onClick={ws.openDeleteDialog}>
              Delete
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                ws.setManageMenuOpen(false);
                void ws.copyLocalLink(ws.conversationId);
              }}
            >
              Copy local link
            </button>
          </div>
        ) : null}
      </div>

      <button
        type="button"
        className="lv-v2-topbar__action-btn"
        onClick={ws.openHistoryDrawer}
      >
        Gesprekken
      </button>
      <button
        type="button"
        className="lv-v2-topbar__action-btn"
        onClick={ws.openInspectorDrawer}
        aria-expanded={ws.inspectorDrawerOpen}
      >
        Context
      </button>
    </>
  );

  return (
    <AppShell
      variant="v2"
      v2Title="Hades AI / Chat"
      v2Subtitle="Geavanceerde AI-assistentie met redeneren, tools en betrouwbare bronnen"
      v2Online={ws.v2Online}
      v2StatusRows={ws.sidebarStatus}
      v2Now={ws.frozen ? () => ws.frozen! : undefined}
      v2Actions={v2Actions}
      v2HideRefresh={true}
      v2Refreshing={ws.refreshing}
      onV2Refresh={() => {
        void ws.onV2Refresh();
      }}
    >
      <main className="lv-v2-page lv-v2-page--chat">
        <HadesConfigStrip
          models={ws.config.chatModels}
          nonChatModels={ws.config.nonChatModels}
          selectedModelId={ws.config.selectedModelId}
          onSelectModel={ws.config.setSelectedModelId}
          collaborationStrategy={ws.config.collaborationStrategy}
          onCollaborationChange={ws.config.setCollaborationStrategy}
          reasoningMode={ws.config.reasoningMode}
          onReasoningChange={ws.config.setReasoningMode}
          capabilities={ws.capabilities}
          busy={ws.turn.busy}
        />

        <button
          type="button"
          className={`lv-v2-chat-drawer-backdrop${
            ws.historyDrawerOpen || ws.inspectorDrawerOpen ? " is-open" : ""
          }`}
          aria-label="Sluit paneel"
          onClick={ws.closeDrawers}
        />

        <div className="lv-v2-chat-workspace">
          <ConversationHistoryPanel
            conversations={ws.catalog.conversations}
            activeId={ws.conversationId}
            onSelect={(id) => void ws.loadConversation(id)}
            onCreate={() => ws.startDraftChat()}
            bootstrapped={ws.bootstrapped}
            creating={false}
            searchQuery={ws.catalog.searchQuery}
            onSearchChange={ws.catalog.setSearchQuery}
            serverSearch
            hasMore={ws.catalog.hasMore}
            onLoadMore={() => void ws.catalog.loadMore()}
            loadingMore={ws.catalog.loadingMore}
            drawerOpen={ws.historyDrawerOpen}
            searchInputRef={ws.historySearchRef}
            panelRef={ws.historyPanelRef}
            now={ws.frozen ?? undefined}
          />

          <div className="lv-v2-chat-col lv-v2-chat-center">
            <MessageList
              messages={ws.thread.messages}
              turnsByMessageId={ws.thread.turnsByMessageId}
              hasMoreOlder={ws.thread.hasMoreOlder}
              loadingOlder={ws.thread.loadingOlder}
              onLoadOlder={() => void ws.thread.loadOlder()}
              onOpenInspector={ws.openInspectorDrawer}
              lastTurn={{
                reasoning: ws.turn.lastTurn.reasoning,
                cognitionPhase: ws.turn.lastTurn.cognitionPhase,
                streaming: ws.turn.lastTurn.streaming,
                telemetry: ws.turn.lastTurn.telemetry,
                reasoningElapsedMs:
                  typeof (ws.turn.lastTurn.telemetry as { reasoning_elapsed_ms?: number } | null)
                    ?.reasoning_elapsed_ms === "number"
                    ? (ws.turn.lastTurn.telemetry as { reasoning_elapsed_ms?: number })
                        .reasoning_elapsed_ms
                    : null,
                activity: ws.turn.lastTurn.activity,
                activityMode: ws.turn.lastTurn.activityMode,
                decisionReceipts: ws.turn.lastTurn.decisionReceipts,
              }}
              onActivityModeChange={(mode) =>
                ws.turn.setLastTurn((prev) => ({ ...prev, activityMode: mode }))
              }
            />
            <ChatComposer
              value={ws.composer}
              onChange={ws.setComposer}
              onSend={() => void ws.sendMessage()}
              onStop={() => void ws.turn.cancel()}
              busy={ws.turn.busy}
              disabled={!ws.bootstrapped}
              reasoningMode={ws.config.reasoningMode}
              onReasoningChange={ws.config.setReasoningMode}
              capabilities={ws.capabilities}
              contextWindow={ws.config.contextWindow}
              selectedModelId={ws.config.selectedModelId}
              quickPrompts={ws.quickPrompts}
              textareaRef={ws.composerRef}
              attachments={ws.attachments}
              attachmentsEnabled={ws.attachmentsEnabled}
              attachmentsUnavailableReason={ws.attachmentsUnavailableReason}
              onAttachFiles={(files) => void ws.onAttachFiles(files)}
              onRemoveAttachment={ws.onRemoveAttachment}
              visionHonestyReason={ws.visionHonesty.reason}
            />
            {ws.diagnosticStrip.length > 0 || ws.teamPanel || ws.runtimeMeta ? (
              <div
                className="lv-v2-muted"
                style={{
                  fontSize: 10,
                  padding: "2px 10px 8px",
                  opacity: 0.7,
                  display: "flex",
                  flexWrap: "wrap",
                  gap: "0.35rem 0.75rem",
                }}
                aria-label="Turn diagnostics"
              >
                {ws.diagnosticStrip.map((item) => (
                  <span key={item.label}>
                    {item.label}={item.value}
                  </span>
                ))}
                {ws.teamPanel ? (
                  <span>
                    TEAM {String(ws.teamPanel.quality_label ?? ws.teamPanel.status ?? "—")}
                  </span>
                ) : null}
                {ws.runtimeMeta ? <span>{ws.runtimeMeta}</span> : null}
                {ws.isDraft ? <span>draft</span> : null}
              </div>
            ) : null}
          </div>

          <ChatInspector
            tokenUsage={ws.inspector.tokenUsage}
            contextBudget={ws.inspector.contextBudget}
            memoryCount={ws.memoryCount}
            preferencesLabel={ws.inspector.preferencesLabel}
            projectContext={ws.inspector.projectContext}
            knowledgeSources={ws.inspector.knowledgeSources}
            verification={ws.inspector.verification}
            systemTelemetry={ws.systemTelemetry}
            lastTurnTelemetry={ws.inspector.lastTurnTelemetry}
            drawerOpen={ws.inspectorDrawerOpen}
            panelRef={ws.inspectorPanelRef}
          />
        </div>
      </main>

      <Dialog
        open={ws.renameOpen}
        title="Hernoem gesprek"
        description="Geef dit gesprek een nieuwe titel."
        confirmLabel="Opslaan"
        cancelLabel="Annuleren"
        busy={ws.renameBusy}
        onClose={() => {
          if (!ws.renameBusy) ws.setRenameOpen(false);
        }}
        onConfirm={() => void ws.confirmRename()}
      >
        <label className="lv-v2-sr-only" htmlFor="chat-rename-input">
          Titel
        </label>
        <input
          id="chat-rename-input"
          value={ws.renameValue}
          onChange={(e) => ws.setRenameValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void ws.confirmRename();
            }
          }}
          disabled={ws.renameBusy}
        />
      </Dialog>

      <Dialog
        open={ws.deleteOpen}
        title="Gesprek verwijderen"
        description="Delete this conversation? This cannot be undone."
        confirmLabel="Verwijderen"
        cancelLabel="Annuleren"
        danger
        busy={ws.deleteBusy}
        onClose={() => {
          if (!ws.deleteBusy) ws.setDeleteOpen(false);
        }}
        onConfirm={() => void ws.confirmDelete()}
      />
    </AppShell>
  );
}
