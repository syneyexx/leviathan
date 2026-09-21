"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useChatRun, type ChatRunProgress } from "@/components/hades/features/chat/hooks/useChatRun";
import { useChatDoctor } from "@/components/hades/features/chat/ChatDoctorBanner";
import type { PinBundle } from "@/components/hades/features/chat/ChatPinsBar";
import type { CodingCardJob } from "@/components/hades/features/chat/CodingCard";
import type { ResearchCardState } from "@/components/hades/features/chat/ResearchCard";
import type { WorkCardState } from "@/components/hades/features/chat/ApprovalWorkCards";
import type {
  ChatExecutionState,
  PendingAttachment,
} from "@/components/hades/features/chat/types";
import {
  attachmentIdsFromPending,
  budgetToolRounds,
  collectUnifiedStopTargets,
  contextBudgetTokens,
  conversationListTime,
  draftAttachmentsFromIds,
  estimateTokensFromText,
  mapSendResultToExecution,
  markCardsCancelled,
  newChatRequestId,
  pickCanvasArtifact,
  resolveConversationModelId,
  scopePendingApprovals,
  shouldApplyStreamToSelection,
  shouldIgnoreCancelledCompletion,
  validateAttachmentBatch,
} from "@/components/hades/features/chat/chat-runtime-core";
import {
  mergeChatToolCalls,
  mergeLiveExecutionEvents,
} from "@/components/hades/features/chat/live-execution-merge";
import {
  EMPTY_MODEL_USAGE,
  type ChatTelemetryExtras,
  type ModelUsageState,
  type UsageKind,
  type UsageStatus,
} from "@/components/hades/model-usage-card";
import { useVoiceDictation } from "@/hooks/use-voice-dictation";
import { useVoicePlayback } from "@/hooks/use-voice-playback";
import { useVoiceSession } from "@/hooks/use-voice-session";
import { useHashSelectionSync } from "@/hooks/use-hash-selection";
import { consumeChatHandoff } from "@/lib/chat-handoff";
import { readHashSelection } from "@/lib/hash-query";
import { hadesSpeechPlayer, type SpeechPlayerState } from "@/lib/hades-speech";
import {
  normalizeReasoningMode,
  reasoningModeLabel,
  reasoningProfileForRequest,
  type ProductReasoningMode,
} from "@/lib/reasoning-mode";
import {
  ChatMessage,
  Conversation,
  ConversationBranch,
  HadesArtifact,
  LmModel,
  ModelProfile,
  SystemHealth,
  hadesApi,
} from "@/lib/hades-api";
import {
  CHAT_APPROVALS_POLL_MS,
  CHAT_USAGE_POLL_ACTIVE_MS,
  CHAT_USAGE_POLL_IDLE_MS,
} from "@/lib/ui-poll-intervals";

export { conversationListTime };

export type SendMessageOptions = {
  revise_message_id?: string;
  regenerate_of?: string;
  content?: string;
  metadata?: Record<string, unknown>;
};

export type BranchCompareSide = {
  branchId: string;
  title: string;
  text: string;
  empty: boolean;
};

function mapUsageTelemetry(
  snap: Awaited<ReturnType<typeof hadesApi.chatUsageTelemetry>>,
  previous: ModelUsageState,
): ModelUsageState {
  const current = snap.current || { total_tokens: null, input_tokens: null, output_tokens: null, kind: "unavailable" };
  const kind = (String(current.kind || previous.kind) as UsageKind) || previous.kind;
  const history = Array.isArray(snap.history)
    ? snap.history
        .map((item) => ({
          at: typeof item.at === "number" ? (item.at < 1e12 ? item.at * 1000 : item.at) : Date.now(),
          total: typeof item.total_tokens === "number" ? item.total_tokens : null,
        }))
        .slice(-60)
    : previous.history;
  const modelCalls = typeof snap.model_calls === "number" ? snap.model_calls : previous.modelCalls;
  const rawSession = typeof snap.totals?.session_tokens === "number" ? snap.totals.session_tokens : null;
  const rawConversation = typeof snap.totals?.conversation_tokens === "number" ? snap.totals.conversation_tokens : null;
  const unused = kind === "unavailable" && (modelCalls == null || modelCalls === 0) && !history.some((item) => item.total != null);
  return {
    status: (String(snap.status || previous.status) as UsageStatus) || previous.status,
    modelId: String(snap.model_id || previous.modelId || ""),
    currentTotal: typeof current.total_tokens === "number" ? current.total_tokens : previous.currentTotal,
    currentInput: typeof current.input_tokens === "number" ? current.input_tokens : previous.currentInput,
    currentOutput: typeof current.output_tokens === "number" ? current.output_tokens : previous.currentOutput,
    kind,
    peakTotal: typeof snap.peak?.total_tokens === "number" ? snap.peak.total_tokens : previous.peakTotal,
    sessionTotal: unused ? null : (rawSession ?? previous.sessionTotal),
    conversationTotal: unused ? null : (rawConversation ?? previous.conversationTotal),
    modelCalls: unused ? null : modelCalls,
    history: history.length ? history : previous.history,
  };
}

function lastAssistantMessage(messages: ChatMessage[]): ChatMessage | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") return messages[index];
  }
  return null;
}

export type HadesChatRuntime = {
  // Core conversation state
  conversations: Conversation[];
  filteredConversations: Conversation[];
  selectedId: string | null;
  selected: Conversation | null;
  messages: ChatMessage[];
  models: LmModel[];
  modelId: string;
  modelConnected: boolean;
  activeDefaultModelId: string;
  modelProfile: ModelProfile | null;
  draft: string;
  draftCursor: number;
  attachments: PendingAttachment[];
  attachmentReport: Array<Record<string, unknown>>;
  searchQuery: string;
  loading: boolean;
  messagesLoading: boolean;
  sending: boolean;
  streamText: string;
  error: string;
  health: SystemHealth | null;
  hostname: string | null;
  titleDraft: string;

  // Reasoning
  reasoningMode: ProductReasoningMode;
  reasoningLabel: string;
  reasoningReady: boolean;
  reasoningSaving: boolean;
  storedReasoningRaw: string;

  // Execution / cards
  lastExecution: ChatExecutionState | null;
  codingCards: CodingCardJob[];
  codingBusy: boolean;
  researchCards: ResearchCardState[];
  researchBusy: boolean;
  workCards: WorkCardState[];
  pendingApprovals: Array<Record<string, unknown>>;
  approvalBusy: string | null;
  pinBundle: PinBundle | null;
  pinsBusy: boolean;

  // Branches
  branches: ConversationBranch[];
  branchesLoading: boolean;
  branchesError: string | null;
  branchActivatingId: string;
  activeBranch: ConversationBranch | null;
  compareMode: boolean;
  compareReady: boolean;
  compareLeftId: string;
  compareRightId: string;
  compareLoading: boolean;
  compareSides: [BranchCompareSide | null, BranchCompareSide | null];

  // Canvas / scratchpad
  canvasOpen: boolean;
  canvasContent: string;
  canvasArtifactId: string | null;
  canvasDirty: boolean;
  canvasLoading: boolean;
  canvasError: string | null;
  canvasSaving: boolean;

  // Usage telemetry
  modelUsage: ModelUsageState;
  runWallMs: number | null;
  chatTelemetry: ChatTelemetryExtras;

  // Voice / speech
  spokenAnswers: boolean;
  speechState: SpeechPlayerState;
  micRecording: boolean;
  sttProvider: "none" | "voicestudio" | "paste";
  ttsProvider: "none" | "voicestudio";
  voiceLanguage: "nl" | "en" | "auto";
  voiceEnabled: boolean;
  voiceTurnMode: "manual" | "auto";
  voiceBargeIn: boolean;
  voiceWakeWord: boolean;
  lastSpokenAnswer: string;
  dictation: ReturnType<typeof useVoiceDictation>;
  playback: ReturnType<typeof useVoicePlayback>;
  voiceSession: ReturnType<typeof useVoiceSession>;

  // Chat doctor
  chatDoctor: ReturnType<typeof useChatDoctor>;

  // Draft / selection actions
  setDraft: (value: string, cursor?: number) => void;
  setDraftCursor: (cursor: number) => void;
  setSearchQuery: (value: string) => void;
  setTitleDraft: (value: string) => void;
  setError: (value: string) => void;
  setCanvasOpen: (open: boolean) => void;
  setCanvasContent: (value: string) => void;
  setCompareMode: (open: boolean) => void;
  setCompareLeftId: (id: string) => void;
  setCompareRightId: (id: string) => void;
  selectConversation: (id: string) => void;
  createConversation: () => Promise<void>;
  deleteConversation: () => Promise<void>;
  refresh: () => Promise<void>;
  refreshConversations: (preferId?: string) => Promise<Conversation[]>;

  // Messaging
  sendMessage: (options?: SendMessageOptions) => Promise<void>;
  cancelGeneration: () => Promise<void>;
  regenerateMessage: (assistantMessage: ChatMessage) => Promise<void>;
  reviseMessage: (userMessage: ChatMessage) => Promise<void>;

  // Model / reasoning / meta
  changeModel: (next: string) => Promise<void>;
  changeReasoningMode: (next: ProductReasoningMode) => Promise<void>;
  renameConversation: (title?: string) => Promise<void>;
  saveSystemPromptOverride: (override: string | null) => Promise<void>;
  exportConversation: () => Promise<void>;

  // Attachments / pins / approvals
  addFiles: (files: File[]) => Promise<void>;
  removeAttachment: (artifactId: string) => void;
  reuseArtifact: (artifact: HadesArtifact) => void;
  persistPins: (paths: string[]) => Promise<void>;
  addPinPath: (path: string) => Promise<void>;
  removePinPath: (path: string) => Promise<void>;
  pickPinFolder: () => Promise<void>;
  decideApproval: (id: string, approve: boolean, note?: string) => Promise<void>;

  // Linked engine card actions
  applyCodingJob: (jobId: string) => Promise<void>;
  rejectCodingJob: (jobId: string) => Promise<void>;
  refreshCodingJob: (jobId: string) => Promise<void>;
  stopResearch: (projectId: string) => Promise<void>;
  goDeeperResearch: (projectId: string) => Promise<void>;
  refreshResearch: (projectId: string) => Promise<void>;
  loadRunEvents: (runId: string) => Promise<void>;

  // Branches / canvas / voice helpers
  branchFromMessage: (message: ChatMessage) => Promise<void>;
  activateBranch: (branchId: string) => Promise<void>;
  openInCanvas: (content: string) => void;
  saveCanvas: () => Promise<void>;
  toggleSpokenAnswers: (checked: boolean) => Promise<void>;
  speakMessage: (message: ChatMessage) => Promise<void>;
  toggleMic: () => Promise<void>;
  copyMessage: (message: ChatMessage) => Promise<void>;
  copiedId: string;
};

/**
 * Shared HADES chat runtime controller — full live behaviour for FINALBETA
 * and future Lux extraction. No JSX; state + actions only.
 */
export function useHadesChatRuntime(): HadesChatRuntime {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [models, setModels] = useState<LmModel[]>([]);
  const [modelId, setModelId] = useState("");
  const [activeDefaultModelId, setActiveDefaultModelId] = useState("");
  const [modelConnected, setModelConnected] = useState(false);
  const [modelProfile, setModelProfile] = useState<ModelProfile | null>(null);
  const [draft, setDraftState] = useState("");
  const [draftCursor, setDraftCursor] = useState(0);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentReport, setAttachmentReport] = useState<Array<Record<string, unknown>>>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState("");
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [hostname, setHostname] = useState<string | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [copiedId, setCopiedId] = useState("");

  const [pendingApprovals, setPendingApprovals] = useState<Array<Record<string, unknown>>>([]);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);
  const [codingCards, setCodingCards] = useState<CodingCardJob[]>([]);
  const [codingBusy, setCodingBusy] = useState(false);
  const [researchCards, setResearchCards] = useState<ResearchCardState[]>([]);
  const [researchBusy, setResearchBusy] = useState(false);
  const [workCards, setWorkCards] = useState<WorkCardState[]>([]);
  const [pinBundle, setPinBundle] = useState<PinBundle | null>(null);
  const [pinsBusy, setPinsBusy] = useState(false);
  const [lastExecution, setLastExecution] = useState<ChatExecutionState | null>(null);
  const [modelUsage, setModelUsage] = useState<ModelUsageState>(EMPTY_MODEL_USAGE);
  const [runWallMs, setRunWallMs] = useState<number | null>(null);

  const [branches, setBranches] = useState<ConversationBranch[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branchesError, setBranchesError] = useState<string | null>(null);
  const [branchActivatingId, setBranchActivatingId] = useState("");
  const [compareMode, setCompareMode] = useState(false);
  const [compareLeftId, setCompareLeftId] = useState("");
  const [compareRightId, setCompareRightId] = useState("");
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareSides, setCompareSides] = useState<[BranchCompareSide | null, BranchCompareSide | null]>([null, null]);

  const [canvasOpen, setCanvasOpen] = useState(true);
  const [canvasContent, setCanvasContent] = useState("");
  const [canvasArtifactId, setCanvasArtifactId] = useState<string | null>(null);
  const [canvasDirty, setCanvasDirty] = useState(false);
  const [canvasLoading, setCanvasLoading] = useState(false);
  const [canvasError, setCanvasError] = useState<string | null>(null);
  const [canvasSaving, setCanvasSaving] = useState(false);

  const [spokenAnswers, setSpokenAnswers] = useState(false);
  const [reasoningMode, setReasoningMode] = useState<ProductReasoningMode>("adaptive");
  const [storedReasoningRaw, setStoredReasoningRaw] = useState("adaptive");
  const [reasoningReady, setReasoningReady] = useState(false);
  const [reasoningSaving, setReasoningSaving] = useState(false);
  const [sttProvider, setSttProvider] = useState<"none" | "voicestudio" | "paste">("paste");
  const [ttsProvider, setTtsProvider] = useState<"none" | "voicestudio">("none");
  const [speechState, setSpeechState] = useState<SpeechPlayerState>(hadesSpeechPlayer.snapshot());
  const [micRecording, setMicRecording] = useState(false);
  const [voiceLanguage, setVoiceLanguage] = useState<"nl" | "en" | "auto">("nl");
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [voiceTurnMode, setVoiceTurnMode] = useState<"manual" | "auto">("manual");
  const [voiceBargeIn, setVoiceBargeIn] = useState(true);
  const [voiceWakeWord, setVoiceWakeWord] = useState(false);
  const [voiceEndSilenceMs, setVoiceEndSilenceMs] = useState(900);
  const [voiceVadSensitivity, setVoiceVadSensitivity] = useState(0.55);
  const [voiceInputDeviceId, setVoiceInputDeviceId] = useState("");
  const [voiceOutputDeviceId, setVoiceOutputDeviceId] = useState("");
  const [voiceVolume, setVoiceVolume] = useState(1);
  const [voiceKeepRecordings, setVoiceKeepRecordings] = useState(false);
  const [voiceIdleTimeoutSeconds, setVoiceIdleTimeoutSeconds] = useState(120);
  const [voiceSpeakStyle, setVoiceSpeakStyle] = useState<"compact" | "full">("compact");
  const [voiceTtsVoice, setVoiceTtsVoice] = useState("nl_NL-pim-medium");
  const [voiceTtsSpeed, setVoiceTtsSpeed] = useState(1);
  const [voiceTtsProvider, setVoiceTtsProvider] = useState<"piper" | "browser">("piper");
  const [lastSpokenAnswer, setLastSpokenAnswer] = useState("");

  const chatDoctor = useChatDoctor();

  const selectedIdRef = useRef<string | null>(null);
  const sendingRef = useRef(false);
  const pendingAutoSendRef = useRef(false);
  const inFlightRequestIdRef = useRef<string | null>(null);
  const inFlightConversationIdRef = useRef<string | null>(null);
  const cancelledRequestIdsRef = useRef<Set<string>>(new Set());
  const runStartedAtRef = useRef<number | null>(null);
  const streamTextRef = useRef("");
  const spokenAnswersRef = useRef(false);
  const draftTimer = useRef<number | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const micChunksRef = useRef<Blob[]>([]);
  const sendRef = useRef<(options?: SendMessageOptions) => Promise<void>>(async () => undefined);
  const lastExecutionRef = useRef<ChatExecutionState | null>(null);
  const codingCardsRef = useRef<CodingCardJob[]>([]);
  const researchCardsRef = useRef<ResearchCardState[]>([]);

  selectedIdRef.current = selectedId;
  sendingRef.current = sending;
  lastExecutionRef.current = lastExecution;
  codingCardsRef.current = codingCards;
  researchCardsRef.current = researchCards;
  streamTextRef.current = streamText || lastExecution?.stream_text || "";
  spokenAnswersRef.current = spokenAnswers;

  const setDraft = useCallback((value: string, cursor?: number) => {
    setDraftState(value);
    if (typeof cursor === "number") setDraftCursor(cursor);
    else setDraftCursor(value.length);
  }, []);

  const applyRunProgress = useCallback((progress: ChatRunProgress) => {
    const requestId = inFlightRequestIdRef.current;
    if (!shouldApplyStreamToSelection({
      selectedConversationId: selectedIdRef.current,
      runConversationId: inFlightConversationIdRef.current,
      requestId,
      activeRequestId: requestId,
    })) {
      return;
    }
    if (progress.streamText != null && progress.streamText !== "") {
      setStreamText(progress.streamText);
    } else if (progress.streamDelta) {
      setStreamText((current) => `${current}${progress.streamDelta}`);
    }
    const hasExecUpdate = Boolean(
      progress.tools.length
      || progress.events.length
      || progress.target
      || progress.routeProfile
      || progress.modelUsage
      || progress.streamFlush,
    );
    if (hasExecUpdate) {
      setLastExecution((current) => ({
        ...(current || {}),
        status: "running",
        tools: progress.tools.length
          ? mergeChatToolCalls(current?.tools, progress.tools)
          : current?.tools,
        stream_text: progress.streamText || current?.stream_text || "",
        live_events: progress.events.length
          ? mergeLiveExecutionEvents(current?.live_events, progress.events)
          : current?.live_events,
        target: progress.target || current?.target,
        route_profile: progress.routeProfile || current?.route_profile,
        reasoning_profile: progress.routeProfile || current?.reasoning_profile,
      }));
    }
    if (!progress.modelUsage) return;
    const payload = progress.modelUsage;
    const usage = (payload.usage as Record<string, unknown> | undefined)
      || (payload.estimate as Record<string, unknown> | undefined)
      || {};
    const snapshot = (payload.snapshot as Record<string, unknown> | undefined) || {};
    const currentUsage = (snapshot.current as Record<string, unknown> | undefined) || {};
    const peak = (snapshot.peak as Record<string, unknown> | undefined) || {};
    const totals = (snapshot.totals as Record<string, unknown> | undefined) || {};
    const totalTokens = typeof usage.total_tokens === "number"
      ? usage.total_tokens
      : typeof currentUsage.total_tokens === "number"
        ? currentUsage.total_tokens
        : null;
    const kindRaw = String(payload.kind || currentUsage.kind || (payload.estimate ? "estimate" : "unavailable"));
    const kind = (kindRaw as UsageKind) || "unavailable";
    const modelCalls = typeof snapshot.model_calls === "number" ? snapshot.model_calls : null;
    const rawSession = typeof totals.session_tokens === "number" ? totals.session_tokens : null;
    const rawConversation = typeof totals.conversation_tokens === "number" ? totals.conversation_tokens : null;
    const unused = kind === "unavailable" && (modelCalls == null || modelCalls === 0) && totalTokens == null;
    setModelUsage((previous) => ({
      ...previous,
      status: (String(snapshot.status || "generating") as UsageStatus) || "generating",
      modelId: String(payload.model_id || previous.modelId || ""),
      currentTotal: totalTokens,
      currentInput: typeof usage.input_tokens === "number" ? usage.input_tokens : (typeof currentUsage.input_tokens === "number" ? currentUsage.input_tokens : null),
      currentOutput: typeof usage.output_tokens === "number" ? usage.output_tokens : (typeof currentUsage.output_tokens === "number" ? currentUsage.output_tokens : null),
      kind,
      peakTotal: typeof peak.total_tokens === "number" ? peak.total_tokens : previous.peakTotal,
      sessionTotal: unused ? previous.sessionTotal : (rawSession ?? previous.sessionTotal),
      conversationTotal: unused ? previous.conversationTotal : (rawConversation ?? previous.conversationTotal),
      modelCalls: modelCalls ?? previous.modelCalls,
      history: totalTokens == null
        ? previous.history
        : [...previous.history, { at: Date.now(), total: totalTokens }].slice(-60),
    }));
  }, []);

  const chatRun = useChatRun({ onProgress: applyRunProgress });

  const playback = useVoicePlayback({
    language: voiceLanguage === "auto" ? "nl" : voiceLanguage,
    style: voiceSpeakStyle,
    voiceId: voiceTtsVoice || null,
    speed: voiceTtsSpeed,
    volume: voiceVolume,
    outputDeviceId: voiceOutputDeviceId || null,
    allowBrowserFallback: true,
    preferBrowserTts: voiceTtsProvider === "browser",
    onError: (message) => setError(message),
  });

  const dictation = useVoiceDictation({
    language: voiceLanguage === "auto" ? "nl" : voiceLanguage,
    mode: voiceTurnMode === "auto" ? "continuous" : "push_to_talk",
    endSilenceMs: voiceEndSilenceMs,
    speechThreshold: 0.04 - (0.034 * voiceVadSensitivity),
    deviceId: voiceInputDeviceId || null,
    onTranscript: (text, meta) => {
      if (meta.silence || !text) {
        setError("Geen spraak herkend — niets verzonden.");
        return;
      }
      setDraftState((current) => {
        const next = current ? `${current.trim()} ${text}` : text;
        setDraftCursor(next.length);
        return next;
      });
    },
  });

  const voiceSession = useVoiceSession({
    conversationId: selectedId,
    language: voiceLanguage === "auto" ? "nl" : voiceLanguage,
    mode: voiceTurnMode === "auto" ? "continuous" : "push_to_talk",
    endSilenceMs: voiceEndSilenceMs,
    speechThreshold: 0.04 - (0.034 * voiceVadSensitivity),
    bargeIn: voiceBargeIn,
    wakeWordEnabled: voiceWakeWord,
    keepAudio: voiceKeepRecordings,
    inputDeviceId: voiceInputDeviceId || null,
    outputDeviceId: voiceOutputDeviceId || null,
    volume: voiceVolume,
    idleTimeoutSeconds: voiceIdleTimeoutSeconds,
    onUserUtterance: async (text, meta) => {
      await sendRef.current({
        content: text,
        metadata: { source: "voice", voice_session_id: meta.sessionId, voice_turn_id: meta.turnId },
      });
    },
    onError: (message) => setError(message),
  });

  const chatTelemetry = useMemo((): ChatTelemetryExtras => {
    const ctx = contextBudgetTokens(lastExecution?.retrieval);
    const tools = budgetToolRounds(lastExecution?.budget);
    const compiler = (lastExecution?.retrieval?.context_compiler as Record<string, unknown> | undefined) || undefined;
    const budget = (lastExecution?.retrieval?.context_budget as Record<string, unknown> | undefined) || undefined;
    const dropReasons = Array.from(
      new Set(
        [
          ...((Array.isArray(compiler?.drop_reasons) ? compiler?.drop_reasons : []) as unknown[]),
          ...((Array.isArray(budget?.drop_events)
            ? (budget?.drop_events as Array<Record<string, unknown>>).map((row) => row.drop_reason)
            : []) as unknown[]),
        ]
          .map((item) => String(item || "").trim())
          .filter(Boolean),
      ),
    );
    return {
      executionStatus: lastExecution?.status ?? (sending ? "running" : null),
      contextUsed: ctx.used,
      contextMax: ctx.max,
      toolRounds: tools.used,
      maxToolRounds: tools.max,
      wallMs: runWallMs,
      dropReasons: dropReasons.length ? dropReasons : null,
    };
  }, [lastExecution, sending, runWallMs]);

  const selected = useMemo(
    () => conversations.find((item) => item.id === selectedId) ?? null,
    [conversations, selectedId],
  );
  const activeBranch = useMemo(() => branches.find((item) => item.is_active) ?? null, [branches]);
  const compareReady = branches.length >= 2;
  const filteredConversations = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((item) => item.title.toLowerCase().includes(q));
  }, [conversations, searchQuery]);

  const refreshConversations = useCallback(async (preferId?: string) => {
    const items = await hadesApi.conversations();
    setConversations(items);
    setSelectedId((current) => {
      if (preferId && items.some((item) => item.id === preferId)) return preferId;
      if (current && items.some((item) => item.id === current)) return current;
      return items[0]?.id ?? null;
    });
    return items;
  }, []);

  const applyModelForConversation = useCallback((conversation: Conversation | null | undefined, activeDefault: string) => {
    setModelId(resolveConversationModelId(conversation?.model_id, activeDefault));
  }, []);

  const restoreLinkedRuns = useCallback(async (linkedRuns: NonNullable<Awaited<ReturnType<typeof hadesApi.conversationRuns>>["runs"]>) => {
    setLastExecution((prev) => ({
      ...(prev || {}),
      linked_runs: linkedRuns,
      run_id: linkedRuns.find((run) => !["completed", "failed", "cancelled", "rejected", "expired"].includes(String(run.status)))?.run_id
        || prev?.run_id
        || null,
    }));
    const codingLinks = linkedRuns.filter((run) => String(run.run_type) === "coding");
    const researchLinks = linkedRuns.filter((run) => String(run.run_type) === "research");
    const workLinks = linkedRuns.filter((run) => String(run.run_type) === "work");

    if (workLinks.length) {
      setWorkCards(
        workLinks.slice(0, 3).map((link) => ({
          task_id: link.run_id,
          title: link.title || "Work-taak",
          status: String(link.status || "running"),
          current_step: typeof link.metadata?.current_step === "string" ? link.metadata.current_step : null,
          executor: typeof link.metadata?.executor === "string" ? link.metadata.executor : null,
          pending: Boolean(link.metadata?.pending),
          verification: typeof link.metadata?.verification === "string" ? link.metadata.verification : null,
        })),
      );
    } else {
      setWorkCards([]);
    }

    if (codingLinks.length) {
      try {
        const cards = await Promise.all(
          codingLinks.slice(0, 3).map(async (link) => {
            try {
              const snap = await hadesApi.buildJobGet(link.run_id);
              const params = (snap.params || {}) as Record<string, unknown>;
              const result = (snap.result || {}) as Record<string, unknown>;
              return {
                job_id: link.run_id,
                status: String(snap.status || link.status),
                goal: String(params.goal || link.title || ""),
                source_repo: String(params.source_repo || ""),
                phase: String((snap.checkpoint as { phase?: string } | undefined)?.phase || ""),
                files_changed: Array.isArray(result.changed_files)
                  ? result.changed_files.map(String)
                  : Array.isArray(result.files_changed)
                    ? result.files_changed.map(String)
                    : [],
                unified_diff: typeof result.unified_diff === "string" ? result.unified_diff : undefined,
                test_output: typeof result.test_output === "string" ? result.test_output : undefined,
                conflict: typeof result.conflict === "string" ? result.conflict : null,
                verification: typeof result.verification === "string" ? result.verification : null,
                poll: String(link.metadata?.poll || `/build/jobs/${link.run_id}`),
              } satisfies CodingCardJob;
            } catch {
              return {
                job_id: link.run_id,
                status: String(link.status || "unknown"),
                goal: link.title || "Coding-job",
                source_repo: String(link.metadata?.source_repo || ""),
              } satisfies CodingCardJob;
            }
          }),
        );
        if (selectedIdRef.current) setCodingCards(cards);
      } catch {
        // Keep previous cards on restore failure.
      }
    } else {
      setCodingCards([]);
    }

    if (researchLinks.length) {
      try {
        const cards = await Promise.all(
          researchLinks.slice(0, 3).map(async (link) => {
            try {
              const detail = await hadesApi.researchProject(link.run_id);
              const coverage = await hadesApi.researchCoverage(link.run_id).catch(() => null);
              const metrics = detail.project.metrics || {};
              return {
                project_id: link.run_id,
                title: String(detail.project.title || link.title || ""),
                topic: String(detail.project.topic || link.metadata?.topic || ""),
                status: String(detail.project.status || link.status),
                round: typeof metrics.research_rounds === "number" ? metrics.research_rounds : null,
                max_rounds: typeof detail.project.max_rounds === "number"
                  ? detail.project.max_rounds
                  : (typeof metrics.configured_rounds === "number" ? metrics.configured_rounds : null),
                allow_web: Boolean(detail.project.allow_web),
                source_count: detail.sources?.length || metrics.source_count || 0,
                coverage: coverage
                  ? `score ${coverage.coverage_score}${coverage.incomplete ? " · incomplete" : ""}`
                  : null,
                conflicts: Array.isArray(metrics.contradictions) ? metrics.contradictions.map(String) : [],
                events: (detail.events || []).slice(-8).map((event) => ({
                  type: String(event.level || ""),
                  message: String(event.message || ""),
                })),
                citations: (detail.sources || []).slice(0, 8).map((source) => ({
                  title: source.title,
                  uri: source.uri,
                })),
                success: detail.project.status === "completed"
                  ? (detail.sources?.length || metrics.source_count || 0) > 0
                  : null,
              } satisfies ResearchCardState;
            } catch {
              return {
                project_id: link.run_id,
                title: link.title || "Onderzoek",
                topic: String(link.metadata?.topic || ""),
                status: String(link.status || "unknown"),
                source_count: 0,
                success: false,
              } satisfies ResearchCardState;
            }
          }),
        );
        if (selectedIdRef.current) setResearchCards(cards);
      } catch {
        // Keep previous cards on restore failure.
      }
    } else {
      setResearchCards([]);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [conversationItems, modelData, settingsData, healthData, metricsPayload] = await Promise.all([
        hadesApi.conversations(),
        hadesApi.models(),
        hadesApi.settings(),
        hadesApi.health().catch(() => null),
        hadesApi.nativeMetrics().catch(() => null),
      ]);
      let items = conversationItems;
      if (!items.length) items = [await hadesApi.createConversation()];
      setConversations(items);
      const deeplinkId = readHashSelection(["c", "id"]);
      setSelectedId((current) => {
        if (deeplinkId && items.some((item) => item.id === deeplinkId)) return deeplinkId;
        if (current && items.some((item) => item.id === current)) return current;
        return items[0]?.id ?? null;
      });
      setModels(modelData.models);
      setModelConnected(Boolean(modelData.connected));
      const active = modelData.active_profile?.model_id || modelData.models[0]?.id || "";
      setActiveDefaultModelId(active);
      const nextSelected = (deeplinkId && items.some((item) => item.id === deeplinkId))
        ? items.find((item) => item.id === deeplinkId)
        : items.find((item) => item.id === selectedIdRef.current) || items[0];
      applyModelForConversation(nextSelected, active);
      if (active) {
        try {
          setModelProfile(await hadesApi.modelProfile(active));
        } catch {
          setModelProfile(null);
        }
      }
      setStoredReasoningRaw(String(settingsData.values.reasoning_profile || "adaptive"));
      setReasoningMode(normalizeReasoningMode(settingsData.values.reasoning_profile));
      setReasoningReady(true);
      const spoken = Boolean(settingsData.values.spoken_answers_enabled || settingsData.values.voice_spoken_answers_default);
      setSpokenAnswers(spoken);
      spokenAnswersRef.current = spoken;
      setSttProvider(settingsData.values.stt_provider || "paste");
      setTtsProvider(settingsData.values.tts_provider === "voicestudio" ? "voicestudio" : "none");
      setVoiceLanguage(settingsData.values.voice_language || "nl");
      setVoiceEnabled(settingsData.values.voice_enabled !== false);
      setVoiceTurnMode(settingsData.values.voice_turn_mode === "auto" ? "auto" : "manual");
      setVoiceBargeIn(settingsData.values.voice_barge_in !== false);
      setVoiceWakeWord(Boolean(settingsData.values.voice_wake_word_enabled));
      setVoiceEndSilenceMs(Number(settingsData.values.voice_vad_end_silence_ms) || 900);
      setVoiceVadSensitivity(Number(settingsData.values.voice_vad_sensitivity) || 0.55);
      setVoiceInputDeviceId(settingsData.values.voice_input_device_id || "");
      setVoiceOutputDeviceId(settingsData.values.voice_output_device_id || "");
      setVoiceVolume(Number(settingsData.values.voice_tts_volume ?? 1));
      setVoiceKeepRecordings(Boolean(settingsData.values.voice_keep_recordings));
      setVoiceIdleTimeoutSeconds(Number(settingsData.values.voice_session_idle_seconds ?? 120));
      setVoiceSpeakStyle(settingsData.values.voice_speak_style === "full" ? "full" : "compact");
      setVoiceTtsVoice(settingsData.values.voice_tts_voice || "nl_NL-pim-medium");
      setVoiceTtsSpeed(Number(settingsData.values.voice_tts_speed ?? 1));
      setVoiceTtsProvider(settingsData.values.voice_tts_provider === "browser" ? "browser" : "piper");
      setHealth(healthData);
      const metrics = (metricsPayload?.metrics || null) as Record<string, unknown> | null;
      setHostname(typeof metrics?.hostname === "string" ? metrics.hostname : null);
      if (!modelData.connected) {
        setError("LM Studio is niet verbonden. Gesprekken blijven wel lokaal bewaard.");
      } else {
        setError("");
      }
      chatDoctor.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Chat laden is mislukt.");
    }
  }, [applyModelForConversation]);

  useEffect(() => {
    let cancelled = false;
    async function initialize() {
      setLoading(true);
      try {
        await refresh();
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void initialize();
    return () => {
      cancelled = true;
    };
  }, []);

  useHashSelectionSync(
    ["c", "id"],
    (deeplinkId) => {
      setSelectedId((current) => {
        if (current === deeplinkId) return current;
        return conversations.some((item) => item.id === deeplinkId) ? deeplinkId : current;
      });
    },
    conversations.length > 0,
  );

  useEffect(() => hadesSpeechPlayer.subscribe(setSpeechState), []);

  // Usage telemetry poll
  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    const tick = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      try {
        if (runStartedAtRef.current != null) {
          setRunWallMs(Date.now() - runStartedAtRef.current);
        }
        const snap = await hadesApi.chatUsageTelemetry(selectedId || undefined);
        if (cancelled) return;
        setModelUsage((previous) => {
          const mapped = mapUsageTelemetry(snap, previous);
          const liveStream = streamTextRef.current;
          if ((previous.status === "generating" || previous.status === "running" || sendingRef.current) && liveStream) {
            const streamedOut = estimateTokensFromText(liveStream);
            if (streamedOut > (mapped.currentOutput || 0)) {
              const input = mapped.currentInput;
              const total = (input || 0) + streamedOut;
              return {
                ...mapped,
                status: "generating",
                currentOutput: streamedOut,
                currentTotal: total,
                kind: mapped.kind === "exact" ? "exact" : "estimate",
                peakTotal: mapped.peakTotal == null || total > mapped.peakTotal ? total : mapped.peakTotal,
                history: [...mapped.history, { at: Date.now(), total }].slice(-60),
              };
            }
          }
          return mapped;
        });
      } catch {
        // Offline / backend restart — keep last known usage.
      } finally {
        inFlight = false;
      }
    };
    void tick();
    const intervalMs = sending ? CHAT_USAGE_POLL_ACTIVE_MS : CHAT_USAGE_POLL_IDLE_MS;
    const timer = window.setInterval(() => {
      void tick();
    }, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedId, sending]);

  // Approvals poll
  useEffect(() => {
    let cancelled = false;
    async function loadApprovals() {
      try {
        const items = await hadesApi.approvals();
        if (cancelled) return;
        setPendingApprovals(scopePendingApprovals(items as Array<Record<string, unknown>>, selectedId));
      } catch {
        if (!cancelled) setPendingApprovals([]);
      }
    }
    void loadApprovals();
    const timer = window.setInterval(() => {
      void loadApprovals();
    }, CHAT_APPROVALS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedId]);

  // Resolve model + title from selection — never inherit the previous conversation's model.
  useEffect(() => {
    if (!selectedId) {
      setTitleDraft("");
      setModelId(resolveConversationModelId(null, activeDefaultModelId));
      return;
    }
    const conv = conversations.find((item) => item.id === selectedId);
    applyModelForConversation(conv, activeDefaultModelId);
    if (conv) setTitleDraft(conv.title);
    // Do NOT clear or rewrite system_prompt_override on open.
  }, [selectedId, conversations, activeDefaultModelId, applyModelForConversation]);

  // Load conversation transcript, draft (with attachments), pins, linked runs
  useEffect(() => {
    if (!selectedId) {
      setMessages([]);
      setDraftState("");
      setAttachments([]);
      setPinBundle(null);
      setCodingCards([]);
      setResearchCards([]);
      setWorkCards([]);
      return;
    }
    const loadId = selectedId;
    const timer = window.setTimeout(() => {
      setMessagesLoading(true);
      Promise.all([
        hadesApi.messages(loadId),
        hadesApi.getDraft(loadId).catch(() => ({ content: "", attachment_ids: [] as string[] })),
        hadesApi.conversationRuns(loadId).catch(() => ({ conversation_id: loadId, runs: [], count: 0 })),
        hadesApi.getConversationPins(loadId).catch(() => null),
      ])
        .then(async ([msgs, draftData, linked, pins]) => {
          if (selectedIdRef.current !== loadId) return;
          // Do not clobber an in-flight optimistic transcript for this conversation.
          if (!(sendingRef.current && inFlightConversationIdRef.current === loadId)) {
            setMessages(msgs);
          }
          if (pins) {
            setPinBundle({
              accepted: pins.accepted || [],
              skipped: pins.skipped || [],
              summary: pins.summary,
            });
          } else {
            setPinBundle(null);
          }
          const handoff = consumeChatHandoff();
          if (handoff?.draft) {
            setDraftState(handoff.draft);
            setDraftCursor(handoff.draft.length);
          } else if (!(sendingRef.current && inFlightConversationIdRef.current === loadId)) {
            setDraftState(draftData.content || "");
            setDraftCursor((draftData.content || "").length);
          }
          const fromDraft = draftAttachmentsFromIds(draftData.attachment_ids);
          if (!(sendingRef.current && inFlightConversationIdRef.current === loadId)) {
            setAttachments(fromDraft);
          }
          if (handoff?.autoSend && (handoff.draft?.trim() || fromDraft.length)) {
            pendingAutoSendRef.current = true;
          }
          if (linked.runs?.length) {
            await restoreLinkedRuns(linked.runs);
          } else {
            setCodingCards([]);
            setResearchCards([]);
            setWorkCards([]);
          }
          // Clear stream display when viewing a conversation that is not the in-flight one.
          if (inFlightConversationIdRef.current !== loadId) {
            setStreamText("");
          }
        })
        .catch((reason: Error) => {
          if (selectedIdRef.current !== loadId) return;
          setError(reason.message || "Berichten laden is mislukt.");
        })
        .finally(() => {
          if (selectedIdRef.current === loadId) setMessagesLoading(false);
        });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selectedId, restoreLinkedRuns]);

  // Auto-send after handoff
  useEffect(() => {
    if (messagesLoading || !selectedId || !pendingAutoSendRef.current) return;
    if (!draft.trim() && !attachments.length) {
      pendingAutoSendRef.current = false;
      return;
    }
    pendingAutoSendRef.current = false;
    void sendRef.current();
  }, [messagesLoading, selectedId, draft, attachments]);

  // Branches
  useEffect(() => {
    if (!selectedId) {
      setBranches([]);
      setBranchesError(null);
      return;
    }
    setBranchesLoading(true);
    void hadesApi.listConversationBranches(selectedId)
      .then((items) => {
        if (selectedIdRef.current !== selectedId) return;
        setBranches(items);
        setBranchesError(null);
      })
      .catch((reason: Error) => {
        setBranchesError(reason.message || "Branches laden mislukt.");
      })
      .finally(() => setBranchesLoading(false));
  }, [selectedId, messages.length]);

  useEffect(() => {
    if (!compareReady) {
      setCompareLeftId("");
      setCompareRightId("");
      setCompareSides([null, null]);
      return;
    }
    const active = branches.find((item) => item.is_active);
    const fallbackLeft = active?.id ?? branches[0]?.id ?? "";
    const fallbackRight = branches.find((item) => item.id !== fallbackLeft)?.id ?? "";
    setCompareLeftId((current) => (current && branches.some((item) => item.id === current) ? current : fallbackLeft));
    setCompareRightId((current) => (current && branches.some((item) => item.id === current) && current !== fallbackLeft ? current : fallbackRight));
  }, [branches, compareReady]);

  useEffect(() => {
    if (!selectedId || !compareMode || !compareReady || !compareLeftId || !compareRightId || compareLeftId === compareRightId) {
      setCompareSides([null, null]);
      return;
    }
    let cancelled = false;
    setCompareLoading(true);
    const branchTitle = (branchId: string) => branches.find((item) => item.id === branchId)?.title ?? branchId;
    Promise.all([
      hadesApi.messages(selectedId, { branch_id: compareLeftId, active_only: false }),
      hadesApi.messages(selectedId, { branch_id: compareRightId, active_only: false }),
    ])
      .then(([leftMessages, rightMessages]) => {
        if (cancelled) return;
        const leftAssistant = lastAssistantMessage(leftMessages);
        const rightAssistant = lastAssistantMessage(rightMessages);
        setCompareSides([
          {
            branchId: compareLeftId,
            title: branchTitle(compareLeftId),
            text: leftAssistant?.content ?? "",
            empty: !leftAssistant,
          },
          {
            branchId: compareRightId,
            title: branchTitle(compareRightId),
            text: rightAssistant?.content ?? "",
            empty: !rightAssistant,
          },
        ]);
      })
      .catch(() => {
        if (!cancelled) setCompareSides([null, null]);
      })
      .finally(() => {
        if (!cancelled) setCompareLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, compareMode, compareReady, compareLeftId, compareRightId, branches]);

  // Canvas / scratchpad
  useEffect(() => {
    if (!selectedId) {
      setCanvasContent("");
      setCanvasArtifactId(null);
      setCanvasDirty(false);
      return;
    }
    let cancelled = false;
    setCanvasLoading(true);
    void hadesApi.artifacts({ conversation_id: selectedId })
      .then(async (items) => {
        const artifact = pickCanvasArtifact(items);
        if (!artifact) {
          if (!cancelled) {
            setCanvasContent("");
            setCanvasArtifactId(null);
            setCanvasDirty(false);
            setCanvasError(null);
          }
          return;
        }
        const preview = await hadesApi.artifactPreview(artifact.id);
        if (cancelled) return;
        setCanvasContent(preview.text ?? "");
        setCanvasArtifactId(artifact.id);
        setCanvasDirty(false);
        setCanvasError(null);
      })
      .catch((reason: Error) => {
        if (!cancelled) {
          setCanvasError(reason.message || "Canvas laden mislukt.");
        }
      })
      .finally(() => {
        if (!cancelled) setCanvasLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  // Persist draft with attachment ids (never wipe attachments on text-only edits)
  useEffect(() => {
    if (!selectedId) return;
    if (draftTimer.current) window.clearTimeout(draftTimer.current);
    draftTimer.current = window.setTimeout(() => {
      void hadesApi.saveDraft(selectedId, draft, attachmentIdsFromPending(attachments)).catch(() => undefined);
    }, 400);
    return () => {
      if (draftTimer.current) window.clearTimeout(draftTimer.current);
    };
  }, [draft, attachments, selectedId]);

  const selectConversation = useCallback((id: string) => {
    // Allow switch during send — stream isolation handles in-flight updates.
    setSelectedId(id);
    setError("");
    if (inFlightConversationIdRef.current !== id) {
      setStreamText("");
    }
  }, []);

  const ensureConversation = useCallback(async () => {
    if (selectedIdRef.current) return selectedIdRef.current;
    const item = await hadesApi.createConversation("Nieuw gesprek", modelId || activeDefaultModelId || undefined);
    setConversations((items) => [item, ...items.filter((row) => row.id !== item.id)]);
    setSelectedId(item.id);
    return item.id;
  }, [modelId, activeDefaultModelId]);

  const createConversation = useCallback(async () => {
    try {
      const item = await hadesApi.createConversation("Nieuw gesprek", modelId || activeDefaultModelId || undefined);
      await refreshConversations(item.id);
      setMessages([]);
      setDraftState("");
      setDraftCursor(0);
      setAttachments([]);
      setStreamText("");
      setLastExecution(null);
      setCodingCards([]);
      setResearchCards([]);
      setWorkCards([]);
      setError("");
      applyModelForConversation(item, activeDefaultModelId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Nieuw gesprek maken is mislukt.");
    }
  }, [modelId, activeDefaultModelId, refreshConversations, applyModelForConversation]);

  const deleteConversation = useCallback(async () => {
    if (!selectedId) return;
    try {
      await hadesApi.forgetMemoryScope({ conversation_id: selectedId, include_derived: true, preview_only: true });
      await hadesApi.forgetMemoryScope({ conversation_id: selectedId, include_derived: true, preview_only: false });
      const items = await refreshConversations();
      const next = items[0] ?? null;
      setSelectedId(next?.id ?? null);
      setMessages([]);
      setAttachments([]);
      setDraftState("");
      applyModelForConversation(next, activeDefaultModelId);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Verwijderen is mislukt.");
    }
  }, [selectedId, refreshConversations, applyModelForConversation, activeDefaultModelId]);

  const changeModel = useCallback(async (next: string) => {
    const previous = modelId;
    const previousProfile = modelProfile;
    setModelId(next);
    try {
      const profile = await hadesApi.modelProfile(next);
      setModelProfile(profile);
      if (selectedId) {
        const updated = await hadesApi.updateConversation(selectedId, { model_id: next });
        setConversations((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      }
    } catch (reason) {
      setModelId(previous);
      setModelProfile(previousProfile);
      if (selectedId) {
        try {
          const items = await hadesApi.conversations();
          setConversations(items);
          const conv = items.find((item) => item.id === selectedId);
          applyModelForConversation(conv, activeDefaultModelId);
        } catch {
          // Keep rolled-back local model id.
        }
      }
      setError(reason instanceof Error ? reason.message : "Model wijzigen is mislukt.");
    }
  }, [modelId, modelProfile, selectedId, activeDefaultModelId, applyModelForConversation]);

  const changeReasoningMode = useCallback(async (next: ProductReasoningMode) => {
    if (!reasoningReady || reasoningSaving || next === reasoningMode) return;
    const previous = reasoningMode;
    const previousRaw = storedReasoningRaw;
    setReasoningMode(next);
    setStoredReasoningRaw(next);
    setReasoningSaving(true);
    try {
      const latest = await hadesApi.settings();
      const saved = await hadesApi.saveSettings({ ...latest.values, reasoning_profile: next });
      setStoredReasoningRaw(String(saved.values.reasoning_profile || next));
      setReasoningMode(normalizeReasoningMode(saved.values.reasoning_profile));
    } catch (reason) {
      setReasoningMode(previous);
      setStoredReasoningRaw(previousRaw);
      setError(reason instanceof Error ? reason.message : "Denkmodus wijzigen is mislukt.");
    } finally {
      setReasoningSaving(false);
    }
  }, [reasoningReady, reasoningSaving, reasoningMode, storedReasoningRaw]);

  const renameConversation = useCallback(async (title?: string) => {
    if (!selectedId) return;
    const nextTitle = (title ?? titleDraft).trim() || "Nieuw gesprek";
    try {
      // Title only — never send update_system_prompt / clear overrides.
      const updated = await hadesApi.updateConversation(selectedId, { title: nextTitle });
      setConversations((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      setTitleDraft(updated.title);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Titel opslaan is mislukt.");
    }
  }, [selectedId, titleDraft]);

  const saveSystemPromptOverride = useCallback(async (override: string | null) => {
    if (!selectedId) return;
    try {
      const updated = await hadesApi.updateConversation(selectedId, {
        system_prompt_override: override,
        update_system_prompt: true,
      });
      setConversations((items) => items.map((item) => (item.id === updated.id ? updated : item)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "System prompt opslaan is mislukt.");
    }
  }, [selectedId]);

  const exportConversationMarkdown = useCallback(async () => {
    if (!selectedId) return;
    try {
      const result = await hadesApi.exportConversation(selectedId);
      const blob = new Blob([result.markdown], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      const title = conversations.find((item) => item.id === selectedId)?.title || "conversation";
      anchor.download = `${title.replace(/[^\w\-]+/g, "_").slice(0, 60)}.md`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Export mislukt.");
    }
  }, [selectedId, conversations]);

  const addFiles = useCallback(async (files: File[]) => {
    if (!files.length) return;
    const validation = validateAttachmentBatch(
      attachments.length,
      files.map((file) => ({ name: file.name, size: file.size })),
    );
    if (!validation.ok) {
      setError(validation.error);
      return;
    }
    try {
      const conversationId = await ensureConversation();
      for (const file of files) {
        try {
          const uploaded = await hadesApi.uploadChatAttachment(conversationId, file);
          setAttachments((current) => [...current, {
            artifact_id: uploaded.artifact.id,
            filename: uploaded.filename,
            status: uploaded.extract_status || "ready",
          }]);
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : `Upload van ${file.name} mislukt.`);
        }
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bijlagen uploaden mislukt.");
    }
  }, [attachments.length, ensureConversation]);

  const removeAttachment = useCallback((artifactId: string) => {
    setAttachments((current) => current.filter((item) => item.artifact_id !== artifactId));
  }, []);

  const reuseArtifact = useCallback((artifact: HadesArtifact) => {
    setAttachments((current) => {
      if (current.some((item) => item.artifact_id === artifact.id)) return current;
      return [...current, { artifact_id: artifact.id, filename: artifact.name, status: "ready" }];
    });
  }, []);

  const persistPins = useCallback(async (paths: string[]) => {
    if (!selectedId) return;
    setPinsBusy(true);
    try {
      const result = await hadesApi.putConversationPins(selectedId, { paths, force: true });
      setPinBundle({
        accepted: result.accepted || [],
        skipped: result.skipped || [],
        summary: result.summary,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Pins opslaan mislukt.");
    } finally {
      setPinsBusy(false);
    }
  }, [selectedId]);

  const addPinPath = useCallback(async (path: string) => {
    const existing = (pinBundle?.accepted || []).map((item) => String(item.path || "")).filter(Boolean);
    const next = Array.from(new Set([...existing, path]));
    await persistPins(next);
  }, [pinBundle, persistPins]);

  const removePinPath = useCallback(async (path: string) => {
    const next = (pinBundle?.accepted || [])
      .map((item) => String(item.path || ""))
      .filter((item) => item && item !== path);
    await persistPins(next);
  }, [pinBundle, persistPins]);

  const pickPinFolder = useCallback(async () => {
    if (!selectedId) return;
    setPinsBusy(true);
    try {
      const picked = await hadesApi.pickConversationPinFolder(selectedId);
      if (picked.cancelled || !picked.path) return;
      await addPinPath(picked.path);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Mapkiezer niet beschikbaar — plak een pad.");
    } finally {
      setPinsBusy(false);
    }
  }, [selectedId, addPinPath]);

  const decideApprovalAction = useCallback(async (id: string, approve: boolean, note = "") => {
    setApprovalBusy(id);
    try {
      await hadesApi.decideApproval(id, approve, note);
      const items = await hadesApi.approvals();
      setPendingApprovals(scopePendingApprovals(items as Array<Record<string, unknown>>, selectedIdRef.current));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Goedkeuring verwerken mislukt.");
    } finally {
      setApprovalBusy(null);
    }
  }, []);

  const refreshCodingJob = useCallback(async (jobId: string) => {
    try {
      const snap = await hadesApi.buildJobGet(jobId);
      const params = (snap.params || {}) as Record<string, unknown>;
      const result = (snap.result || {}) as Record<string, unknown>;
      setCodingCards((current) => current.map((item) => (
        item.job_id === jobId
          ? {
              ...item,
              status: String(snap.status || item.status),
              goal: String(params.goal || item.goal || ""),
              source_repo: String(params.source_repo || item.source_repo || ""),
              phase: String((snap.checkpoint as { phase?: string } | undefined)?.phase || item.phase || ""),
              files_changed: Array.isArray(result.changed_files)
                ? result.changed_files.map(String)
                : Array.isArray(result.files_changed)
                  ? result.files_changed.map(String)
                  : item.files_changed,
              unified_diff: typeof result.unified_diff === "string" ? result.unified_diff : item.unified_diff,
              test_output: typeof result.test_output === "string" ? result.test_output : item.test_output,
            }
          : item
      )));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Coding-job vernieuwen mislukt.");
    }
  }, []);

  const applyCodingJob = useCallback(async (jobId: string) => {
    setCodingBusy(true);
    try {
      await hadesApi.buildApply(jobId, true);
      await refreshCodingJob(jobId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Apply mislukt.");
    } finally {
      setCodingBusy(false);
    }
  }, [refreshCodingJob]);

  const rejectCodingJob = useCallback(async (jobId: string) => {
    setCodingBusy(true);
    try {
      await hadesApi.buildJobCancel(jobId);
      setCodingCards((current) => current.map((item) => (
        item.job_id === jobId ? { ...item, status: "cancelled" } : item
      )));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Coding-job annuleren mislukt.");
    } finally {
      setCodingBusy(false);
    }
  }, []);

  const refreshResearch = useCallback(async (projectId: string) => {
    try {
      const detail = await hadesApi.researchProject(projectId);
      const coverage = await hadesApi.researchCoverage(projectId).catch(() => null);
      setResearchCards((current) => current.map((row) => (
        row.project_id === projectId
          ? {
              ...row,
              status: String(detail.project.status || row.status),
              source_count: detail.sources?.length || 0,
              coverage: coverage ? String((coverage as { coverage?: string }).coverage || row.coverage || "") : row.coverage,
              events: (detail.events || []).slice(-8).map((event) => ({
                type: String(event.level || ""),
                message: String(event.message || ""),
              })),
              citations: (detail.sources || []).slice(0, 8).map((source) => ({
                title: source.title,
                uri: source.uri,
              })),
              success: detail.project.status === "completed" ? (detail.sources?.length || 0) > 0 : null,
            }
          : row
      )));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Onderzoek vernieuwen mislukt.");
    }
  }, []);

  const stopResearch = useCallback(async (projectId: string) => {
    setResearchBusy(true);
    try {
      const project = await hadesApi.cancelResearch(projectId);
      setResearchCards((current) => current.map((row) => (
        row.project_id === projectId ? { ...row, status: String(project.status || "cancelled") } : row
      )));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Onderzoek stoppen mislukt.");
    } finally {
      setResearchBusy(false);
    }
  }, []);

  const goDeeperResearch = useCallback(async (projectId: string) => {
    setResearchBusy(true);
    try {
      const project = await hadesApi.runResearch(projectId);
      setResearchCards((current) => current.map((row) => (
        row.project_id === projectId ? { ...row, status: String(project.status || row.status) } : row
      )));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Diepere onderzoeksronde starten mislukt.");
    } finally {
      setResearchBusy(false);
    }
  }, []);

  const loadRunEvents = useCallback(async (runId: string) => {
    try {
      const payload = await hadesApi.runEvents(runId);
      setLastExecution((prev) => (prev
        ? {
          ...prev,
          live_events: mergeLiveExecutionEvents(
            [],
            (payload.events || []) as ChatExecutionState["live_events"],
          ),
        }
        : prev));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run-events laden mislukt.");
    }
  }, []);

  const cancelGeneration = useCallback(async () => {
    const runId = inFlightRequestIdRef.current;
    if (runId) cancelledRequestIdsRef.current.add(runId);
    if (runStartedAtRef.current != null) {
      setRunWallMs(Date.now() - runStartedAtRef.current);
      runStartedAtRef.current = null;
    }
    setSending(false);
    voiceSession.setModelGenerating(false);
    setModelUsage((current) => ({ ...current, status: "cancelled" }));
    setLastExecution((current) => (current ? { ...current, status: "cancelled" } : current));
    setStreamText("");
    await chatRun.cancelRun(runId || undefined);

    const targets = collectUnifiedStopTargets({
      linkedRuns: lastExecutionRef.current?.linked_runs,
      codingJobIds: codingCardsRef.current.map((item) => item.job_id),
      researchProjectIds: researchCardsRef.current.map((item) => item.project_id),
      codingStatuses: Object.fromEntries(codingCardsRef.current.map((item) => [item.job_id, item.status])),
      researchStatuses: Object.fromEntries(researchCardsRef.current.map((item) => [item.project_id, item.status])),
    });
    await Promise.all(targets.map((target) => {
      if (target.engine === "coding") return hadesApi.buildJobCancel(target.run_id).catch(() => undefined);
      if (target.engine === "research") return hadesApi.cancelResearch(target.run_id).catch(() => undefined);
      return hadesApi.cancelTask(target.run_id).catch(() => undefined);
    }));
    setCodingCards((current) => markCardsCancelled(current));
    setResearchCards((current) => markCardsCancelled(current));
    setWorkCards((current) => markCardsCancelled(current));
  }, [chatRun, voiceSession]);

  const sendMessage = useCallback(async (options?: SendMessageOptions) => {
    const content = (options?.content ?? draft).trim();
    if ((!content && !attachments.length) || sendingRef.current) return;
    const requestId = newChatRequestId();
    inFlightRequestIdRef.current = requestId;
    let conversationId = selectedIdRef.current;
    const fromVoice = Boolean(options?.metadata?.source === "voice" || options?.metadata?.voice);

    // Barge-in: stop leftover TTS before a new user turn.
    await hadesSpeechPlayer.stop().catch(() => undefined);
    playback.stop();

    try {
      conversationId = await ensureConversation();
      inFlightConversationIdRef.current = conversationId;
      const optimistic: ChatMessage = {
        id: `local-${Date.now()}`,
        conversation_id: conversationId,
        role: "user",
        content: content || "(bijlagen)",
        created_at: new Date().toISOString(),
        metadata: options?.metadata,
      };
      if (selectedIdRef.current === conversationId) {
        setMessages((current) => [...current, optimistic]);
      }
      setDraftState("");
      setDraftCursor(0);
      const attachmentIds = attachmentIdsFromPending(attachments);
      setAttachments([]);
      setSending(true);
      if (fromVoice || voiceSession.state.sessionId) voiceSession.setModelGenerating(true);
      setError("");
      runStartedAtRef.current = Date.now();
      setRunWallMs(0);
      if (selectedIdRef.current === conversationId) {
        setModelUsage((current) => ({ ...current, status: "running", modelId: modelId || current.modelId }));
        setLastExecution({ status: "running", tools: [], live_events: [], stream_text: "" });
        setStreamText("");
      }
      chatRun.start(requestId);
      try {
        const result = await hadesApi.sendMessage(conversationId, content || "Bekijk de bijlagen.", modelId || undefined, {
          client_request_id: requestId,
          attachment_ids: attachmentIds,
          revise_message_id: options?.revise_message_id,
          regenerate_of: options?.regenerate_of,
          metadata: options?.metadata,
          reasoning_profile: reasoningProfileForRequest(storedReasoningRaw, reasoningMode),
        });
        if (inFlightRequestIdRef.current !== requestId) return;
        const execStatus = String(
          result.execution_status
          || (result.assistant_message?.metadata as Record<string, unknown> | undefined)?.execution_status
          || "",
        ).toLowerCase();
        if (shouldIgnoreCancelledCompletion(requestId, cancelledRequestIdsRef.current, execStatus)) {
          cancelledRequestIdsRef.current.delete(requestId);
          if (selectedIdRef.current === conversationId) {
            setLastExecution((current) => (current ? { ...current, status: "cancelled" } : current));
            setModelUsage((prev) => ({ ...prev, status: "cancelled" }));
            try {
              setMessages(await hadesApi.messages(conversationId));
            } catch {
              // Keep local transcript if reload fails.
            }
          }
          return;
        }
        cancelledRequestIdsRef.current.delete(requestId);
        const execution = mapSendResultToExecution(result as unknown as Record<string, unknown>, requestId);
        if (selectedIdRef.current === conversationId) {
          setMessages((current) => [
            ...current.filter((item) => item.id !== optimistic.id),
            result.user_message,
            result.assistant_message,
          ]);
          setAttachmentReport(result.attachments || []);
          setStreamText("");
          setLastExecution(execution);
          if (execStatus === "failed" || execStatus === "blocked") {
            setModelUsage((prev) => ({ ...prev, status: "failed" }));
          } else if (execStatus === "degraded") {
            setModelUsage((prev) => ({ ...prev, status: "degraded" }));
          } else if (execStatus === "cancelled") {
            setModelUsage((prev) => ({ ...prev, status: "cancelled" }));
          } else if (result.usage) {
            const total = typeof result.usage.total_tokens === "number" ? result.usage.total_tokens : null;
            setModelUsage((prev) => {
              const peak = total != null && (prev.peakTotal == null || total > prev.peakTotal) ? total : prev.peakTotal;
              return {
                ...prev,
                status: "idle",
                modelId: String(result.usage?.model_id || result.model_id || prev.modelId),
                currentTotal: total,
                currentInput: typeof result.usage?.input_tokens === "number" ? result.usage.input_tokens : null,
                currentOutput: typeof result.usage?.output_tokens === "number" ? result.usage.output_tokens : null,
                kind: total != null ? "exact" : "unavailable",
                peakTotal: peak,
                sessionTotal: total != null ? (prev.sessionTotal ?? 0) + total : prev.sessionTotal,
                conversationTotal: total != null ? (prev.conversationTotal ?? 0) + total : prev.conversationTotal,
                modelCalls: total != null ? (prev.modelCalls ?? 0) + 1 : prev.modelCalls,
                history: total == null ? prev.history : [...prev.history, { at: Date.now(), total }].slice(-60),
              };
            });
          } else {
            setModelUsage((prev) => ({ ...prev, status: "idle", kind: prev.kind === "exact" ? "exact" : "unavailable" }));
          }
          if (execution.linked_runs?.length) {
            void restoreLinkedRuns(execution.linked_runs);
          }
          try {
            setBranches(await hadesApi.listConversationBranches(conversationId));
            setBranchesError(null);
          } catch (branchReason) {
            setBranchesError(branchReason instanceof Error ? branchReason.message : "Branches laden mislukt.");
          }
        }
        if (result.model_id && selectedIdRef.current === conversationId) {
          setModelId(result.model_id);
        }
        await refreshConversations(conversationId);
        const inVoiceSession = Boolean(voiceSession.state.sessionId);
        if (result.assistant_message?.content && (spokenAnswersRef.current || inVoiceSession)) {
          setLastSpokenAnswer(result.assistant_message.content);
          if (inVoiceSession) {
            await voiceSession.speakAssistantResponse(result.assistant_message.content, result.assistant_message.id);
          } else if (ttsProvider === "voicestudio") {
            void hadesSpeechPlayer.speakText(result.assistant_message.content, result.assistant_message.id).catch((speakReason) => {
              setError(speakReason instanceof Error ? speakReason.message : "Voorlezen mislukt. Tekstchat blijft beschikbaar.");
            });
          } else {
            await playback.speak(result.assistant_message.content, { messageId: result.assistant_message.id });
          }
        }
      } finally {
        chatRun.stop();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Het bericht kon niet worden verstuurd.");
      if (conversationId && selectedIdRef.current === conversationId) {
        try {
          setMessages(await hadesApi.messages(conversationId));
        } catch {
          // Keep existing transcript.
        }
      }
    } finally {
      if (inFlightRequestIdRef.current === requestId) {
        if (runStartedAtRef.current != null) {
          setRunWallMs(Date.now() - runStartedAtRef.current);
          runStartedAtRef.current = null;
        }
        setSending(false);
        voiceSession.setModelGenerating(false);
        inFlightRequestIdRef.current = null;
        inFlightConversationIdRef.current = null;
      }
    }
  }, [
    draft,
    attachments,
    modelId,
    storedReasoningRaw,
    reasoningMode,
    ensureConversation,
    chatRun,
    refreshConversations,
    restoreLinkedRuns,
    playback,
    voiceSession,
    ttsProvider,
  ]);

  sendRef.current = sendMessage;

  const reviseMessage = useCallback(async (userMessage: ChatMessage) => {
    await sendMessage({ revise_message_id: userMessage.id, content: userMessage.content });
  }, [sendMessage]);

  const regenerateMessage = useCallback(async (assistantMessage: ChatMessage) => {
    const index = messages.findIndex((item) => item.id === assistantMessage.id);
    const prior = index > 0 ? messages[index - 1] : null;
    if (prior?.role === "user") {
      await sendMessage({
        regenerate_of: assistantMessage.id,
        content: prior.content,
        revise_message_id: prior.id,
      });
    }
  }, [messages, sendMessage]);

  const branchFromMessage = useCallback(async (message: ChatMessage) => {
    if (!selectedId) return;
    try {
      await hadesApi.branchConversation(selectedId, message.id);
      setDraftState("");
      setDraftCursor(0);
      const [branchItems, msgs] = await Promise.all([
        hadesApi.listConversationBranches(selectedId),
        hadesApi.messages(selectedId),
      ]);
      setBranches(branchItems);
      setMessages(msgs);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Vertakken mislukt.");
    }
  }, [selectedId]);

  const activateBranch = useCallback(async (branchId: string) => {
    if (!selectedId || branchActivatingId) return;
    const target = branches.find((item) => item.id === branchId);
    if (!target || target.is_active) return;
    setBranchActivatingId(branchId);
    try {
      await hadesApi.activateConversationBranch(selectedId, branchId);
      const [branchItems, msgs] = await Promise.all([
        hadesApi.listConversationBranches(selectedId),
        hadesApi.messages(selectedId),
      ]);
      setBranches(branchItems);
      setMessages(msgs);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Vertakking activeren mislukt.");
    } finally {
      setBranchActivatingId("");
    }
  }, [selectedId, branchActivatingId, branches]);

  const openInCanvas = useCallback((content: string) => {
    setCanvasContent(content);
    setCanvasDirty(true);
    setCanvasOpen(true);
  }, []);

  const saveCanvas = useCallback(async () => {
    if (!selectedId || canvasSaving) return;
    setCanvasSaving(true);
    try {
      const artifact = await hadesApi.generateArtifact({
        name: "canvas.md",
        content: canvasContent,
        mime_type: "text/markdown",
        kind: "generated",
        conversation_id: selectedId,
      });
      setCanvasArtifactId(artifact.id);
      setCanvasDirty(false);
      setCanvasError(null);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Canvas opslaan mislukt.";
      setCanvasError(message);
      setError(message);
    } finally {
      setCanvasSaving(false);
    }
  }, [selectedId, canvasSaving, canvasContent]);

  const toggleSpokenAnswers = useCallback(async (checked: boolean) => {
    const previous = spokenAnswers;
    setSpokenAnswers(checked);
    spokenAnswersRef.current = checked;
    try {
      const latest = await hadesApi.settings();
      await hadesApi.saveSettings({
        ...latest.values,
        spoken_answers_enabled: checked,
        voice_spoken_answers_default: checked,
      });
    } catch (reason) {
      setSpokenAnswers(previous);
      spokenAnswersRef.current = previous;
      setError(reason instanceof Error ? reason.message : "Gesproken antwoorden opslaan mislukt.");
    }
  }, [spokenAnswers]);

  const speakMessage = useCallback(async (message: ChatMessage) => {
    try {
      setLastSpokenAnswer(message.content);
      if (voiceSession.state.sessionId) {
        await voiceSession.speakAssistantResponse(message.content, message.id, { forceReplay: true });
      } else if (ttsProvider === "voicestudio") {
        await hadesSpeechPlayer.speakText(message.content, message.id);
      } else {
        await playback.speak(message.content, { messageId: message.id });
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Voorlezen mislukt.");
    }
  }, [voiceSession, ttsProvider, playback]);

  const toggleMic = useCallback(async () => {
    if (micRecording) {
      mediaRecorderRef.current?.stop();
      setMicRecording(false);
      return;
    }
    if (sttProvider !== "voicestudio") {
      setError("STT staat op plakken. Zet Instellingen → Spraak → STT-provider op VoiceStudio voor microfoon, of gebruik Dictatie (ingebouwd).");
      return;
    }
    try {
      await hadesSpeechPlayer.ensureMicAllowed();
      await hadesSpeechPlayer.stop();
      playback.stop();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      micChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) micChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(micChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        void hadesApi.speechTranscribe(blob, "mic.webm").then((result) => {
          const text = String(result.text || "").trim();
          if (text) {
            setDraftState((current) => {
              const next = current ? `${current.trim()} ${text}` : text;
              setDraftCursor(next.length);
              return next;
            });
          } else {
            setError("Geen transcript ontvangen.");
          }
        }).catch((reason) => {
          setError(reason instanceof Error ? reason.message : "Transcriptie mislukt.");
        });
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setMicRecording(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Microfoon starten mislukt.");
      setMicRecording(false);
    }
  }, [micRecording, sttProvider, playback]);

  const copyMessage = useCallback(async (message: ChatMessage) => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedId(message.id);
      window.setTimeout(() => setCopiedId(""), 1_500);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Kopiëren mislukt.");
    }
  }, []);

  return {
    conversations,
    filteredConversations,
    selectedId,
    selected,
    messages,
    models,
    modelId,
    modelConnected,
    activeDefaultModelId,
    modelProfile,
    draft,
    draftCursor,
    attachments,
    attachmentReport,
    searchQuery,
    loading,
    messagesLoading,
    sending,
    streamText,
    error,
    health: health || chatDoctor.health,
    hostname,
    titleDraft,
    reasoningMode,
    reasoningLabel: reasoningModeLabel(reasoningMode),
    reasoningReady,
    reasoningSaving,
    storedReasoningRaw,
    lastExecution,
    codingCards,
    codingBusy,
    researchCards,
    researchBusy,
    workCards,
    pendingApprovals,
    approvalBusy,
    pinBundle,
    pinsBusy,
    branches,
    branchesLoading,
    branchesError,
    branchActivatingId,
    activeBranch,
    compareMode,
    compareReady,
    compareLeftId,
    compareRightId,
    compareLoading,
    compareSides,
    canvasOpen,
    canvasContent,
    canvasArtifactId,
    canvasDirty,
    canvasLoading,
    canvasError,
    canvasSaving,
    modelUsage,
    runWallMs,
    chatTelemetry,
    spokenAnswers,
    speechState,
    micRecording,
    sttProvider,
    ttsProvider,
    voiceLanguage,
    voiceEnabled,
    voiceTurnMode,
    voiceBargeIn,
    voiceWakeWord,
    lastSpokenAnswer,
    dictation,
    playback,
    voiceSession,
    chatDoctor,
    setDraft,
    setDraftCursor,
    setSearchQuery,
    setTitleDraft,
    setError,
    setCanvasOpen,
    setCanvasContent: (value: string) => {
      setCanvasContent(value);
      setCanvasDirty(true);
    },
    setCompareMode,
    setCompareLeftId,
    setCompareRightId,
    selectConversation,
    createConversation,
    deleteConversation,
    refresh,
    refreshConversations,
    sendMessage,
    cancelGeneration,
    regenerateMessage,
    reviseMessage,
    changeModel,
    changeReasoningMode,
    renameConversation,
    saveSystemPromptOverride,
    exportConversation: exportConversationMarkdown,
    addFiles,
    removeAttachment,
    reuseArtifact,
    persistPins,
    addPinPath,
    removePinPath,
    pickPinFolder,
    decideApproval: decideApprovalAction,
    applyCodingJob,
    rejectCodingJob,
    refreshCodingJob,
    stopResearch,
    goDeeperResearch,
    refreshResearch,
    loadRunEvents,
    branchFromMessage,
    activateBranch,
    openInCanvas,
    saveCanvas,
    toggleSpokenAnswers,
    speakMessage,
    toggleMic,
    copyMessage,
    copiedId,
  };
}
