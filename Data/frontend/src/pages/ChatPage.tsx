import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { displayMessageContent, normalizeMessage } from "../api/chatContract";
import { Dialog } from "../components/ui";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import { useSystemTelemetry } from "../hooks/useSystemTelemetry";
import { AppShell } from "../layouts/AppShell";
import { formatBytes, normalizeLmStudioStatus } from "../lib/dashboardNormalize";
import { partitionChatModels } from "../lib/chatModels";
import { formatJobStateLabel, normalizeJobStatus } from "../lib/jobStatus";
import { ActivityClientProjector } from "../lib/activityProjector";
import { useAppToast } from "../state/useAppToast";
import type {
  CapabilityListItem,
  Conversation,
  HealthResponse,
  KnowledgeSource,
  ModelDescriptor,
  ReasoningSummary,
} from "../types/api";
import type {
  ActivityDisplayMode,
  ActivityProjection,
  DecisionReceipt,
} from "../types/activity";
import { parseActivityProjection } from "../types/activity";
import { buildDiagnosticStrip, deriveAssistantTelemetry } from "./chatTelemetry";
import { chatQuickPrompts } from "../lib/chat/promptPresets";
import {
  parseReasoningMode,
  reasoningModeForApi,
  type ReasoningModeId,
} from "../lib/chat/reasoningModes";
import { ChatComposer } from "./chat/ChatComposer";
import { ChatInspector } from "./chat/ChatInspector";
import { ConversationHistoryPanel } from "./chat/ConversationHistoryPanel";
import { HadesConfigStrip } from "./chat/HadesConfigStrip";
import { MessageList } from "./chat/MessageList";

type LocationState = {
  draft?: string;
};

type DisplayMessage = {
  role: "user" | "assistant";
  content: string;
  created_at: string | null;
  pending?: boolean;
  error?: boolean;
};

function toDisplayMessages(
  items: unknown[] | null | undefined,
): DisplayMessage[] {
  const out: DisplayMessage[] = [];
  for (const item of items || []) {
    const normalized = normalizeMessage(item);
    if (!normalized) continue;
    if (normalized.role !== "user" && normalized.role !== "assistant") continue;
    out.push({
      role: normalized.role,
      content: displayMessageContent(normalized.content),
      created_at: normalized.created_at,
    });
  }
  return out;
}

type LastTurnMeta = {
  model: string | null;
  intent: string | null;
  complexity: string | null;
  knowledgeCount: number;
  streaming: "idle" | "streaming" | "degraded" | "complete" | "failed";
  reasoning: ReasoningSummary | null;
  knowledgeSources: KnowledgeSource[];
  cognitionMode: string | null;
  cognitionStatus: string | null;
  cognitionPhase: string | null;
  language: string | null;
  languageSource: string | null;
  reasoningMode: string | null;
  memoryCount: number;
  verification: string | null;
  telemetry: ReturnType<typeof deriveAssistantTelemetry> | null;
  activity: ActivityProjection | null;
  activityMode: ActivityDisplayMode;
  decisionReceipts: DecisionReceipt[];
};

const EMPTY_TURN: LastTurnMeta = {
  model: null,
  intent: null,
  complexity: null,
  knowledgeCount: 0,
  streaming: "idle",
  reasoning: null,
  knowledgeSources: [],
  cognitionMode: null,
  cognitionStatus: null,
  cognitionPhase: null,
  language: null,
  languageSource: null,
  reasoningMode: null,
  memoryCount: 0,
  verification: null,
  telemetry: null,
  activity: null,
  activityMode: "detailed",
  decisionReceipts: [],
};

function conversationDeepLink(id: string): string {
  return `${window.location.origin}/chat?conversation=${encodeURIComponent(id)}`;
}

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

type ChatVisualFixtureUi = {
  activeConversationId?: string;
  selectedModelId?: string | null;
  reasoningMode?: ReasoningModeId;
  collaborationStrategy?: "direct" | "team";
  lastTurn?: LastTurnMeta;
};

function readChatVisualFixtureUi(): ChatVisualFixtureUi | null {
  if (typeof window === "undefined") return null;
  const w = window as Window & {
    __LV_V2_VISUAL_FIXTURE__?: boolean;
    __LV_CHAT_V2_FIXTURE_UI__?: ChatVisualFixtureUi;
  };
  if (!w.__LV_V2_VISUAL_FIXTURE__ || !w.__LV_CHAT_V2_FIXTURE_UI__) return null;
  return w.__LV_CHAT_V2_FIXTURE_UI__;
}

function applyChatVisualFixtureUi(
  fixtureUi: ChatVisualFixtureUi,
  setters: {
    setSelectedModelId: (id: string | null) => void;
    setReasoningMode: (mode: ReasoningModeId) => void;
    setCollaborationStrategy: (strategy: "direct" | "team") => void;
    setLastTurn: (turn: LastTurnMeta) => void;
  },
): void {
  if (fixtureUi.selectedModelId !== undefined) {
    setters.setSelectedModelId(fixtureUi.selectedModelId);
  }
  if (fixtureUi.reasoningMode) setters.setReasoningMode(parseReasoningMode(fixtureUi.reasoningMode));
  if (fixtureUi.collaborationStrategy) {
    setters.setCollaborationStrategy(fixtureUi.collaborationStrategy);
  }
  if (fixtureUi.lastTurn) {
    setters.setLastTurn({ ...EMPTY_TURN, ...fixtureUi.lastTurn });
  }
}

function buildChatSidebarStatus(
  health: HealthResponse | null,
  telemetry: ReturnType<typeof useSystemTelemetry>["sample"],
): SidebarStatusRow[] {
  const lm = normalizeLmStudioStatus(health);
  const rows: SidebarStatusRow[] = [
    {
      id: "lm-studio",
      label: lm.label,
      value: lm.value,
      tone: lm.tone,
    },
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

const QUICK_PROMPTS = chatQuickPrompts();

export function ChatPage() {
  const toast = useAppToast();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const draft = (location.state as LocationState | null)?.draft;
  const frozen = visualFixtureNow();
  const { sample: systemTelemetry } = useSystemTelemetry({ intervalMs: 2000 });

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [title, setTitle] = useState("New conversation");
  const [composer, setComposer] = useState(draft ?? "");
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [reasoningMode, setReasoningMode] = useState<ReasoningModeId>("auto");
  const [collaborationStrategy, setCollaborationStrategy] = useState<"direct" | "team">("direct");
  const [teamPanel, setTeamPanel] = useState<Record<string, unknown> | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityListItem[]>([]);
  const [agentsEnabled, setAgentsEnabled] = useState<boolean | null>(null);
  const [codingEnabled, setCodingEnabled] = useState<boolean | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [lastTurn, setLastTurn] = useState<LastTurnMeta>(EMPTY_TURN);
  const [bootstrapped, setBootstrapped] = useState(false);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const [inspectorDrawerOpen, setInspectorDrawerOpen] = useState(false);
  const [newChatMenuOpen, setNewChatMenuOpen] = useState(false);
  const [manageMenuOpen, setManageMenuOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [renameBusy, setRenameBusy] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const historySearchRef = useRef<HTMLInputElement | null>(null);
  const newChatMenuRef = useRef<HTMLDivElement | null>(null);
  const manageMenuRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const creatingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const activeConversation = useMemo(
    () => conversations.find((item) => item.id === conversationId) ?? null,
    [conversations, conversationId],
  );

  const { eligible: chatModels, ineligible: nonChatModels } = useMemo(
    () => partitionChatModels(models),
    [models],
  );

  const modelLabel = useMemo(() => {
    if (!selectedModelId) return "Auto";
    const match = chatModels.find((item) => item.id === selectedModelId);
    return match?.displayName || match?.id || selectedModelId;
  }, [chatModels, selectedModelId]);

  const contextWindow = useMemo(() => {
    if (!selectedModelId) return null;
    const match = chatModels.find((item) => item.id === selectedModelId);
    return match?.contextWindow ?? null;
  }, [chatModels, selectedModelId]);

  const sidebarStatus = useMemo(
    () => buildChatSidebarStatus(health, systemTelemetry),
    [health, systemTelemetry],
  );

  const v2Online = useMemo(() => {
    if (health?.ok === true) return true;
    if (health?.llm?.available === false) return false;
    if (health?.ok === false) return false;
    return null;
  }, [health]);

  const diagnosticStrip = useMemo(
    () => buildDiagnosticStrip(lastTurn.telemetry),
    [lastTurn.telemetry],
  );

  const tokenUsage =
    lastTurn.telemetry?.context_used ?? lastTurn.telemetry?.context_tokens ?? null;
  const contextBudget = lastTurn.telemetry?.context_budget ?? contextWindow;

  useEffect(() => {
    if (!selectedModelId) return;
    const stillEligible = chatModels.some((item) => item.id === selectedModelId);
    if (!stillEligible) {
      setSelectedModelId(null);
      toast("Selected model is not chat-capable — switched to Auto");
    }
  }, [chatModels, selectedModelId, toast]);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    creatingRef.current = creating;
  }, [creating]);

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

  function syncUrl(id: string | null) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("conversation", id);
        else next.delete("conversation");
        return next;
      },
      { replace: true },
    );
  }

  async function loadMemoryCount() {
    try {
      const data = await api.listMemory({ status: "ACTIVE", limit: 100 });
      setMemoryCount(Array.isArray(data.memory) ? data.memory.length : null);
    } catch {
      setMemoryCount(null);
    }
  }

  async function refreshBootstrapData() {
    const [healthData, coding, modelData, caps] = await Promise.all([
      api.health().catch(() => null),
      api.codingStatus().catch(() => null),
      api.listModels().catch(() => null),
      api.listCapabilities({ limit: 50 }).catch(() => null),
    ]);
    if (healthData) {
      setHealth(healthData);
      setAgentsEnabled(Boolean(healthData.agents?.enabled));
    } else {
      setHealth(null);
      setAgentsEnabled(null);
    }
    if (coding) {
      setCodingEnabled(Boolean(coding.enabled));
    } else {
      setCodingEnabled(null);
    }
    if (modelData) {
      setModels(modelData.models ?? []);
    }
    if (caps) {
      setCapabilities(caps.capabilities ?? []);
    }
    await loadMemoryCount();
  }

  async function refreshConversations(selectId?: string | null) {
    const data = await api.listConversations();
    setConversations(data.conversations);
    if (selectId) {
      setConversationId(selectId);
      syncUrl(selectId);
    }
    return data.conversations;
  }

  async function loadConversation(id: string, known?: Conversation[]) {
    if (busyRef.current) return;
    const data = await api.getConversation(id);
    setConversationId(id);
    syncUrl(id);
    setTitle(data.conversation.title);
    setMessages(toDisplayMessages(data.messages));
    setLastTurn(EMPTY_TURN);
    setTeamPanel(null);
    const list = known ?? (await refreshConversations(id));
    setConversations(list);
    setHistoryDrawerOpen(false);
  }

  async function reconcileConversation(id: string) {
    try {
      const data = await api.getConversation(id);
      setConversationId(id);
      syncUrl(id);
      setTitle(data.conversation.title);
      setMessages(toDisplayMessages(data.messages));
      await refreshConversations(id);
    } catch (error) {
      toast(
        `Could not reload conversation: ${error instanceof Error ? error.message : "unknown error"}`,
      );
    }
  }

  async function createConversation() {
    if (busyRef.current || creatingRef.current) return;
    // Draft only — durable conversation is created on first Send.
    setNewChatMenuOpen(false);
    setConversationId(null);
    setTitle("New conversation");
    setMessages([]);
    setLastTurn(EMPTY_TURN);
    setTeamPanel(null);
    setComposer("");
    syncUrl(null);
    requestAnimationFrame(() => composerRef.current?.focus());
  }

  async function onV2Refresh() {
    setRefreshing(true);
    try {
      await refreshBootstrapData();
      await refreshConversations(conversationId);
    } catch (error) {
      toast(`Refresh failed: ${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const [healthData, coding, modelData, caps] = await Promise.all([
          api.health().catch(() => null),
          api.codingStatus().catch(() => null),
          api.listModels().catch(() => null),
          api.listCapabilities({ limit: 50 }).catch(() => null),
        ]);
        if (cancelled) return;
        if (healthData) {
          setHealth(healthData);
          setAgentsEnabled(Boolean(healthData.agents?.enabled));
        } else {
          setAgentsEnabled(null);
        }
        if (coding) {
          setCodingEnabled(Boolean(coding.enabled));
        } else {
          setCodingEnabled(null);
        }
        if (modelData) {
          setModels(modelData.models ?? []);
        }
        if (caps) {
          setCapabilities(caps.capabilities ?? []);
        }
        await loadMemoryCount();
      } catch {
        /* parallel load already guarded */
      }

      try {
        const listed = await api.listConversations();
        if (cancelled) return;
        setConversations(listed.conversations);

        const fixtureUi = readChatVisualFixtureUi();
        const deepLinkId =
          searchParams.get("conversation") ||
          (fixtureUi?.activeConversationId ? String(fixtureUi.activeConversationId) : null);

        if (deepLinkId) {
          try {
            await loadConversation(deepLinkId, listed.conversations);
          } catch (error) {
            if (cancelled) return;
            toast(
              `Conversation not found: ${error instanceof Error ? error.message : "invalid id"}`,
            );
            if (listed.conversations.length > 0) {
              await loadConversation(listed.conversations[0].id, listed.conversations);
            } else {
              setConversationId(null);
              setMessages([]);
              setTitle("New conversation");
              syncUrl(null);
              await createConversation();
            }
          }
        } else if (listed.conversations.length > 0) {
          await loadConversation(listed.conversations[0].id, listed.conversations);
        } else {
          await createConversation();
        }

        // TEST-ONLY: hydrate Screen 1 visual fixture controls + last-turn inspector.
        if (!cancelled && fixtureUi) {
          applyChatVisualFixtureUi(fixtureUi, {
            setSelectedModelId,
            setReasoningMode,
            setCollaborationStrategy,
            setLastTurn,
          });
        }
      } catch (error) {
        if (cancelled) return;
        setMessages([]);
        setTitle("New conversation");
        toast(`Backend unavailable: ${error instanceof Error ? error.message : "unknown error"}`);
      } finally {
        if (!cancelled) setBootstrapped(true);
      }
    })();

    return () => {
      cancelled = true;
    };
    // Bootstrap once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function copyLocalLink(id: string | null) {
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
  }

  async function togglePinned() {
    if (!conversationId || busy) return;
    setManageMenuOpen(false);
    const nextPinned = !activeConversation?.pinned;
    try {
      await api.updateConversation(conversationId, { pinned: nextPinned });
      await refreshConversations(conversationId);
      toast(nextPinned ? "Pinned" : "Unpinned");
    } catch (error) {
      toast(`Pin failed: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  function openRenameDialog() {
    if (!conversationId) return;
    setManageMenuOpen(false);
    setRenameValue(activeConversation?.title ?? title);
    setRenameOpen(true);
  }

  async function confirmRename() {
    if (!conversationId) return;
    const current = activeConversation?.title ?? title;
    const trimmed = renameValue.trim();
    if (!trimmed || trimmed === current) {
      setRenameOpen(false);
      return;
    }
    setRenameBusy(true);
    try {
      const data = await api.updateConversation(conversationId, { title: trimmed });
      setTitle(data.conversation.title);
      await refreshConversations(conversationId);
      toast("Renamed");
      setRenameOpen(false);
    } catch (error) {
      toast(`Rename failed: ${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setRenameBusy(false);
    }
  }

  function openDeleteDialog() {
    if (!conversationId) return;
    setManageMenuOpen(false);
    setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!conversationId) return;
    const deletingId = conversationId;
    setDeleteBusy(true);
    try {
      await api.deleteConversation(deletingId);
      const list = await api.listConversations();
      setConversations(list.conversations);
      toast("Deleted");
      setDeleteOpen(false);
      if (list.conversations.length > 0) {
        await loadConversation(list.conversations[0].id, list.conversations);
      } else {
        setConversationId(null);
        setMessages([]);
        setTitle("New conversation");
        setLastTurn(EMPTY_TURN);
        syncUrl(null);
        await createConversation();
      }
    } catch (error) {
      toast(`Delete failed: ${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setDeleteBusy(false);
    }
  }

  async function sendMessage() {
    const text = composer.trim();
    if (!text || busy || busyRef.current) return;
    busyRef.current = true;

    let activeId = conversationId;
    if (!activeId) {
      if (creatingRef.current) {
        busyRef.current = false;
        return;
      }
      setCreating(true);
      creatingRef.current = true;
      try {
        const created = await api.createConversation();
        activeId = created.conversation.id;
        setConversationId(activeId);
        setTitle(created.conversation.title);
        syncUrl(activeId);
        await refreshConversations(activeId);
      } catch (error) {
        toast(`Could not create chat: ${error instanceof Error ? error.message : "unknown error"}`);
        creatingRef.current = false;
        setCreating(false);
        busyRef.current = false;
        return;
      } finally {
        creatingRef.current = false;
        setCreating(false);
      }
    }

    setComposer("");
    setMessages((current) => [
      ...current,
      { role: "user", content: text, created_at: new Date().toISOString() },
      { role: "assistant", content: "Thinking…", created_at: null, pending: true },
    ]);
    setBusy(true);
    const activityProjector = new ActivityClientProjector();
    setLastTurn((prev) => ({
      ...prev,
      streaming: "streaming",
      activity: activityProjector.project(),
      decisionReceipts: [],
    }));
    const abort = new AbortController();
    abortRef.current = abort;

    try {
      let doneOnce = false;
      const data = await api.chatStream(
        text,
        {
          conversationId: activeId,
          modelId: selectedModelId,
          reasoningMode: reasoningModeForApi(reasoningMode),
          collaborationStrategy:
            collaborationStrategy === "team" ? "team" : null,
          idempotencyKey:
            typeof crypto !== "undefined" && "randomUUID" in crypto
              ? crypto.randomUUID()
              : `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        },
        {
          onMeta: (meta) => {
            const projection = parseActivityProjection(meta.activity);
            if (projection) {
              activityProjector.ingestProjection(projection);
              setLastTurn((prev) => ({
                ...prev,
                activity: activityProjector.project(),
                streaming: "streaming",
              }));
            }
            if (meta.reasoning && typeof meta.reasoning === "object") {
              setLastTurn((prev) => ({
                ...prev,
                reasoning: meta.reasoning as ReasoningSummary,
              }));
            }
          },
          onActivity: (payload) => {
            // Full projection vs single event.
            if (payload && typeof payload === "object" && Array.isArray((payload as { tree?: unknown }).tree)) {
              activityProjector.ingestProjection(parseActivityProjection(payload));
            } else {
              activityProjector.ingest(payload);
            }
            setLastTurn((prev) => ({
              ...prev,
              activity: activityProjector.project(),
              streaming: prev.streaming === "idle" ? "streaming" : prev.streaming,
            }));
          },
          onToken: (token) => {
            setMessages((current) => {
              const copy = [...current];
              const last = copy[copy.length - 1];
              if (last?.pending && last.role === "assistant") {
                const base = last.content === "Thinking…" ? "" : last.content;
                copy[copy.length - 1] = {
                  ...last,
                  content: `${base}${token}`,
                };
              }
              return copy;
            });
          },
          onSnapshot: (snapshotText) => {
            setMessages((current) => {
              const copy = [...current];
              const last = copy[copy.length - 1];
              if (last?.pending && last.role === "assistant") {
                copy[copy.length - 1] = {
                  ...last,
                  content: snapshotText,
                };
              }
              return copy;
            });
          },
          onDone: () => {
            doneOnce = true;
          },
          onCapabilityEvent: (event, payload) => {
            // Operational status only — surface as a pending assistant status line.
            // job.* events reuse shared JobRuntime label semantics (Datasets/Training).
            const cap = String(
              payload.capability_id || payload.module_id || payload.job_id || event,
            );
            let statusLabel = "";
            if (event.startsWith("job.")) {
              const raw =
                payload.state ||
                payload.status ||
                payload.phase ||
                event.replace(/^job\./, "");
              statusLabel = formatJobStateLabel(normalizeJobStatus(String(raw)));
              const pct = payload.progress ?? payload.percent;
              // Only show measured job progress when backend reports a finite value.
              if (typeof pct === "number" && Number.isFinite(pct)) {
                statusLabel = `${statusLabel} · ${Math.round(pct * (pct <= 1 ? 100 : 1))}%`;
              }
            } else {
              const status = String(payload.status || payload.phase || "");
              statusLabel = status && status !== event ? status : "";
            }
            setMessages((current) => {
              const copy = [...current];
              const last = copy[copy.length - 1];
              if (last?.pending && last.role === "assistant") {
                const prev = last.content === "Thinking…" ? "" : last.content;
                const line = `[${event}] ${cap}${statusLabel ? ` · ${statusLabel}` : ""}`;
                // Keep the last status line short; don't accumulate private detail.
                const withoutStatus = prev.replace(/\n?\[[^\]]+\].*$/s, "").trimEnd();
                copy[copy.length - 1] = {
                  ...last,
                  content: withoutStatus ? `${withoutStatus}\n${line}` : line,
                };
              }
              return copy;
            });
          },
        },
        { signal: abort.signal },
      );
      setConversationId(data.conversation_id);
      syncUrl(data.conversation_id);

      const protocolFailure =
        typeof (data as { protocol_failure?: unknown }).protocol_failure === "string"
          ? String((data as { protocol_failure?: string }).protocol_failure)
          : null;
      const isProvisional = Boolean(data.provisional) || Boolean(protocolFailure);
      const assistantNormalized = normalizeMessage(data.assistant_message);
      const assistantContent = assistantNormalized
        ? displayMessageContent(assistantNormalized.content)
        : "";

      setMessages((current) => {
        const withoutPending = current.filter((item) => !item.pending);
        // Prefer canonical assistant message when valid; else keep streamed provisional text.
        if (doneOnce || assistantNormalized) {
          const streamedProvisional = current.find((item) => item.pending && item.role === "assistant");
          const streamedText =
            streamedProvisional && streamedProvisional.content !== "Thinking…"
              ? streamedProvisional.content
              : "";
          const content =
            assistantContent ||
            (isProvisional ? streamedText : streamedText) ||
            (protocolFailure
              ? `Stream protocol failure (${protocolFailure}). Partial reply may be incomplete.`
              : "");
          return [
            ...withoutPending,
            {
              role: "assistant",
              content,
              created_at: assistantNormalized?.created_at ?? new Date().toISOString(),
              error: Boolean(protocolFailure),
            },
          ];
        }
        return withoutPending;
      });

      if (protocolFailure) {
        setLastTurn((prev) => ({ ...prev, streaming: "failed" }));
        toast(`Chat protocol failure: ${protocolFailure}`);
        // Clear stale TEAM state on every terminal turn without team payload.
        setTeamPanel(null);
        const list = await refreshConversations(data.conversation_id || activeId);
        if (data.conversation_id) {
          const active = list.find((item) => item.id === data.conversation_id);
          if (active) setTitle(active.title);
        }
        return;
      }

      const degraded = Boolean(data.truth?.streaming_degraded);
      const cog = data.cognition && typeof data.cognition === "object" ? data.cognition : null;
      const cogDecision =
        cog && "decision" in cog && cog.decision && typeof cog.decision === "object"
          ? (cog.decision as Record<string, unknown>)
          : null;
      const cogStatus =
        cog && "status" in cog && typeof cog.status === "string" ? cog.status : null;
      const telemetry = deriveAssistantTelemetry(data);
      const verificationLabel =
        telemetry.verification_mode && telemetry.verification_mode !== "NONE"
          ? telemetry.verification_passed === true
            ? `${telemetry.verification_mode} · passed`
            : telemetry.verification_passed === false
              ? `${telemetry.verification_mode} · failed`
              : `${telemetry.verification_mode}`
          : data.quality?.pass === false
            ? "issues found"
            : data.quality
              ? "ok"
              : "not required";
      setLastTurn({
        model: telemetry.model || data.model || null,
        intent: data.reasoning?.intent ?? null,
        complexity: data.reasoning?.complexity ?? null,
        knowledgeCount: telemetry.knowledge_hits ?? data.knowledge_sources?.length ?? 0,
        streaming: degraded ? "degraded" : "complete",
        reasoning: data.reasoning ?? null,
        knowledgeSources: data.knowledge_sources ?? [],
        cognitionMode:
          telemetry.cognition_mode ||
          (cogDecision && typeof cogDecision.mode === "string" ? String(cogDecision.mode) : null),
        cognitionStatus: telemetry.cognition_status || cogStatus,
        cognitionPhase:
          cogStatus && ["REASONING", "PERCEIVING", "VERIFYING", "EXECUTING"].includes(cogStatus)
            ? cogStatus.charAt(0) + cogStatus.slice(1).toLowerCase()
            : null,
        language: data.language?.response_language ?? null,
        languageSource: data.language?.source ?? null,
        reasoningMode: data.reasoning?.mode?.effective ?? reasoningMode,
        memoryCount: telemetry.memory_hits ?? data.memory_sources?.length ?? 0,
        verification: verificationLabel,
        telemetry,
        activity: (() => {
          if (data.activity) {
            activityProjector.ingestProjection(parseActivityProjection(data.activity));
          }
          if (Array.isArray(data.activity_events)) {
            activityProjector.ingestMany(data.activity_events);
          }
          return activityProjector.project();
        })(),
        activityMode: "detailed",
        decisionReceipts: Array.isArray(data.decision_receipts)
          ? (data.decision_receipts as DecisionReceipt[])
          : [],
      });
      // TEAM state must never linger into a later normal response.
      const teamPayload = data.team;
      if (teamPayload && typeof teamPayload === "object") {
        setTeamPanel(teamPayload);
      } else {
        setTeamPanel(null);
      }
      const list = await refreshConversations(data.conversation_id);
      const active = list.find((item) => item.id === data.conversation_id);
      if (active) setTitle(active.title);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Request failed";
      activityProjector.markDisconnected();
      setLastTurn((prev) => ({
        ...prev,
        streaming: "failed",
        activity: activityProjector.project(),
      }));
      setTeamPanel(null);
      setMessages((current) => {
        const withoutPending = current.filter((item) => !item.pending);
        const streamed = current.find((item) => item.pending && item.role === "assistant");
        const provisional =
          streamed && streamed.content && streamed.content !== "Thinking…"
            ? streamed.content
            : null;
        return [
          ...withoutPending,
          {
            role: "assistant",
            content: provisional
              ? `${provisional}\n\n[Provisional — request failed: ${detail}]`
              : `Leviathan could not reach the configured LLM. ${detail}`,
            created_at: new Date().toISOString(),
            error: true,
          },
        ];
      });
      toast(detail);
      if (activeId) {
        await reconcileConversation(activeId);
      } else {
        await refreshConversations(null);
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function openHistoryDrawer() {
    setInspectorDrawerOpen(false);
    setHistoryDrawerOpen(true);
    requestAnimationFrame(() => historySearchRef.current?.focus());
  }

  const pinned = Boolean(activeConversation?.pinned);

  // Reference runtime flags so bootstrap stays typed-used (noUnusedLocals).
  const runtimeMeta =
    agentsEnabled != null || codingEnabled != null
      ? `agents=${agentsEnabled === null ? "?" : agentsEnabled ? "on" : "off"} · coding=${
          codingEnabled === null ? "?" : codingEnabled ? "on" : "off"
        }`
      : null;

  const v2Actions = (
    <>
      <div style={{ position: "relative" }} ref={newChatMenuRef}>
        <div className="lv-v2-topbar__action-split">
          <button
            type="button"
            className="lv-v2-topbar__action-btn lv-v2-topbar__action-btn--primary"
            disabled={busy || creating || !bootstrapped}
            onClick={() => void createConversation()}
          >
            + Nieuwe chat
          </button>
          <button
            type="button"
            className="lv-v2-topbar__action-split__chevron"
            aria-label="Nieuwe chat opties"
            aria-expanded={newChatMenuOpen}
            disabled={busy || creating || !bootstrapped}
            onClick={() => {
              setManageMenuOpen(false);
              setNewChatMenuOpen((open) => !open);
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="currentColor" d="M7 10l5 5 5-5" />
            </svg>
          </button>
        </div>
        {newChatMenuOpen ? (
          <div className="lv-v2-topbar__action-menu" role="menu">
            <button
              type="button"
              role="menuitem"
              onClick={() => void createConversation()}
            >
              Nieuwe lege chat
            </button>
            {selectedModelId ? (
              <button
                type="button"
                role="menuitem"
                onClick={() => void createConversation()}
                title={`Model blijft: ${modelLabel}`}
              >
                met huidig model ({modelLabel})
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div style={{ position: "relative" }} ref={manageMenuRef}>
        <button
          type="button"
          className="lv-v2-topbar__action-btn"
          aria-expanded={manageMenuOpen}
          disabled={!conversationId}
          onClick={() => {
            setNewChatMenuOpen(false);
            setManageMenuOpen((open) => !open);
          }}
        >
          Manage
        </button>
        {manageMenuOpen ? (
          <div className="lv-v2-topbar__action-menu" role="menu">
            <button type="button" role="menuitem" onClick={openRenameDialog}>
              Rename
            </button>
            <button type="button" role="menuitem" onClick={() => void togglePinned()}>
              {pinned ? "Unpin" : "Pin"}
            </button>
            <button type="button" role="menuitem" onClick={openDeleteDialog}>
              Delete
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setManageMenuOpen(false);
                void copyLocalLink(conversationId);
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
        onClick={openHistoryDrawer}
      >
        Gesprekken
      </button>
    </>
  );

  return (
    <AppShell
      variant="v2"
      v2Title="Hades AI / Chat"
      v2Subtitle="Geavanceerde AI-assistentie met redeneren, tools en betrouwbare bronnen"
      v2Online={v2Online}
      v2StatusRows={sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
      v2Actions={v2Actions}
      v2HideRefresh={true}
      v2Refreshing={refreshing}
      onV2Refresh={() => {
        void onV2Refresh();
      }}
    >
      <main className="lv-v2-page lv-v2-page--chat">
        <HadesConfigStrip
          models={chatModels}
          nonChatModels={nonChatModels}
          selectedModelId={selectedModelId}
          onSelectModel={setSelectedModelId}
          collaborationStrategy={collaborationStrategy}
          onCollaborationChange={setCollaborationStrategy}
          reasoningMode={reasoningMode}
          onReasoningChange={setReasoningMode}
          capabilities={capabilities}
          busy={busy}
        />

        <button
          type="button"
          className={`lv-v2-chat-drawer-backdrop${
            historyDrawerOpen || inspectorDrawerOpen ? " is-open" : ""
          }`}
          aria-label="Sluit paneel"
          onClick={() => {
            setHistoryDrawerOpen(false);
            setInspectorDrawerOpen(false);
          }}
        />

        <div className="lv-v2-chat-workspace">
          <ConversationHistoryPanel
            conversations={conversations}
            activeId={conversationId}
            onSelect={(id) => void loadConversation(id)}
            onCreate={() => void createConversation()}
            bootstrapped={bootstrapped}
            creating={creating}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            drawerOpen={historyDrawerOpen}
            searchInputRef={historySearchRef}
            now={frozen ?? undefined}
          />

          <div className="lv-v2-chat-col lv-v2-chat-center">
            <MessageList
              messages={messages}
              lastTurn={{
                reasoning: lastTurn.reasoning,
                cognitionPhase: lastTurn.cognitionPhase,
                streaming: lastTurn.streaming,
                telemetry: lastTurn.telemetry,
                reasoningElapsedMs:
                  typeof (lastTurn.telemetry as { reasoning_elapsed_ms?: number } | null)
                    ?.reasoning_elapsed_ms === "number"
                    ? (lastTurn.telemetry as { reasoning_elapsed_ms?: number }).reasoning_elapsed_ms
                    : null,
                activity: lastTurn.activity,
                activityMode: lastTurn.activityMode,
                decisionReceipts: lastTurn.decisionReceipts,
              }}
              onActivityModeChange={(mode) =>
                setLastTurn((prev) => ({ ...prev, activityMode: mode }))
              }
            />
            <ChatComposer
              value={composer}
              onChange={setComposer}
              onSend={() => void sendMessage()}
              onStop={() => {
                abortRef.current?.abort();
                abortRef.current = null;
              }}
              busy={busy}
              disabled={!bootstrapped}
              reasoningMode={reasoningMode}
              onReasoningChange={setReasoningMode}
              capabilities={capabilities}
              contextWindow={contextWindow}
              selectedModelId={selectedModelId}
              quickPrompts={messages.length === 0 ? QUICK_PROMPTS : []}
              textareaRef={composerRef}
            />
            {diagnosticStrip.length > 0 || teamPanel || runtimeMeta ? (
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
                {diagnosticStrip.map((item) => (
                  <span key={item.label}>
                    {item.label}={item.value}
                  </span>
                ))}
                {teamPanel ? (
                  <span>
                    TEAM {String(teamPanel.quality_label ?? teamPanel.status ?? "—")}
                  </span>
                ) : null}
                {runtimeMeta ? <span>{runtimeMeta}</span> : null}
              </div>
            ) : null}
          </div>

          <ChatInspector
            tokenUsage={tokenUsage}
            contextBudget={contextBudget}
            memoryCount={memoryCount}
            preferencesLabel={null}
            projectContext={null}
            knowledgeSources={lastTurn.knowledgeSources}
            verification={lastTurn.verification}
            systemTelemetry={systemTelemetry}
            lastTurnTelemetry={lastTurn.telemetry}
            drawerOpen={inspectorDrawerOpen}
          />
        </div>
      </main>

      <Dialog
        open={renameOpen}
        title="Hernoem gesprek"
        description="Geef dit gesprek een nieuwe titel."
        confirmLabel="Opslaan"
        cancelLabel="Annuleren"
        busy={renameBusy}
        onClose={() => {
          if (!renameBusy) setRenameOpen(false);
        }}
        onConfirm={() => void confirmRename()}
      >
        <label className="lv-v2-sr-only" htmlFor="chat-rename-input">
          Titel
        </label>
        <input
          id="chat-rename-input"
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void confirmRename();
            }
          }}
          disabled={renameBusy}
        />
      </Dialog>

      <Dialog
        open={deleteOpen}
        title="Gesprek verwijderen"
        description="Delete this conversation? This cannot be undone."
        confirmLabel="Verwijderen"
        cancelLabel="Annuleren"
        danger
        busy={deleteBusy}
        onClose={() => {
          if (!deleteBusy) setDeleteOpen(false);
        }}
        onConfirm={() => void confirmDelete()}
      />
    </AppShell>
  );
}
