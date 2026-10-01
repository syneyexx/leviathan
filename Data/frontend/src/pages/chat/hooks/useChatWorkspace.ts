/**
 * useChatWorkspace — composition root for ChatPage V2.
 * New chat stays a local draft until the first send (no POST /api/conversations).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { api } from "../../../api/client";
import { formatBytes, normalizeLmStudioStatus } from "../../../lib/dashboardNormalize";
import { CHAT_PROMPT_PRESETS } from "../../../lib/chat/promptPresets";
import type { ReasoningModeId } from "../../../lib/chat/reasoningModes";
import {
  canAttachFiles,
  readyArtifactIds,
  uploadChatAttachment,
  visionClaimAllowed,
  type ChatAttachment,
} from "../../../lib/chat/attachments";
import { useSystemTelemetry } from "../../../hooks/useSystemTelemetry";
import { useAppToast } from "../../../state/useAppToast";
import type { SidebarStatusRow } from "../../../components/layout/AppSidebarV2";
import type { HealthResponse } from "../../../types/api";
import { buildDiagnosticStrip } from "../../chatTelemetry";
import { classifyCapability, isCapabilityActive } from "../chatHelpers";
import { useChatBootstrap } from "./useChatBootstrap";
import { useChatConfiguration } from "./useChatConfiguration";
import { useChatInspectorData } from "./useChatInspectorData";
import { useConversationCatalog } from "./useConversationCatalog";
import { useConversationThread } from "./useConversationThread";
import { EMPTY_TURN, useChatTurn, type LastTurnMeta } from "./useChatTurn";

type LocationState = { draft?: string };

type ChatVisualFixtureUi = {
  activeConversationId?: string;
  selectedModelId?: string | null;
  reasoningMode?: ReasoningModeId;
  collaborationStrategy?: "direct" | "team";
  lastTurn?: Partial<LastTurnMeta>;
};

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

function readChatVisualFixtureUi(): ChatVisualFixtureUi | null {
  if (typeof window === "undefined") return null;
  const w = window as Window & {
    __LV_V2_VISUAL_FIXTURE__?: boolean;
    __LV_CHAT_V2_FIXTURE_UI__?: ChatVisualFixtureUi;
  };
  if (!w.__LV_V2_VISUAL_FIXTURE__ || !w.__LV_CHAT_V2_FIXTURE_UI__) return null;
  return w.__LV_CHAT_V2_FIXTURE_UI__;
}

function conversationDeepLink(id: string): string {
  return `${window.location.origin}/chat?conversation=${encodeURIComponent(id)}`;
}

function buildChatSidebarStatus(
  health: HealthResponse | null,
  telemetry: ReturnType<typeof useSystemTelemetry>["sample"],
): SidebarStatusRow[] {
  const lm = normalizeLmStudioStatus(health);
  const rows: SidebarStatusRow[] = [
    { id: "lm-studio", label: lm.label, value: lm.value, tone: lm.tone },
  ];
  const devices = telemetry?.gpu?.devices?.slice(0, 2) ?? [];
  if (devices.length === 0) {
    rows.push({
      id: "gpu-none",
      label: "GPU",
      value: telemetry?.gpu?.available === false ? "Unavailable" : "UNMEASURED",
      tone: "muted",
    });
  } else {
    for (const d of devices) {
      const shortName = (d.name || "GPU").replace(/^NVIDIA\s+/i, "");
      rows.push({
        id: `gpu-${d.index}`,
        label: `GPU ${d.index} - ${shortName}`,
        value: d.utilizationPct != null ? "Ready" : "UNMEASURED",
        tone: d.utilizationPct == null ? "muted" : "success",
      });
    }
  }
  const mem = telemetry?.memory;
  rows.push({
    id: "ram",
    label: "RAM",
    value:
      mem?.available && mem.usedBytes != null && mem.totalBytes != null
        ? `${formatBytes(mem.usedBytes)} / ${formatBytes(mem.totalBytes)}`
        : "UNMEASURED",
    tone: mem?.available ? "info" : "muted",
  });
  const gpus = telemetry?.gpu?.devices ?? [];
  if (gpus.length && telemetry?.gpu?.available) {
    let used = 0;
    let total = 0;
    let ok = false;
    for (const g of gpus) {
      if (g.vramUsedBytes != null && g.vramTotalBytes != null) {
        used += g.vramUsedBytes;
        total += g.vramTotalBytes;
        ok = true;
      }
    }
    rows.push({
      id: "vram",
      label: "VRAM Total",
      value: ok ? `${formatBytes(used)} / ${formatBytes(total)}` : "UNMEASURED",
      tone: ok ? "info" : "muted",
    });
  }
  return rows;
}

export function useChatWorkspace() {
  const toast = useAppToast();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const draft = (location.state as LocationState | null)?.draft;
  const frozen = visualFixtureNow();
  const { sample: systemTelemetry } = useSystemTelemetry({ intervalMs: 2000 });

  const bootstrap = useChatBootstrap();
  const catalog = useConversationCatalog();
  const thread = useConversationThread();
  const config = useChatConfiguration(bootstrap.models, {
    onIneligibleModel: (msg) => toast(msg),
  });

  const [conversationId, setConversationId] = useState<string | null>(null);
  /** True when the open chat has no durable server id yet. */
  const [isDraft, setIsDraft] = useState(true);
  const [composer, setComposer] = useState(draft ?? "");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [attachBusy, setAttachBusy] = useState(false);
  const [teamPanel, setTeamPanel] = useState<Record<string, unknown> | null>(null);
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const [inspectorDrawerOpen, setInspectorDrawerOpen] = useState(false);
  const [newChatMenuOpen, setNewChatMenuOpen] = useState(false);
  const [manageMenuOpen, setManageMenuOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [renameBusy, setRenameBusy] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [initializing, setInitializing] = useState(true);

  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const historySearchRef = useRef<HTMLInputElement | null>(null);
  const historyPanelRef = useRef<HTMLElement | null>(null);
  const inspectorPanelRef = useRef<HTMLElement | null>(null);
  const newChatMenuRef = useRef<HTMLDivElement | null>(null);
  const manageMenuRef = useRef<HTMLDivElement | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const drawerTriggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  const syncUrl = useCallback(
    (id: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id) next.set("conversation", id);
          else next.delete("conversation");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const ensureConversationId = useCallback(async () => {
    if (conversationIdRef.current) return conversationIdRef.current;
    try {
      const created = await api.createConversation();
      const id = created.conversation.id;
      setConversationId(id);
      conversationIdRef.current = id;
      setIsDraft(false);
      thread.setTitle(created.conversation.title);
      syncUrl(id);
      catalog.upsertConversation(created.conversation);
      catalog.selectConversation(id);
      return id;
    } catch (error) {
      toast(
        `Could not create chat: ${error instanceof Error ? error.message : "unknown error"}`,
      );
      return null;
    }
  }, [catalog, syncUrl, thread, toast]);

  const turn = useChatTurn({
    getConversationId: () => conversationIdRef.current,
    ensureConversationId,
    setMessages: thread.setMessages,
    reasoningMode: config.reasoningMode,
    selectedModelId: config.selectedModelId,
    collaborationStrategy: config.collaborationStrategy,
    toolPolicy: config.toolPolicy,
    onToast: toast,
    onConversationId: (id) => {
      setConversationId(id);
      conversationIdRef.current = id;
      setIsDraft(false);
      syncUrl(id);
      catalog.selectConversation(id);
    },
    onAfterTurn: async (id) => {
      await catalog.refresh();
      catalog.selectConversation(id);
      await thread.loadConversation(id);
    },
    onTeamPanel: setTeamPanel,
  });

  const inspector = useChatInspectorData({
    lastTurn: {
      knowledgeSources: turn.lastTurn.knowledgeSources,
      verification: turn.lastTurn.verification,
      telemetry: turn.lastTurn.telemetry,
      behaviorProfileId: turn.lastTurn.telemetry?.behavior_profile_id ?? null,
      behaviorVersion: turn.lastTurn.telemetry?.behavior_version ?? null,
      projectContext: null,
    },
    contextWindow: config.contextWindow,
    systemTelemetry,
  });

  // ArtifactStore HTTP is mounted when backend is up — gate on bootstrap truth.
  const attachGate = canAttachFiles(bootstrap.bootstrapped ? true : null);
  const visionCapActive = useMemo(
    () =>
      bootstrap.capabilities.some(
        (c) => classifyCapability(c) === "vision" && isCapabilityActive(c),
      ),
    [bootstrap.capabilities],
  );
  const selectedModel = useMemo(
    () => config.chatModels.find((m) => m.id === config.selectedModelId) ?? null,
    [config.chatModels, config.selectedModelId],
  );
  const modelVision =
    selectedModel == null
      ? null
      : Boolean(
          (selectedModel as { supportsVision?: boolean; vision?: boolean }).supportsVision ||
            (selectedModel as { vision?: boolean }).vision ||
            /vision|vlm|multimodal/i.test(
              `${selectedModel.id} ${selectedModel.displayName || ""} ${selectedModel.family || ""}`,
            ),
        );
  const hasImageAttachment = attachments.some(
    (a) => a.mimeType.startsWith("image/") && (a.state === "ready" || a.state === "uploading"),
  );
  const visionHonesty = visionClaimAllowed({
    hasImageAttachment,
    modelSupportsVision: modelVision,
    visionCapabilityActive: visionCapActive,
  });

  const activeConversation = useMemo(
    () => catalog.conversations.find((item) => item.id === conversationId) ?? null,
    [catalog.conversations, conversationId],
  );

  const sidebarStatus = useMemo(
    () => buildChatSidebarStatus(bootstrap.health, systemTelemetry),
    [bootstrap.health, systemTelemetry],
  );

  const v2Online = useMemo(() => {
    if (bootstrap.health?.ok === true) return true;
    if (bootstrap.health?.llm?.available === false) return false;
    if (bootstrap.health?.ok === false) return false;
    return null;
  }, [bootstrap.health]);

  const diagnosticStrip = useMemo(
    () => buildDiagnosticStrip(turn.lastTurn.telemetry),
    [turn.lastTurn.telemetry],
  );

  /** New chat = local draft only — no POST until first send. */
  const startDraftChat = useCallback(() => {
    if (turn.busyRef.current) return;
    setNewChatMenuOpen(false);
    setConversationId(null);
    conversationIdRef.current = null;
    setIsDraft(true);
    thread.setMessages([]);
    thread.setTitle("New conversation");
    turn.resetTurn();
    setTeamPanel(null);
    setAttachments([]);
    setComposer("");
    syncUrl(null);
    catalog.selectConversation(null);
    requestAnimationFrame(() => composerRef.current?.focus());
  }, [catalog, syncUrl, thread, turn]);

  const loadConversation = useCallback(
    async (id: string) => {
      if (turn.busyRef.current) return;
      setConversationId(id);
      conversationIdRef.current = id;
      setIsDraft(false);
      syncUrl(id);
      catalog.selectConversation(id);
      turn.resetTurn();
      setTeamPanel(null);
      setAttachments([]);
      await thread.loadConversation(id);
      setHistoryDrawerOpen(false);
    },
    [catalog, syncUrl, thread, turn],
  );

  // Initial bootstrap: catalog + deep link / fixture / first conversation / draft.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const listed = await catalog.refresh();
        if (cancelled) return;
        const fixtureUi = readChatVisualFixtureUi();
        const deepLinkId =
          searchParams.get("conversation") ||
          (fixtureUi?.activeConversationId
            ? String(fixtureUi.activeConversationId)
            : null);

        if (deepLinkId) {
          try {
            await loadConversation(deepLinkId);
          } catch (error) {
            if (cancelled) return;
            toast(
              `Conversation not found: ${
                error instanceof Error ? error.message : "invalid id"
              }`,
            );
            if (listed.length > 0) {
              await loadConversation(listed[0].id);
            } else {
              startDraftChat();
            }
          }
        } else if (listed.length > 0) {
          await loadConversation(listed[0].id);
        } else {
          startDraftChat();
        }

        if (!cancelled && fixtureUi) {
          if (fixtureUi.selectedModelId !== undefined) {
            config.setSelectedModelId(fixtureUi.selectedModelId);
          }
          if (fixtureUi.reasoningMode) {
            config.setReasoningMode(fixtureUi.reasoningMode);
          }
          if (fixtureUi.collaborationStrategy) {
            config.setCollaborationStrategy(fixtureUi.collaborationStrategy);
          }
          if (fixtureUi.lastTurn) {
            turn.setLastTurn({ ...EMPTY_TURN, ...fixtureUi.lastTurn });
          }
        }
      } catch (error) {
        if (cancelled) return;
        startDraftChat();
        toast(
          `Backend unavailable: ${error instanceof Error ? error.message : "unknown error"}`,
        );
      } finally {
        if (!cancelled) setInitializing(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once on mount
  }, []);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (newChatMenuRef.current && !newChatMenuRef.current.contains(target)) {
        setNewChatMenuOpen(false);
      }
      if (manageMenuRef.current && !manageMenuRef.current.contains(target)) {
        setManageMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (historyDrawerOpen) {
        setHistoryDrawerOpen(false);
        requestAnimationFrame(() => drawerTriggerRef.current?.focus());
        return;
      }
      if (inspectorDrawerOpen) {
        setInspectorDrawerOpen(false);
        requestAnimationFrame(() => drawerTriggerRef.current?.focus());
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [historyDrawerOpen, inspectorDrawerOpen]);

  useEffect(() => {
    if (historyDrawerOpen) {
      requestAnimationFrame(() => historySearchRef.current?.focus());
    }
  }, [historyDrawerOpen]);

  useEffect(() => {
    if (inspectorDrawerOpen) {
      requestAnimationFrame(() => {
        inspectorPanelRef.current
          ?.querySelector<HTMLElement>("button, [href], input, select, textarea")
          ?.focus();
      });
    }
  }, [inspectorDrawerOpen]);

  // Focus trap while a mobile drawer is open.
  useEffect(() => {
    const open = historyDrawerOpen || inspectorDrawerOpen;
    if (!open) return;
    const panel = historyDrawerOpen ? historyPanelRef.current : inspectorPanelRef.current;
    if (!panel) return;

    function onTab(event: KeyboardEvent) {
      if (event.key !== "Tab" || !panel) return;
      const focusable = panel.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onTab);
    return () => document.removeEventListener("keydown", onTab);
  }, [historyDrawerOpen, inspectorDrawerOpen]);

  const openHistoryDrawer = useCallback(() => {
    drawerTriggerRef.current = document.activeElement as HTMLElement | null;
    setInspectorDrawerOpen(false);
    setHistoryDrawerOpen(true);
  }, []);

  const openInspectorDrawer = useCallback(() => {
    drawerTriggerRef.current = document.activeElement as HTMLElement | null;
    setHistoryDrawerOpen(false);
    setInspectorDrawerOpen(true);
  }, []);

  const closeDrawers = useCallback(() => {
    setHistoryDrawerOpen(false);
    setInspectorDrawerOpen(false);
    requestAnimationFrame(() => drawerTriggerRef.current?.focus());
  }, []);

  const copyLocalLink = useCallback(
    async (id: string | null) => {
      if (!id) {
        toast("No conversation to share yet");
        return;
      }
      const link = conversationDeepLink(id);
      try {
        await navigator.clipboard.writeText(link);
        toast("Copied local deep link (this host only)");
      } catch {
        toast(`Copy failed — link: ${link}`);
      }
    },
    [toast],
  );

  const togglePinned = useCallback(async () => {
    if (!conversationId || turn.busy) return;
    setManageMenuOpen(false);
    const nextPinned = !activeConversation?.pinned;
    try {
      const data = await api.updateConversation(conversationId, { pinned: nextPinned });
      catalog.upsertConversation(data.conversation);
      toast(nextPinned ? "Pinned" : "Unpinned");
    } catch (error) {
      toast(`Pin failed: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }, [activeConversation?.pinned, catalog, conversationId, toast, turn.busy]);

  const openRenameDialog = useCallback(() => {
    if (!conversationId) return;
    setManageMenuOpen(false);
    setRenameValue(activeConversation?.title ?? thread.title);
    setRenameOpen(true);
  }, [activeConversation?.title, conversationId, thread.title]);

  const confirmRename = useCallback(async () => {
    if (!conversationId) return;
    const current = activeConversation?.title ?? thread.title;
    const trimmed = renameValue.trim();
    if (!trimmed || trimmed === current) {
      setRenameOpen(false);
      return;
    }
    setRenameBusy(true);
    try {
      const data = await api.updateConversation(conversationId, { title: trimmed });
      thread.setTitle(data.conversation.title);
      catalog.upsertConversation(data.conversation);
      toast("Renamed");
      setRenameOpen(false);
    } catch (error) {
      toast(`Rename failed: ${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setRenameBusy(false);
    }
  }, [activeConversation?.title, catalog, conversationId, renameValue, thread, toast]);

  const openDeleteDialog = useCallback(() => {
    if (!conversationId) return;
    setManageMenuOpen(false);
    setDeleteOpen(true);
  }, [conversationId]);

  const confirmDelete = useCallback(async () => {
    if (!conversationId) return;
    const deletingId = conversationId;
    setDeleteBusy(true);
    try {
      await api.deleteConversation(deletingId);
      catalog.removeConversation(deletingId);
      toast("Deleted");
      setDeleteOpen(false);
      const listed = await catalog.refresh();
      const next = listed.find((c) => c.id !== deletingId);
      if (next) await loadConversation(next.id);
      else startDraftChat();
    } catch (error) {
      toast(`Delete failed: ${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setDeleteBusy(false);
    }
  }, [catalog, conversationId, loadConversation, startDraftChat, toast]);

  const onV2Refresh = useCallback(async () => {
    try {
      await bootstrap.refresh();
      await catalog.refresh();
      if (conversationId) await thread.loadConversation(conversationId);
    } catch (error) {
      toast(`Refresh failed: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }, [bootstrap, catalog, conversationId, thread, toast]);

  const onAttachFiles = useCallback(
    async (files: FileList | File[]) => {
      if (!attachGate.ok) {
        toast(attachGate.reason || "Attachments unavailable");
        return;
      }
      const list = Array.from(files);
      if (!list.length) return;
      setAttachBusy(true);
      try {
        for (const file of list) {
          const pendingId = `att-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
          const pending: ChatAttachment = {
            localId: pendingId,
            fileName: file.name.replace(/[\\/]/g, "_").slice(0, 200),
            mimeType: file.type || "application/octet-stream",
            sizeBytes: file.size,
            artifactId: null,
            state: "uploading",
            error: null,
            unavailableReason: null,
          };
          setAttachments((prev) => [...prev, pending]);
          const uploaded = await uploadChatAttachment(file, {
            conversationId: conversationIdRef.current,
          });
          setAttachments((prev) =>
            prev.map((item) =>
              item.localId === pendingId ? { ...uploaded, localId: pendingId } : item,
            ),
          );
          if (uploaded.state === "failed") {
            toast(uploaded.error || `Kon ${file.name} niet uploaden`);
          }
        }
      } finally {
        setAttachBusy(false);
      }
    },
    [attachGate.ok, attachGate.reason, toast],
  );

  const onRemoveAttachment = useCallback((localId: string) => {
    setAttachments((prev) => prev.filter((a) => a.localId !== localId));
  }, []);

  const sendMessage = useCallback(async () => {
    const text = composer.trim();
    const ids = readyArtifactIds(attachments);
    if (!text && ids.length === 0) return;
    setComposer("");
    setAttachments([]);
    await turn.send(text || "(attachment)", ids.length ? { artifactIds: ids } : undefined);
  }, [attachments, composer, turn]);

  const quickPrompts = thread.messages.length === 0 ? [...CHAT_PROMPT_PRESETS] : [];

  const runtimeMeta =
    bootstrap.agentsEnabled != null || bootstrap.codingEnabled != null
      ? `agents=${
          bootstrap.agentsEnabled === null ? "?" : bootstrap.agentsEnabled ? "on" : "off"
        } · coding=${
          bootstrap.codingEnabled === null ? "?" : bootstrap.codingEnabled ? "on" : "off"
        }`
      : null;

  const bootstrapped = bootstrap.bootstrapped && !initializing;

  return {
    frozen,
    v2Online,
    sidebarStatus,
    bootstrapped,
    refreshing: bootstrap.refreshing,
    onV2Refresh,
    config,
    capabilities: bootstrap.capabilities,
    catalog,
    thread,
    conversationId,
    isDraft,
    activeConversation,
    title: thread.title,
    turn,
    teamPanel,
    diagnosticStrip,
    inspector,
    systemTelemetry,
    memoryCount: bootstrap.memoryCount,
    composer,
    setComposer,
    composerRef,
    quickPrompts,
    sendMessage,
    attachments,
    attachBusy,
    attachmentsEnabled: attachGate.ok,
    attachmentsUnavailableReason: attachGate.reason,
    visionHonesty,
    onAttachFiles,
    onRemoveAttachment,
    historyDrawerOpen,
    inspectorDrawerOpen,
    openHistoryDrawer,
    openInspectorDrawer,
    closeDrawers,
    historySearchRef,
    historyPanelRef,
    inspectorPanelRef,
    newChatMenuOpen,
    setNewChatMenuOpen,
    manageMenuOpen,
    setManageMenuOpen,
    newChatMenuRef,
    manageMenuRef,
    startDraftChat,
    loadConversation,
    copyLocalLink,
    togglePinned,
    openRenameDialog,
    confirmRename,
    renameOpen,
    setRenameOpen,
    renameValue,
    setRenameValue,
    renameBusy,
    openDeleteDialog,
    confirmDelete,
    deleteOpen,
    setDeleteOpen,
    deleteBusy,
    runtimeMeta,
    modelLabel: config.modelLabel,
  };
}
