"use client";

import { KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BrainCircuit, Check, ChevronDown, ChevronUp, Columns2, Download, GitBranch, Loader2, Plus, RefreshCcw, Save, ServerOff, Square, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { ModelUsageCard, EMPTY_MODEL_USAGE, type ChatTelemetryExtras, type ModelUsageState, type UsageKind, type UsageStatus } from "@/components/hades/model-usage-card";
import { ResultsPanel } from "@/components/hades/results-panel";
import { MentionAutocompleteList, useMentionAutocomplete, type MentionSuggestion } from "@/components/hades/chat-mention-autocomplete";
import { ChatProvenanceList } from "@/components/hades/chat-provenance";
import { ExecutionCompletionBanner } from "@/components/hades/execution-completion-banner";
import { ToolResultCards } from "@/components/hades/tool-result-cards";
import { VoiceComposerControls } from "@/components/hades/voice/voice-composer-controls";
import { VoiceMessageActions } from "@/components/hades/voice/voice-message-actions";
import { VoicePanel } from "@/components/hades/voice/voice-panel";
import { VoiceSetupWizard } from "@/components/hades/voice/voice-setup-wizard";
import { ChatComposer } from "@/components/hades/features/chat/ChatComposer";
import { ChatDoctorBanner, useChatDoctor } from "@/components/hades/features/chat/ChatDoctorBanner";
import { ChatPinsBar, type PinBundle } from "@/components/hades/features/chat/ChatPinsBar";
import { ContextTurnPanel } from "@/components/hades/features/chat/ContextTurnPanel";
import { CodingCard, type CodingCardJob } from "@/components/hades/features/chat/CodingCard";
import { ApprovalCard, WorkCard, type WorkCardState } from "@/components/hades/features/chat/ApprovalWorkCards";
import { ResearchCard, type ResearchCardState } from "@/components/hades/features/chat/ResearchCard";
import { ChatTimeline } from "@/components/hades/features/chat/ChatTimeline";
import { ExecutionTrace } from "@/components/hades/features/chat/ExecutionTrace";
import { VerificationSummary } from "@/components/hades/features/chat/VerificationSummary";
import { useChatRun, type ChatRunProgress } from "@/components/hades/features/chat/hooks/useChatRun";
import type { ChatExecutionState, HighLevelExecutionEvent, PendingAttachment } from "@/components/hades/features/chat/types";
import {
  mergeChatToolCalls,
  mergeLiveExecutionEvents,
} from "@/components/hades/features/chat/live-execution-merge";
import { useVoiceDictation } from "@/hooks/use-voice-dictation";
import { useVoicePlayback } from "@/hooks/use-voice-playback";
import { useVoiceSession } from "@/hooks/use-voice-session";
import { assessChatCompletion, selfCorrectionNotes } from "@/lib/execution-completion";
import { ChatMessage, Conversation, ConversationBranch, HadesArtifact, hadesApi, LmModel, ModelProfile, formatDate } from "@/lib/hades-api";
import { REASONING_MODE_OPTIONS, normalizeReasoningMode, reasoningProfileForRequest, type ProductReasoningMode } from "@/lib/reasoning-mode";
import { hadesSpeechPlayer, type SpeechPlayerState } from "@/lib/hades-speech";
import { readHashSelection } from "@/lib/hash-query";
import { chatChrome } from "@/lib/chat-i18n";
import { CHAT_APPROVALS_POLL_MS, CHAT_USAGE_POLL_ACTIVE_MS, CHAT_USAGE_POLL_IDLE_MS } from "@/lib/ui-poll-intervals";
import { useHashSelectionSync } from "@/hooks/use-hash-selection";
import { consumeChatHandoff } from "@/lib/chat-handoff";
import { resolveConversationModelId } from "@/components/hades/features/chat/chat-runtime-core";
const CANVAS_NAMES = ["canvas.md", "scratchpad.md"];

type BranchCompareSide = { branchId: string; title: string; text: string; empty: boolean };

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function estimateTokensFromText(text: string): number {
  const length = text.trim().length;
  return length ? Math.max(1, Math.ceil(length / 4)) : 0;
}

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
  // Backend session_tokens defaults to 0 — treat unused/unavailable as missing for the strip.
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

function contextBudgetTokens(retrieval: Record<string, unknown> | undefined): { used: number | null; max: number | null } {
  const budget = (retrieval?.context_budget as Record<string, unknown> | undefined) || undefined;
  if (!budget) return { used: null, max: null };
  const usedChars = typeof budget.used_chars === "number" ? budget.used_chars : null;
  const maxChars = typeof budget.max_chars === "number" ? budget.max_chars : null;
  // Context budget is char-based; show approx tokens (chars/4) when known — never invent zeros.
  return {
    used: usedChars == null ? null : Math.max(0, Math.ceil(usedChars / 4)),
    max: maxChars == null ? null : Math.max(0, Math.ceil(maxChars / 4)),
  };
}

function budgetToolRounds(budget: Record<string, unknown> | undefined): { used: number | null; max: number | null } {
  if (!budget) return { used: null, max: null };
  return {
    used: typeof budget.tool_rounds === "number" ? budget.tool_rounds : null,
    max: typeof budget.max_tool_rounds === "number" ? budget.max_tool_rounds : null,
  };
}

function lastAssistantMessage(messages: ChatMessage[]): ChatMessage | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") return messages[index];
  }
  return null;
}

function pickCanvasArtifact(items: HadesArtifact[]): HadesArtifact | null {
  const readyText = items.filter((item) => item.status === "ready" && (
    item.mime_type.startsWith("text/") || item.name.endsWith(".md") || item.name.endsWith(".txt")
  ));
  const preferred = readyText.find((item) => CANVAS_NAMES.includes(item.name.toLowerCase()));
  if (preferred) return preferred;
  return readyText.sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0] ?? null;
}

export function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [models, setModels] = useState<LmModel[]>([]);
  const [modelId, setModelId] = useState("");
  const [activeDefaultModelId, setActiveDefaultModelId] = useState("");
  const [, setProfile] = useState<ModelProfile | null>(null);
  const [draft, setDraft] = useState("");
  const [pendingApprovals, setPendingApprovals] = useState<Array<Record<string, unknown>>>([]);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [copiedId, setCopiedId] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [systemPromptDraft, setSystemPromptDraft] = useState("");
  const [defaultSystemPrompt, setDefaultSystemPrompt] = useState("");
  const [uiLanguage, setUiLanguage] = useState<"nl" | "en">("nl");
  const chrome = chatChrome(uiLanguage);
  const chatDoctor = useChatDoctor();
  const [codingCards, setCodingCards] = useState<CodingCardJob[]>([]);
  const [codingBusy, setCodingBusy] = useState(false);
  const [researchCards, setResearchCards] = useState<ResearchCardState[]>([]);
  const [researchBusy, setResearchBusy] = useState(false);
  const [workCards, setWorkCards] = useState<WorkCardState[]>([]);
  const [pinBundle, setPinBundle] = useState<PinBundle | null>(null);
  const [pinsBusy, setPinsBusy] = useState(false);
  const [attachmentReport, setAttachmentReport] = useState<Array<Record<string, unknown>>>([]);
  const [lastExecution, setLastExecution] = useState<ChatExecutionState | null>(null);
  const [streamText, setStreamText] = useState("");
  const [modelUsage, setModelUsage] = useState<ModelUsageState>(EMPTY_MODEL_USAGE);
  const [runWallMs, setRunWallMs] = useState<number | null>(null);
  const runStartedAtRef = useRef<number | null>(null);
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
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const reasoningMenuRef = useRef<HTMLDivElement>(null);
  const [sttProvider, setSttProvider] = useState<"none" | "voicestudio" | "paste">("paste");
  const [speechState, setSpeechState] = useState<SpeechPlayerState>(hadesSpeechPlayer.snapshot());
  const [micRecording, setMicRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const micChunksRef = useRef<Blob[]>([]);
  const spokenAnswersRef = useRef(false);
  const streamTextRef = useRef("");
  const sendingRef = useRef(false);
  const pendingAutoSendRef = useRef(false);
  const inFlightRequestIdRef = useRef<string | null>(null);
  const cancelledRequestIdsRef = useRef<Set<string>>(new Set());
  const [ttsProvider, setTtsProvider] = useState<"none" | "voicestudio">("none");
  const [draftCursor, setDraftCursor] = useState(0);
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
  const [showVoiceSetup, setShowVoiceSetup] = useState(false);
  const [lastSpokenAnswer, setLastSpokenAnswer] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const draftTimer = useRef<number | null>(null);
  const mention = useMentionAutocomplete(draft, draftCursor);
  const sendRef = useRef<(options?: { revise_message_id?: string; regenerate_of?: string; content?: string; metadata?: Record<string, unknown> }) => Promise<void>>(async () => undefined);

  useEffect(() => {
    void hadesApi.settings().then((config) => {
      const values = config.values;
      setUiLanguage(values.language === "en" ? "en" : "nl");
      setVoiceLanguage(values.voice_language || "nl");
      setVoiceEnabled(values.voice_enabled !== false);
      setVoiceTurnMode(values.voice_turn_mode === "auto" ? "auto" : "manual");
      setVoiceBargeIn(values.voice_barge_in !== false);
      setVoiceWakeWord(Boolean(values.voice_wake_word_enabled));
      setVoiceEndSilenceMs(Number(values.voice_vad_end_silence_ms) || 900);
      setVoiceVadSensitivity(Number(values.voice_vad_sensitivity) || 0.55);
      setVoiceInputDeviceId(values.voice_input_device_id || "");
      setVoiceOutputDeviceId(values.voice_output_device_id || "");
      setVoiceVolume(Number(values.voice_tts_volume ?? 1));
      setVoiceKeepRecordings(Boolean(values.voice_keep_recordings));
      setVoiceIdleTimeoutSeconds(Number(values.voice_session_idle_seconds ?? 120));
      setVoiceSpeakStyle(values.voice_speak_style === "full" ? "full" : "compact");
      setVoiceTtsVoice(values.voice_tts_voice || "nl_NL-pim-medium");
      setVoiceTtsSpeed(Number(values.voice_tts_speed ?? 1));
      setVoiceTtsProvider(values.voice_tts_provider === "browser" ? "browser" : "piper");
      if (!values.voice_setup_completed_at) setShowVoiceSetup(true);
    }).catch(() => undefined);
  }, []);

  const playback = useVoicePlayback({
    language: voiceLanguage === "auto" ? "nl" : voiceLanguage,
    style: voiceSpeakStyle,
    voiceId: voiceTtsVoice || null,
    speed: voiceTtsSpeed,
    volume: voiceVolume,
    outputDeviceId: voiceOutputDeviceId || null,
    allowBrowserFallback: true,
    preferBrowserTts: voiceTtsProvider === "browser",
    onError: (message) => toast.error(message),
  });

  const dictation = useVoiceDictation({
    language: voiceLanguage === "auto" ? "nl" : voiceLanguage,
    mode: voiceTurnMode === "auto" ? "continuous" : "push_to_talk",
    endSilenceMs: voiceEndSilenceMs,
    speechThreshold: 0.04 - (0.034 * voiceVadSensitivity),
    deviceId: voiceInputDeviceId || null,
    onTranscript: (text, meta) => {
      if (meta.silence || !text) {
        toast.message("Geen spraak herkend — niets verzonden.");
        return;
      }
      setDraft((current) => (current ? `${current.trim()} ${text}` : text));
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
    onError: (message) => toast.error(message),
  });

  const chatCompletion = useMemo(
    () => assessChatCompletion({
      status: lastExecution?.status,
      verification_called: lastExecution?.verification,
      route: lastExecution?.route,
      executed_route: lastExecution?.executed_route,
      reasoning_profile: lastExecution?.reasoning_profile,
      verification_notes: lastExecution?.verification_notes,
      acceptance_checklist: lastExecution?.acceptance_checklist as Array<Record<string, unknown>> | undefined,
    }),
    [lastExecution],
  );
  const correctionNotes = useMemo(
    () => selfCorrectionNotes(lastExecution?.verification_notes),
    [lastExecution?.verification_notes],
  );
  const applyRunProgress = useCallback((progress: ChatRunProgress) => {
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
  streamTextRef.current = streamText || lastExecution?.stream_text || "";
  sendingRef.current = sending;

  // Poll live usage telemetry every second so CURRENT/PEAK/TOTAL move while chatting.
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
          const streamText = streamTextRef.current;
          if ((previous.status === "generating" || previous.status === "running" || sendingRef.current) && streamText) {
            const streamedOut = estimateTokensFromText(streamText);
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


  useEffect(() => {
    let cancelled = false;
    async function loadApprovals() {
      try {
        const items = await hadesApi.approvals();
        if (cancelled) return;
        const scoped = (items as Array<Record<string, unknown>>).filter((item) => {
          if (String(item.status || "") !== "pending") return false;
          if (!selectedId) return true;
          const cid = item.conversation_id ? String(item.conversation_id) : "";
          return !cid || cid === selectedId;
        });
        setPendingApprovals(scoped);
      } catch {
        if (!cancelled) setPendingApprovals([]);
      }
    }
    void loadApprovals();
    const timer = window.setInterval(() => { void loadApprovals(); }, CHAT_APPROVALS_POLL_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [selectedId]);

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

  const selected = useMemo(() => conversations.find((item) => item.id === selectedId), [conversations, selectedId]);
  const activeBranch = useMemo(() => branches.find((item) => item.is_active) ?? null, [branches]);
  const compareReady = branches.length >= 2;

  const refreshConversations = useCallback(async (preferId?: string) => {
    const items = await hadesApi.conversations();
    setConversations(items);
    setSelectedId((current) => preferId ?? current ?? items[0]?.id ?? null);
    return items;
  }, []);

  useEffect(() => {
    async function initialize() {
      setLoading(true);
      try {
        const [conversationItems, modelData, settingsData] = await Promise.all([hadesApi.conversations(), hadesApi.models(), hadesApi.settings()]);
        let items = conversationItems;
        if (!items.length) items = [await hadesApi.createConversation()];
        setConversations(items);
        const deeplinkId = readHashSelection(["c", "id"]);
        const initialId = deeplinkId && items.some((item) => item.id === deeplinkId) ? deeplinkId : items[0].id;
        setSelectedId(initialId);
        setModels(modelData.models);
        setDefaultSystemPrompt(settingsData.values.system_prompt || "");
        setStoredReasoningRaw(String(settingsData.values.reasoning_profile || "adaptive"));
        setReasoningMode(normalizeReasoningMode(settingsData.values.reasoning_profile));
        setReasoningReady(true);
        const spoken = Boolean(settingsData.values.spoken_answers_enabled || settingsData.values.voice_spoken_answers_default);
        setSpokenAnswers(spoken);
        spokenAnswersRef.current = spoken;
        setSttProvider(settingsData.values.stt_provider || "paste");
        setTtsProvider(settingsData.values.tts_provider === "voicestudio" ? "voicestudio" : "none");
        const active = modelData.active_profile?.model_id || modelData.models[0]?.id || "";
        setActiveDefaultModelId(active);
        const initialConversation = items.find((item) => item.id === initialId) || items[0];
        setModelId(resolveConversationModelId(initialConversation?.model_id, active));
        if (active) setProfile(await hadesApi.modelProfile(active));
        if (!modelData.connected) setError("LM Studio is niet verbonden. Gesprekken blijven wel lokaal bewaard.");
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Initialiseren is mislukt.");
      } finally {
        setLoading(false);
      }
    }
    void initialize();
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

  useEffect(() => {
    spokenAnswersRef.current = spokenAnswers;
  }, [spokenAnswers]);

  useEffect(() => {
    if (!selectedId) return;
    const timer = window.setTimeout(() => {
      setLoading(true);
      Promise.all([
        hadesApi.messages(selectedId),
        hadesApi.getDraft(selectedId),
        hadesApi.conversationRuns(selectedId).catch(() => ({ conversation_id: selectedId, runs: [], count: 0 })),
        hadesApi.getConversationPins(selectedId).catch(() => null),
      ])
        .then(([msgs, draftData, linked, pins]) => {
          setMessages(msgs);
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
            setDraft(handoff.draft);
          } else {
            setDraft(draftData.content || "");
          }
          const fromDraft = (draftData.attachment_ids || []).map((id) => ({
            artifact_id: id,
            filename: id,
            status: "ready" as const,
          }));
          setAttachments(fromDraft);
          if (handoff?.autoSend && (handoff.draft?.trim() || fromDraft.length)) {
            pendingAutoSendRef.current = true;
          }
          if (linked.runs?.length) {
            setLastExecution((prev) => ({
              ...(prev || {}),
              linked_runs: linked.runs,
              run_id: linked.runs.find((run) => !["completed", "failed", "cancelled", "rejected", "expired"].includes(String(run.status)))?.run_id
                || prev?.run_id
                || null,
            }));
            const codingLinks = linked.runs.filter((run) => String(run.run_type) === "coding");
            const researchLinks = linked.runs.filter((run) => String(run.run_type) === "research");
            const workLinks = linked.runs.filter((run) => String(run.run_type) === "work");
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
              void Promise.all(
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
              ).then(setCodingCards).catch(() => undefined);
            } else {
              setCodingCards([]);
            }
            if (researchLinks.length) {
              void Promise.all(
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
              ).then(setResearchCards).catch(() => undefined);
            } else {
              setResearchCards([]);
            }
          } else {
            setCodingCards([]);
            setResearchCards([]);
            setWorkCards([]);
          }
        })
        .catch((reason: Error) => setError(reason.message))
        .finally(() => setLoading(false));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selectedId]);

  useEffect(() => {
    if (loading || !selectedId || !pendingAutoSendRef.current) return;
    if (!draft.trim() && !attachments.length) {
      pendingAutoSendRef.current = false;
      return;
    }
    pendingAutoSendRef.current = false;
    void sendRef.current();
  }, [loading, selectedId, draft, attachments]);

  useEffect(() => {
    if (!selectedId) {
      setBranches([]);
      setBranchesError(null);
      return;
    }
    setBranchesLoading(true);
    void hadesApi.listConversationBranches(selectedId)
      .then((items) => {
        setBranches(items);
        setBranchesError(null);
      })
      .catch((reason: Error) => {
        // Keep last-good branches — empty must not look like "no branches".
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
          // Keep last good canvas content; do not fake an empty scratchpad on load failure.
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

  useEffect(() => {
    setTitleDraft(selected?.title ?? "");
    setSystemPromptDraft(selected?.system_prompt_override ?? "");
    setModelId(resolveConversationModelId(selected?.model_id, activeDefaultModelId));
  }, [selected?.id, selected?.title, selected?.system_prompt_override, selected?.model_id, activeDefaultModelId]);

  useEffect(() => {
    if (!selectedId) return;
    if (draftTimer.current) window.clearTimeout(draftTimer.current);
    draftTimer.current = window.setTimeout(() => {
      void hadesApi.saveDraft(selectedId, draft, attachments.map((item) => item.artifact_id)).catch(() => undefined);
    }, 400);
    return () => {
      if (draftTimer.current) window.clearTimeout(draftTimer.current);
    };
  }, [draft, attachments, selectedId]);

  const saveConversationMeta = async () => {
    if (!selectedId) return;
    try {
      const updated = await hadesApi.updateConversation(selectedId, {
        title: titleDraft.trim() || "Nieuw gesprek",
        system_prompt_override: systemPromptDraft.trim() || null,
        update_system_prompt: true,
      });
      setConversations((items) => items.map((item) => item.id === updated.id ? updated : item));
      toast.success("Chatinstellingen opgeslagen.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Chatinstellingen opslaan is mislukt.");
    }
  };

  const changeModel = async (next: string) => {
    setModelId(next);
    try {
      setProfile(await hadesApi.modelProfile(next));
      if (selectedId) {
        const updated = await hadesApi.updateConversation(selectedId, { model_id: next });
        setConversations((items) => items.map((item) => item.id === updated.id ? updated : item));
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Modelprofiel laden is mislukt.");
    }
  };

  const createConversation = async () => {
    try {
      const item = await hadesApi.createConversation("Nieuw gesprek", modelId || undefined);
      await refreshConversations(item.id);
      setMessages([]);
      setDraft("");
      setAttachments([]);
      setError("");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Nieuw gesprek maken is mislukt.");
    }
  };

  const removeConversation = async () => {
    if (!selectedId) return;
    try {
      const preview = await hadesApi.forgetMemoryScope({ conversation_id: selectedId, include_derived: true, preview_only: true });
      await hadesApi.forgetMemoryScope({ conversation_id: selectedId, include_derived: true, preview_only: false });
      const items = await refreshConversations();
      setSelectedId(items[0]?.id ?? null);
      setMessages([]);
      toast.success(`Gesprek verwijderd inclusief afgeleide context (${JSON.stringify(preview.preview || {})}).`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Verwijderen is mislukt.");
    }
  };

  const ensureConversation = async () => {
    if (selectedId) return selectedId;
    const item = await hadesApi.createConversation("Nieuw gesprek", modelId || undefined);
    setSelectedId(item.id);
    return item.id;
  };

  const addFiles = async (files: File[]) => {
    if (!files.length) return;
    if (attachments.length + files.length > 10) {
      toast.error("Maximaal 10 bijlagen per bericht.");
      return;
    }
    const conversationId = await ensureConversation();
    for (const file of files) {
      if (file.size > 20 * 1024 * 1024) {
        toast.error(`${file.name} is groter dan 20 MB.`);
        continue;
      }
      try {
        const uploaded = await hadesApi.uploadChatAttachment(conversationId, file);
        setAttachments((current) => [...current, {
          artifact_id: uploaded.artifact.id,
          filename: uploaded.filename,
          status: uploaded.extract_status || "ready",
        }]);
      } catch (reason) {
        toast.error(reason instanceof Error ? reason.message : `Upload van ${file.name} mislukt.`);
      }
    }
  };

  const persistPins = async (paths: string[]) => {
    if (!selectedId) return;
    setPinsBusy(true);
    try {
      const result = await hadesApi.putConversationPins(selectedId, { paths, force: true });
      setPinBundle({
        accepted: result.accepted || [],
        skipped: result.skipped || [],
        summary: result.summary,
      });
      if (result.skipped?.length) {
        toast.message(`${result.skipped.length} pad(en) overgeslagen (secret/policy).`);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Pins opslaan mislukt.");
    } finally {
      setPinsBusy(false);
    }
  };

  const addPinPath = async (path: string) => {
    const existing = (pinBundle?.accepted || []).map((item) => String(item.path || "")).filter(Boolean);
    const next = Array.from(new Set([...existing, path]));
    await persistPins(next);
  };

  const removePinPath = async (path: string) => {
    const next = (pinBundle?.accepted || [])
      .map((item) => String(item.path || ""))
      .filter((item) => item && item !== path);
    await persistPins(next);
  };

  const pickPinFolder = async () => {
    if (!selectedId) return;
    setPinsBusy(true);
    try {
      const picked = await hadesApi.pickConversationPinFolder(selectedId);
      if (picked.cancelled || !picked.path) {
        toast.message("Mapkiezer geannuleerd.");
        return;
      }
      await addPinPath(picked.path);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Mapkiezer niet beschikbaar — plak een pad.");
    } finally {
      setPinsBusy(false);
    }
  };

  const send = async (options?: { revise_message_id?: string; regenerate_of?: string; content?: string; metadata?: Record<string, unknown> }) => {
    const content = (options?.content ?? draft).trim();
    if ((!content && !attachments.length) || sending) return;
    let conversationId = selectedId;
    const requestId = newRequestId();
    inFlightRequestIdRef.current = requestId;
    const fromVoice = Boolean(options?.metadata?.source === "voice" || options?.metadata?.voice);
    // Barge-in: stop leftover TTS (VoiceStudio and/or built-in) before a new user turn.
    await hadesSpeechPlayer.stop().catch(() => undefined);
    playback.stop();

    try {
      conversationId = await ensureConversation();
      const optimistic: ChatMessage = {
        id: `local-${Date.now()}`, conversation_id: conversationId, role: "user", content: content || "(bijlagen)", created_at: new Date().toISOString(),
        metadata: options?.metadata,
      };
      setMessages((current) => [...current, optimistic]);
      if (!options?.content) setDraft("");
      else setDraft("");
      const attachmentIds = attachments.map((item) => item.artifact_id);
      setAttachments([]);
      setSending(true);
      if (fromVoice || voiceSession.state.sessionId) voiceSession.setModelGenerating(true);
      setError("");
      runStartedAtRef.current = Date.now();
      setRunWallMs(0);
      setModelUsage((current) => ({ ...current, status: "running", modelId: modelId || current.modelId }));
      setLastExecution({ status: "running", tools: [], live_events: [], stream_text: "" });
      setStreamText("");
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
        if (
          cancelledRequestIdsRef.current.has(requestId)
          && execStatus !== "cancelled"
          && execStatus !== "failed"
          && execStatus !== "blocked"
        ) {
          cancelledRequestIdsRef.current.delete(requestId);
          setLastExecution((current) => (current ? { ...current, status: "cancelled" } : current));
          setModelUsage((prev) => ({ ...prev, status: "cancelled" }));
          if (conversationId) {
            try {
              setMessages(await hadesApi.messages(conversationId));
            } catch {
              // Keep the local transcript if reload fails.
            }
          }
          return;
        }
        cancelledRequestIdsRef.current.delete(requestId);
        setMessages((current) => [...current.filter((item) => item.id !== optimistic.id), result.user_message, result.assistant_message]);
        setAttachmentReport(result.attachments || []);
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
        setLastExecution({
          status: result.execution_status,
          linked_task_id: result.linked_task_id,
          run_id: result.run_id || requestId || null,
          target: String(result.executed_route?.actual_target || result.route?.target || ""),
          verification: Boolean(result.executed_route?.verification_called),
          verification_expected: Boolean(result.route?.require_verification),
          route: (result.route as Record<string, unknown> | undefined) || undefined,
          executed_route: (result.executed_route as Record<string, unknown> | undefined) || undefined,
          verification_notes: Array.isArray(result.executed_route?.notes)
            ? (result.executed_route?.notes as string[])
            : [],
          acceptance: Array.isArray(result.acceptance_criteria) && result.acceptance_criteria.length
            ? result.acceptance_criteria
            : Array.isArray(result.request_spec?.acceptance_hints)
              ? (result.request_spec?.acceptance_hints as string[])
              : Array.isArray((result.request_spec as Record<string, unknown> | undefined)?.acceptance_criteria)
                ? ((result.request_spec as Record<string, unknown>).acceptance_criteria as string[])
                : [],
          acceptance_checklist: Array.isArray(result.acceptance_checklist)
            ? result.acceptance_checklist
            : [],
          route_profile: String(result.route?.profile || result.reasoning_profile || ""),
          difficulty_router: (result.difficulty_router as Record<string, unknown> | undefined)
            || (result.reasoning_meta as Record<string, unknown> | undefined)
            || undefined,
          tools: (result.tools as Array<Record<string, unknown>> | undefined) || [],
          tool_cards: (result.tool_cards as Array<Record<string, unknown>> | undefined) || [],
          reasoning_profile: result.reasoning_profile,
          selected_mode: result.selected_mode,
          effective_policy: result.effective_policy,
          decision_reason: result.decision_reason,
          retrieval: (result.retrieval as Record<string, unknown> | undefined) || undefined,
          working_state: (result.working_state as Record<string, unknown> | undefined) || undefined,
          budget: (result.budget as Record<string, unknown> | undefined) || undefined,
          live_events: [],
          stream_text: "",
          grounding: (result.grounding as Record<string, unknown> | undefined) || undefined,
          verification_display: result.verification_display,
          result_artifact_id: result.result_artifact_id || null,
          persistence: Array.isArray(result.persistence) ? result.persistence : [],
        });
        try {
          setBranches(await hadesApi.listConversationBranches(conversationId));
          setBranchesError(null);
        } catch (reason) {
          setBranchesError(reason instanceof Error ? reason.message : "Branches laden mislukt.");
        }
        await refreshConversations(conversationId);
        // Speak only the final assistant message — never provisional stream_delta text.
        // Spraakgesprek always speaks; typed chat respects Gesproken antwoorden.
        const inVoiceSession = Boolean(voiceSession.state.sessionId);
        if (result.assistant_message?.content && (spokenAnswersRef.current || inVoiceSession)) {
          setLastSpokenAnswer(result.assistant_message.content);
          if (inVoiceSession) {
            await voiceSession.speakAssistantResponse(result.assistant_message.content, result.assistant_message.id);
          } else if (ttsProvider === "voicestudio") {
            void hadesSpeechPlayer.speakText(result.assistant_message.content, result.assistant_message.id).catch((reason) => {
              toast.error(reason instanceof Error ? reason.message : "Voorlezen mislukt. Tekstchat blijft beschikbaar.");
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
      if (conversationId) {
        try {
          setMessages(await hadesApi.messages(conversationId));
        } catch {
          // Keep existing transcript — reload failure must not wipe the chat.
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
      }
    }
  };

  const cancelInFlight = async () => {
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
    await chatRun.cancelRun(runId || undefined);

    // Unified Stop: cancel linked conversation engines that support cancellation.
    const linked = lastExecution?.linked_runs || [];
    const cancels: Array<Promise<unknown>> = [];
    for (const link of linked) {
      const status = String(link.status || "").toLowerCase();
      if (["completed", "failed", "cancelled", "rejected", "expired"].includes(status)) continue;
      if (link.run_type === "coding") {
        cancels.push(hadesApi.buildJobCancel(link.run_id).catch(() => undefined));
      } else if (link.run_type === "research") {
        cancels.push(hadesApi.cancelResearch(link.run_id).catch(() => undefined));
      } else if (link.run_type === "work") {
        cancels.push(hadesApi.cancelTask(link.run_id).catch(() => undefined));
      }
    }
    for (const job of codingCards) {
      if (!["completed", "failed", "cancelled"].includes(job.status.toLowerCase())) {
        cancels.push(hadesApi.buildJobCancel(job.job_id).catch(() => undefined));
      }
    }
    for (const research of researchCards) {
      if (!["completed", "failed", "cancelled"].includes(research.status.toLowerCase())) {
        cancels.push(hadesApi.cancelResearch(research.project_id).catch(() => undefined));
      }
    }
    await Promise.all(cancels);
    setCodingCards((current) => current.map((item) => (
      ["completed", "failed", "cancelled"].includes(item.status.toLowerCase())
        ? item
        : { ...item, status: "cancelled" }
    )));
    setResearchCards((current) => current.map((item) => (
      ["completed", "failed", "cancelled"].includes(item.status.toLowerCase())
        ? item
        : { ...item, status: "cancelled" }
    )));
    setWorkCards((current) => current.map((item) => (
      ["completed", "failed", "cancelled"].includes(item.status.toLowerCase())
        ? item
        : { ...item, status: "cancelled" }
    )));
  };

  sendRef.current = send;

  const toggleSpokenAnswers = async (checked: boolean) => {
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
      toast.error(reason instanceof Error ? reason.message : "Gesproken antwoorden opslaan mislukt.");
    }
  };

  useEffect(() => {
    if (!reasoningOpen) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!reasoningMenuRef.current?.contains(event.target as Node)) setReasoningOpen(false);
    };
    const closeOnEscape = (event: Event) => {
      if ("key" in event && (event as { key: string }).key === "Escape") setReasoningOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [reasoningOpen]);

  const changeReasoningMode = async (next: ProductReasoningMode) => {
    setReasoningOpen(false);
    if (!reasoningReady || reasoningSaving || next === reasoningMode) return;
    const previous = reasoningMode;
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
      toast.error(reason instanceof Error ? reason.message : "Denkmodus wijzigen is mislukt.");
    } finally {
      setReasoningSaving(false);
    }
  };

  const activeReasoningMode = REASONING_MODE_OPTIONS.find((item) => item.id === reasoningMode) ?? REASONING_MODE_OPTIONS[REASONING_MODE_OPTIONS.length - 1]!;

  const speakMessage = async (message: ChatMessage) => {
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
      toast.error(reason instanceof Error ? reason.message : "Voorlezen mislukt.");
    }
  };

  const toggleMic = async () => {
    if (micRecording) {
      mediaRecorderRef.current?.stop();
      setMicRecording(false);
      return;
    }
    if (sttProvider !== "voicestudio") {
      toast.message("STT staat op plakken. Zet Instellingen → Spraak → STT-provider op VoiceStudio voor microfoon, of gebruik Dictatie (ingebouwd).");
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
          if (text) setDraft((current) => (current ? `${current.trim()} ${text}` : text));
          else toast.error("Geen transcript ontvangen.");
        }).catch((reason) => {
          toast.error(reason instanceof Error ? reason.message : "Transcriptie mislukt.");
        });
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setMicRecording(true);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Microfoon starten mislukt.");
      setMicRecording(false);
    }
  };


  const copy = async (message: ChatMessage) => {
    await navigator.clipboard.writeText(message.content);
    setCopiedId(message.id);
    window.setTimeout(() => setCopiedId(""), 1_500);
  };

  const branchFrom = async (message: ChatMessage) => {
    if (!selectedId) return;
    try {
      const branch = await hadesApi.branchConversation(selectedId, message.id);
      setDraft("");
      const [branchItems, msgs] = await Promise.all([
        hadesApi.listConversationBranches(selectedId),
        hadesApi.messages(selectedId),
      ]);
      setBranches(branchItems);
      setMessages(msgs);
      toast.success(`Branch here → ${branch.title || branch.id}; UI volgt deze fork.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Vertakken mislukt.");
    }
  };

  const activateBranch = async (branchId: string) => {
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
      toast.success(`Vertakking "${target.title}" geactiveerd.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Vertakking activeren mislukt.");
    } finally {
      setBranchActivatingId("");
    }
  };

  const openInCanvas = (content: string) => {
    setCanvasContent(content);
    setCanvasDirty(true);
    setCanvasOpen(true);
    toast.success("In canvas geplaatst — opslaan maakt een nieuwe versie.");
  };

  const saveCanvas = async () => {
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
      toast.success("Canvas opgeslagen als canvas.md.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Canvas opslaan mislukt.");
    } finally {
      setCanvasSaving(false);
    }
  };

  const applyMention = (item: MentionSuggestion) => {
    const applied = mention.applySuggestion(item, draft, draftCursor);
    setDraft(applied.next);
    setDraftCursor(applied.nextCursor);
    window.setTimeout(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(applied.nextCursor, applied.nextCursor);
    }, 0);
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention.open && mention.items.length) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        mention.setActiveIndex((index) => Math.min(index + 1, mention.items.length - 1));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        mention.setActiveIndex((index) => Math.max(index - 1, 0));
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        const pick = mention.items[mention.activeIndex];
        if (pick) applyMention(pick);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  };

  const reuseArtifact = (artifact: HadesArtifact) => {
    setAttachments((current) => {
      if (current.some((item) => item.artifact_id === artifact.id)) return current;
      return [...current, { artifact_id: artifact.id, filename: artifact.name, status: "ready" }];
    });
    toast.success(`${artifact.name} toegevoegd als bijlage.`);
  };

  return (
    <div className="chat-layout functional-chat">
      <aside className="conversation-rail">
        <Button className="new-chat" variant="outline" onClick={createConversation}><Plus />{chrome.newChat}</Button>
        <div className="rail-label">{uiLanguage === "en" ? "Local conversations" : "Lokale gesprekken"}</div>
        <div className="conversation-list">
          {conversations.map((item) => (
            <button key={item.id} className={item.id === selectedId ? "conversation active" : "conversation"} type="button" onClick={() => setSelectedId(item.id)}>
              <span>{item.title}</span><small>{formatDate(item.updated_at)}</small>
            </button>
          ))}
          {!conversations.length && !loading ? <p className="empty-copy">Nog geen gesprekken.</p> : null}
        </div>
      </aside>

      <section className="chat-canvas">
        <div className="chat-titlebar">
          <h1 className="visually-hidden">{selected?.title || "Chat"}</h1>
          <div className="chat-title-edit"><span className="eyebrow">Privé Workspace</span><Input aria-label="Chatnaam" value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} onBlur={() => void saveConversationMeta()} className="chat-title-input" /></div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!selectedId}
            aria-label="Exporteer gesprek als Markdown"
            onClick={() => {
              if (!selectedId) return;
              void hadesApi.exportConversation(selectedId)
                .then((result) => {
                  const blob = new Blob([result.markdown], { type: "text/markdown;charset=utf-8" });
                  const url = URL.createObjectURL(blob);
                  const anchor = document.createElement("a");
                  anchor.href = url;
                  anchor.download = `${(selected?.title || "conversation").replace(/[^\w\-]+/g, "_").slice(0, 60)}.md`;
                  anchor.click();
                  URL.revokeObjectURL(url);
                  toast.success("Gesprek geëxporteerd (secrets geredacteerd).");
                })
                .catch((reason: Error) => toast.error(reason.message || "Export mislukt."));
            }}
          >
            <Download />Export
          </Button>
          <div ref={reasoningMenuRef} className="relative">
            <button
              type="button"
              aria-haspopup="listbox"
              aria-expanded={reasoningOpen}
              aria-label={`Denkdiepte: ${activeReasoningMode.label}`}
              disabled={!reasoningReady || reasoningSaving}
              onClick={() => setReasoningOpen((current) => !current)}
              className="flex h-8 items-center gap-1.5 rounded-lg border border-transparent bg-transparent px-2 text-[0.68rem] font-semibold text-[#5f594f] transition hover:border-[#ded7ca] hover:bg-[#f4f0e8] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <BrainCircuit className="h-3.5 w-3.5 text-[#9c773e]" />
              <span>{activeReasoningMode.label}</span>
              <ChevronDown className={`h-3 w-3 text-[#8a8276] transition-transform ${reasoningOpen ? "rotate-180" : ""}`} />
            </button>
            {reasoningOpen ? (
              <div
                role="listbox"
                aria-label="Denkdiepte kiezen"
                className="absolute right-0 top-[calc(100%+0.45rem)] z-50 w-[20rem] overflow-hidden rounded-xl border border-[#ded8cc] bg-[#fffefa]/[.98] p-1.5 shadow-[0_18px_50px_#2d241817] backdrop-blur-xl"
              >
                <div className="px-2.5 pb-1 pt-1 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-[#91897d]">Denkdiepte</div>
                {REASONING_MODE_OPTIONS.map((item) => {
                  const active = item.id === reasoningMode;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      aria-selected={active}
                      disabled={!reasoningReady || reasoningSaving}
                      onClick={() => void changeReasoningMode(item.id)}
                      className={`flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition ${active ? "bg-[#efe9de]" : "hover:bg-[#f5f1e9]"}`}
                    >
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-[#e2dbcf] bg-[#fbf8f2] text-[#8b6a39]">
                        <BrainCircuit className="h-3.5 w-3.5" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <strong className="text-[0.74rem] font-semibold text-[#2f2b25]">{item.label}</strong>
                          {item.id === "adaptive" ? <small className="rounded-full bg-[#eee6d7] px-1.5 py-0.5 text-[0.52rem] font-semibold text-[#765b32]">Aanbevolen</small> : null}
                        </span>
                        <small className="mt-0.5 block text-[0.62rem] leading-4 text-[#81796d]">{item.hint}</small>
                      </span>
                      <span className="grid h-7 w-5 shrink-0 place-items-center text-[#6f634f]">{active ? <Check className="h-3.5 w-3.5" /> : null}</span>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
          <label className="spoken-answers-toggle" title="Lees definitieve antwoorden voor via de gekozen TTS-provider">
            <span>Gesproken antwoorden</span>
            <Switch checked={spokenAnswers} onCheckedChange={(checked) => void toggleSpokenAnswers(checked)} />
          </label>
          {speechState.speaking ? (
            <Button variant="outline" size="sm" onClick={() => void hadesSpeechPlayer.stop()} aria-label="Voorlezen stoppen">
              <Square />Stop spraak
            </Button>
          ) : null}
          <Button variant="ghost" size="icon" onClick={removeConversation} disabled={!selectedId} aria-label="Gesprek verwijderen"><Trash2 /></Button>
        </div>

        <ChatDoctorBanner
          health={chatDoctor.health}
          settings={chatDoctor.settings}
          onRetry={chatDoctor.refresh}
          showLexicalHint={!messages.length}
        />

        {codingCards.length ? (
          <div className="chat-coding-cards" aria-label="Coding-jobs in dit gesprek">
            {codingCards.map((job) => (
              <CodingCard
                key={job.job_id}
                job={job}
                busy={codingBusy}
                onRefresh={() => {
                  void hadesApi.buildJobGet(job.job_id).then((snap) => {
                    const result = (snap.result || {}) as Record<string, unknown>;
                    setCodingCards((current) => current.map((item) => (
                      item.job_id === job.job_id
                        ? {
                            ...item,
                            status: String(snap.status || item.status),
                            phase: String((snap.checkpoint as { phase?: string } | undefined)?.phase || item.phase || ""),
                            files_changed: Array.isArray(result.changed_files)
                              ? result.changed_files.map(String)
                              : item.files_changed,
                            unified_diff: typeof result.unified_diff === "string" ? result.unified_diff : item.unified_diff,
                            test_output: typeof result.test_output === "string" ? result.test_output : item.test_output,
                          }
                        : item
                    )));
                  }).catch(() => undefined);
                }}
                onApplyAll={() => {
                  const runId = String((job as CodingCardJob & { run_id?: string }).run_id || "");
                  // Apply uses build run id when present; otherwise open Advanced for review.
                  if (!runId) {
                    window.location.hash = `/fb/coding?codingJob=${encodeURIComponent(job.job_id)}`;
                    return;
                  }
                  setCodingBusy(true);
                  void hadesApi.buildApply(runId, true)
                    .then(() => toast.success("Apply uitgevoerd — controleer verificatie."))
                    .catch((reason: Error) => toast.error(reason.message || "Apply mislukt."))
                    .finally(() => setCodingBusy(false));
                }}
                onReject={() => {
                  setCodingBusy(true);
                  void hadesApi.buildJobCancel(job.job_id)
                    .then(() => {
                      toast.message("Coding-job geannuleerd/rejected.");
                      setCodingCards((current) => current.map((item) => (
                        item.job_id === job.job_id ? { ...item, status: "cancelled" } : item
                      )));
                    })
                    .catch((reason: Error) => toast.error(reason.message || "Annuleren mislukt."))
                    .finally(() => setCodingBusy(false));
                }}
              />
            ))}
          </div>
        ) : null}

        {researchCards.length ? (
          <div className="chat-research-cards" aria-label="Onderzoek in dit gesprek">
            {researchCards.map((item) => (
              <ResearchCard
                key={item.project_id}
                research={item}
                busy={researchBusy}
                onRefresh={() => {
                  void hadesApi.researchProject(item.project_id).then((detail) => {
                    setResearchCards((current) => current.map((row) => (
                      row.project_id === item.project_id
                        ? {
                            ...row,
                            status: String(detail.project.status || row.status),
                            source_count: detail.sources?.length || 0,
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
                  }).catch(() => undefined);
                }}
                onStop={() => {
                  setResearchBusy(true);
                  void hadesApi.cancelResearch(item.project_id)
                    .then((project) => {
                      setResearchCards((current) => current.map((row) => (
                        row.project_id === item.project_id ? { ...row, status: String(project.status || "cancelled") } : row
                      )));
                    })
                    .catch((reason: Error) => toast.error(reason.message || "Stop mislukt."))
                    .finally(() => setResearchBusy(false));
                }}
                onGoDeeper={() => {
                  setResearchBusy(true);
                  void hadesApi.runResearch(item.project_id)
                    .then((project) => {
                      toast.message("Diepere onderzoeksronde gestart.");
                      setResearchCards((current) => current.map((row) => (
                        row.project_id === item.project_id ? { ...row, status: String(project.status || row.status) } : row
                      )));
                    })
                    .catch((reason: Error) => toast.error(reason.message || "Dieper gaan mislukt."))
                    .finally(() => setResearchBusy(false));
                }}
              />
            ))}
          </div>
        ) : null}

        {pendingApprovals.length ? (
          <div className="chat-approval-cards" aria-label="Goedkeuringen in dit gesprek">
            {pendingApprovals.slice(0, 5).map((item) => (
              <ApprovalCard
                key={String(item.id)}
                item={{
                  id: String(item.id),
                  tool_name: item.tool_name ? String(item.tool_name) : undefined,
                  kind: item.kind ? String(item.kind) : undefined,
                  summary: item.summary ? String(item.summary) : undefined,
                  timed_out: Boolean(item.timed_out),
                  status: item.status ? String(item.status) : "pending",
                }}
                busy={approvalBusy === String(item.id)}
                onApprove={() => {
                  void (async () => {
                    setApprovalBusy(String(item.id));
                    try {
                      const decided = await hadesApi.decideApproval(String(item.id), true);
                      if (decided && (decided as Record<string, unknown>).resume_ok === false) {
                        toast.error(String((decided as Record<string, unknown>).resume_error || "Goedkeuring opgeslagen, hervatten mislukt."));
                      } else {
                        toast.success("Goedgekeurd — run hervat in dit gesprek.");
                      }
                      setPendingApprovals(await hadesApi.approvals() as Array<Record<string, unknown>>);
                    } catch (reason) {
                      toast.error(reason instanceof Error ? reason.message : "Goedkeuren mislukt.");
                    } finally {
                      setApprovalBusy(null);
                    }
                  })();
                }}
                onReject={() => {
                  void (async () => {
                    setApprovalBusy(String(item.id));
                    try {
                      await hadesApi.decideApproval(String(item.id), false);
                      toast.message("Afgewezen.");
                      setPendingApprovals(await hadesApi.approvals() as Array<Record<string, unknown>>);
                    } catch (reason) {
                      toast.error(reason instanceof Error ? reason.message : "Afwijzen mislukt.");
                    } finally {
                      setApprovalBusy(null);
                    }
                  })();
                }}
              />
            ))}
          </div>
        ) : null}

        {workCards.length ? (
          <div className="chat-work-cards" aria-label="Work Runtime in dit gesprek">
            {workCards.map((work) => (
              <WorkCard key={work.task_id} work={work} />
            ))}
          </div>
        ) : null}

        <ChatTimeline
          messages={messages}
          loading={loading}
          sending={sending}
          execution={lastExecution}
          streamText={streamText}
          copiedId={copiedId}
          speakingMessageId={speechState.speaking ? speechState.messageId : null}
          onCopy={(message) => void copy(message)}
          onEdit={(message) => setDraft(message.content)}
          onResend={(message) => void send({ revise_message_id: message.id, content: message.content })}
          onBranch={(message) => void branchFrom(message)}
          onRegenerate={(message) => {
            const prior = [...messages].reverse().find((item) => item.role === "user" && item.created_at <= message.created_at);
            if (prior) void send({ regenerate_of: message.id, content: prior.content, revise_message_id: prior.id });
          }}
          onSpeak={(message) => void speakMessage(message)}
          onStopSpeaking={() => void hadesSpeechPlayer.stop()}
          onOpenInCanvas={openInCanvas}
          renderVoiceActions={(message) => voiceEnabled ? (
            <VoiceMessageActions
              speaking={playback.speaking || voiceSession.audioPlaying}
              isCurrentMessage={
                playback.messageId === message.id
                || (Boolean(lastSpokenAnswer) && lastSpokenAnswer === message.content && voiceSession.audioPlaying)
              }
              disabled={sending}
              onSpeak={() => { void speakMessage(message); }}
              onReplay={() => {
                if (voiceSession.state.sessionId) {
                  void voiceSession.speakAssistantResponse(message.content, message.id, { forceReplay: true });
                } else if (ttsProvider === "voicestudio") {
                  void speakMessage(message);
                } else {
                  void playback.replay();
                }
              }}
              onStop={() => {
                playback.stop();
                void voiceSession.interrupt();
                void hadesSpeechPlayer.stop().catch(() => undefined);
              }}
            />
          ) : null}
        />

        <div className="composer-wrap">
          {error ? <div className="inline-error"><ServerOff />{error}</div> : null}
          {voiceEnabled && showVoiceSetup ? (
            <div className="voice-setup-inline">
              <VoiceSetupWizard
                open={showVoiceSetup}
                onComplete={() => {
                  void (async () => {
                    try {
                      const config = await hadesApi.settings();
                      await hadesApi.saveSettings({
                        ...config.values,
                        voice_setup_completed_at: new Date().toISOString(),
                      });
                      setShowVoiceSetup(false);
                      toast.success("Spraaksetup afgerond.");
                    } catch (reason) {
                      toast.error(reason instanceof Error ? reason.message : "Spraaksetup opslaan mislukt.");
                    }
                  })();
                }}
                onClose={() => setShowVoiceSetup(false)}
              />
            </div>
          ) : null}
          {voiceEnabled && voiceSession.state.sessionId ? (
            <VoicePanel
              status={voiceSession.status}
              level={voiceSession.level}
              micActive={voiceSession.micActive}
              modelGenerating={voiceSession.modelGenerating}
              audioPlaying={voiceSession.audioPlaying}
              transcript={voiceSession.state.lastTranscript || dictation.partialText}
              lastAnswer={lastSpokenAnswer}
              error={voiceSession.state.lastError}
              muted={voiceSession.state.micState === "muted"}
              outputMuted={voiceSession.outputMuted}
              turnMode={voiceSession.turnMode}
              lastInterruptLatencyMs={voiceSession.lastInterruptLatencyMs}
              onToggleMute={() => voiceSession.setMicMuted(voiceSession.state.micState !== "muted")}
              onToggleOutputMute={() => voiceSession.setOutputMuted(!voiceSession.outputMuted)}
              onHoldPushToTalk={(down) => voiceSession.holdPushToTalk(down)}
              onInterrupt={() => void voiceSession.interrupt()}
              onStop={() => void voiceSession.stopSession()}
              onOpenSettings={() => {
                sessionStorage.setItem("hades-settings-tab", "Spraak");
                window.location.hash = "#/settings";
              }}
            />
          ) : null}
          {attachmentReport.length ? (
            <div className="attachment-report">
              {attachmentReport.map((item) => (
                <small key={String(item.id)}>
                  {String(item.filename)}: {String(item.extract_status)}{item.used_in_context ? " · gelezen" : " · niet in context"}
                </small>
              ))}
            </div>
          ) : null}
          <ContextTurnPanel retrieval={lastExecution?.retrieval} />
          <ChatPinsBar
            bundle={pinBundle}
            busy={pinsBusy || !selectedId}
            onAddPath={(path) => void addPinPath(path)}
            onPickFolder={() => void pickPinFolder()}
            onRemovePath={(path) => void removePinPath(path)}
          />
          <ChatComposer
            draft={draft}
            attachments={attachments}
            sending={sending}
            micRecording={micRecording}
            sttProvider={sttProvider}
            textareaRef={textareaRef}
            fileRef={fileRef}
            onDraftChange={(value, cursor) => {
              setDraft(value);
              setDraftCursor(cursor);
            }}
            onCursorChange={setDraftCursor}
            onKeyDown={onComposerKeyDown}
            onFiles={(files) => void addFiles(files)}
            onRemoveAttachment={(id) => setAttachments((current) => current.filter((entry) => entry.artifact_id !== id))}
            onToggleMic={() => void toggleMic()}
            onSend={() => void send()}
            onCancel={() => void cancelInFlight()}
            footerMeta={(
              <span className="composer-live-meta">
                <span>{modelId || chatDoctor.health?.active_model || "geen model"}</span>
                <span aria-hidden="true">·</span>
                <span>
                  {typeof modelUsage.currentTotal === "number"
                    ? `~${modelUsage.currentTotal} tokens`
                    : typeof modelUsage.currentInput === "number" || typeof modelUsage.currentOutput === "number"
                      ? `~${(modelUsage.currentInput || 0) + (modelUsage.currentOutput || 0)} tokens`
                      : "context live"}
                </span>
                <span aria-hidden="true">·</span>
                <span>
                  {chatDoctor.settings?.embedding_model_id
                    ? "retrieval: hybrid"
                    : "retrieval: lexical"}
                </span>
                {pinBundle?.summary ? (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>
                      pins: {pinBundle.summary.indexed} idx / {pinBundle.summary.stale} stale / {pinBundle.summary.skipped} skip
                    </span>
                  </>
                ) : null}
                {chatDoctor.settings?.streaming === false ? (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>streaming uit</span>
                  </>
                ) : null}
              </span>
            )}
            mentionList={(
              <MentionAutocompleteList
                open={mention.open}
                items={mention.items}
                loading={mention.loading}
                error={mention.error}
                activeIndex={mention.activeIndex}
                onPick={applyMention}
                onHover={mention.setActiveIndex}
              />
            )}
            controls={voiceEnabled ? (
              <VoiceComposerControls
                dictationActive={dictation.listening}
                dictationLevel={dictation.level}
                sessionActive={Boolean(voiceSession.state.sessionId)}
                speaking={playback.speaking || voiceSession.audioPlaying}
                spokenAnswers={spokenAnswers}
                disabled={sending}
                error={dictation.error || voiceSession.state.lastError}
                onToggleDictation={() => void dictation.toggle()}
                onStartConversation={() => void voiceSession.startSession()}
                onStopConversation={() => void voiceSession.stopSession()}
                onSpokenAnswersChange={(checked) => void toggleSpokenAnswers(checked)}
                onHoldPushToTalk={(down) => {
                  if (voiceSession.state.sessionId) voiceSession.holdPushToTalk(down);
                  else dictation.holdPushToTalk(down);
                }}
                onStopSpeaking={() => {
                  playback.stop();
                  void voiceSession.interrupt();
                  void hadesSpeechPlayer.stop().catch(() => undefined);
                }}
              />
            ) : null}
          />
        </div>
      </section>

      <aside className="context-rail">
        <ModelUsageCard
          models={models}
          modelId={modelId}
          onModelChange={changeModel}
          usage={modelUsage}
          telemetry={chatTelemetry}
        />
        <Panel title={chrome.systemPrompt} className="flat-panel"><div className="form-stack"><Textarea value={systemPromptDraft} onChange={(event) => setSystemPromptDraft(event.target.value)} placeholder={defaultSystemPrompt || "Leeg = system prompt uit Instellingen"} className="chat-system-prompt" /><small>{systemPromptDraft.trim() ? "Deze prompt geldt alleen voor deze chat." : "Gebruikt automatisch de globale system prompt uit Instellingen."}</small><Button variant="outline" size="sm" onClick={() => void saveConversationMeta()}><Save />Opslaan voor chat</Button></div></Panel>
        <ResultsPanel conversationId={selectedId || undefined} onReuse={reuseArtifact} />
        <Panel title="Canvas" className="flat-panel canvas-panel" actions={(
          <Button variant="ghost" size="icon" onClick={() => setCanvasOpen((open) => !open)} aria-label={canvasOpen ? "Canvas inklappen" : "Canvas uitklappen"}>
            {canvasOpen ? <ChevronUp /> : <ChevronDown />}
          </Button>
        )}>
          {canvasOpen ? (
            <>
              {canvasLoading ? <small><Loader2 className="spin" /> Canvas laden…</small> : null}
              {canvasError ? <p className="empty-copy inline-error">{canvasError}</p> : null}
              {!canvasLoading ? (
                <Textarea
                  className="canvas-editor"
                  value={canvasContent}
                  onChange={(event) => {
                    setCanvasContent(event.target.value);
                    setCanvasDirty(true);
                  }}
                  placeholder="Lang antwoord, outline of notities naast de chat. Opslaan maakt canvas.md."
                  aria-label="Canvas scratchpad"
                />
              ) : null}
              <div className="canvas-meta">
                {canvasArtifactId ? <small>Versie: {canvasArtifactId.slice(0, 10)}…</small> : <small>Nog geen opgeslagen canvas voor dit gesprek.</small>}
                {canvasDirty ? <StatusBadge tone="warning">Niet opgeslagen</StatusBadge> : canvasContent.trim() ? <StatusBadge tone="success">Gesynchroniseerd</StatusBadge> : null}
              </div>
              <div className="canvas-actions">
                <Button variant="outline" size="sm" onClick={() => void saveCanvas()} disabled={canvasSaving || !selectedId}>
                  {canvasSaving ? <Loader2 className="spin" /> : <Save />}
                  Opslaan
                </Button>
              </div>
            </>
          ) : (
            <p className="empty-copy">{canvasContent.trim() ? "Canvas ingeklapt — bevat tekst." : "Canvas ingeklapt — nog leeg."}</p>
          )}
        </Panel>
        <Panel title={chrome.branches} className="flat-panel">
          <div className="branch-compare-head">
            <small>{activeBranch ? `Actief: ${activeBranch.title}` : "Hoofdlijn"}</small>
            <Button
              variant={compareMode ? "default" : "outline"}
              size="sm"
              className="h-7 px-2 text-[0.62rem]"
              onClick={() => setCompareMode((mode) => !mode)}
              disabled={!compareReady}
            >
              <Columns2 />
              Vergelijk
            </Button>
          </div>
          {branchesLoading ? <small><Loader2 className="spin" /> Vertakkingen laden…</small> : null}
          {branchesError ? <p className="empty-copy inline-error">{branchesError}</p> : null}
          {!branchesLoading && branches.length ? (
            <ul className="branch-list">
              {branches.map((branch) => (
                <li key={branch.id} className={branch.is_active ? "branch-item active" : "branch-item"}>
                  <GitBranch />
                  <div>
                    <strong>{branch.title}</strong>
                    <small>{formatDate(branch.created_at)}{branch.is_active ? " · actief" : ""}</small>
                  </div>
                  {!branch.is_active ? (
                    <button
                      type="button"
                      className="branch-activate"
                      disabled={branchActivatingId === branch.id}
                      onClick={() => void activateBranch(branch.id)}
                    >
                      {branchActivatingId === branch.id ? "…" : "Activeren"}
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {!branchesLoading && !branchesError && !branches.length ? (
            <p className="empty-copy">Geen vertakkingen — gebruik <em>Vertakken</em> op een eigen bericht.</p>
          ) : null}
          {compareMode ? (
            <div className="branch-compare">
              {!compareReady ? (
                <p className="branch-compare-empty">Maak minstens twee vertakkingen om te vergelijken.</p>
              ) : (
                <>
                  <div className="branch-compare-picks">
                    <Select value={compareLeftId} onValueChange={setCompareLeftId}>
                      <SelectTrigger aria-label="Eerste vertakking"><SelectValue placeholder="Links" /></SelectTrigger>
                      <SelectContent>{branches.map((branch) => <SelectItem key={`left-${branch.id}`} value={branch.id}>{branch.title}</SelectItem>)}</SelectContent>
                    </Select>
                    <Select value={compareRightId} onValueChange={setCompareRightId}>
                      <SelectTrigger aria-label="Tweede vertakking"><SelectValue placeholder="Rechts" /></SelectTrigger>
                      <SelectContent>{branches.map((branch) => <SelectItem key={`right-${branch.id}`} value={branch.id}>{branch.title}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  {compareLeftId === compareRightId ? (
                    <p className="branch-compare-empty">Kies twee verschillende vertakkingen.</p>
                  ) : compareLoading ? (
                    <small><Loader2 className="spin" /> Laatste assistent-antwoorden laden…</small>
                  ) : (
                    <div className="branch-compare-grid">
                      {compareSides.map((side, index) => (
                        <div className="branch-compare-col" key={side?.branchId ?? index}>
                          <header>{side?.title ?? (index === 0 ? "Links" : "Rechts")}</header>
                          <pre className={side?.empty ? "empty" : undefined}>
                            {side?.empty
                              ? "Geen assistent-antwoord op deze vertakking."
                              : side?.text ?? "Vergelijking niet beschikbaar."}
                          </pre>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ) : null}
        </Panel>
        <Panel title="Status" className="flat-panel">
          {pendingApprovals.length ? (
            <div className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" role="alert">
              <strong>{chrome.pendingApproval}</strong>
              <p className="m-0 mt-1 text-muted-foreground">
                {pendingApprovals.length} aanvraag(en) wachten op expliciete beslissing. Timeout blijft pending — nooit auto-allow.
              </p>
              <ul className="m-0 mt-2 list-disc pl-4">
                {pendingApprovals.slice(0, 5).map((item) => (
                  <li key={String(item.id)} className="flex flex-wrap items-center gap-2">
                    <code>{String(item.tool_name || item.kind || item.id)}</code>
                    {item.timed_out ? <StatusBadge tone="warning">timeout/pending</StatusBadge> : <StatusBadge tone="warning">pending</StatusBadge>}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={approvalBusy === String(item.id)}
                      onClick={() => {
                        void (async () => {
                          setApprovalBusy(String(item.id));
                          try {
                            const decided = await hadesApi.decideApproval(String(item.id), true);
                            if (decided && (decided as Record<string, unknown>).resume_ok === false) {
                              toast.error(String((decided as Record<string, unknown>).resume_error || "Goedkeuring opgeslagen, hervatten mislukt."));
                            } else {
                              toast.success("Goedgekeurd.");
                            }
                            setPendingApprovals(await hadesApi.approvals() as Array<Record<string, unknown>>);
                          } catch (reason) {
                            toast.error(reason instanceof Error ? reason.message : "Goedkeuren mislukt.");
                          } finally {
                            setApprovalBusy(null);
                          }
                        })();
                      }}
                    >
                      Goedkeuren
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={approvalBusy === String(item.id)}
                      onClick={() => {
                        void (async () => {
                          setApprovalBusy(String(item.id));
                          try {
                            await hadesApi.decideApproval(String(item.id), false);
                            toast.message("Afgewezen.");
                            setPendingApprovals(await hadesApi.approvals() as Array<Record<string, unknown>>);
                          } catch (reason) {
                            toast.error(reason instanceof Error ? reason.message : "Afwijzen mislukt.");
                          } finally {
                            setApprovalBusy(null);
                          }
                        })();
                      }}
                    >
                      Afwijzen
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <ExecutionCompletionBanner assessment={chatCompletion} />
          <Button variant="outline" className="full-button" onClick={() => window.location.reload()}><RefreshCcw />Gegevens vernieuwen</Button>
          <StatusBadge tone={error ? "warning" : lastExecution?.status === "failed" || lastExecution?.status === "partial" ? "warning" : "success"}>
            {error ? "Aandacht nodig" : lastExecution?.status ? `Uitvoering: ${lastExecution.status}` : "Gereed"}
          </StatusBadge>
          {lastExecution?.difficulty_router ? (
            <span title={String(lastExecution.difficulty_router.rationale || "")} className="routing-meta-badge">
              <StatusBadge tone={lastExecution.difficulty_router.stop_and_ask ? "warning" : "info"}>
                Route: {String(lastExecution.difficulty_router.path || "—")}
                {" · "}
                {String(lastExecution.difficulty_router.profile || lastExecution.route_profile || "—")}
                {lastExecution.difficulty_router.agent_id ? ` · ${String(lastExecution.difficulty_router.agent_id)}` : ""}
                {lastExecution.difficulty_router.stop_and_ask ? " · stop-and-ask" : ""}
              </StatusBadge>
            </span>
          ) : null}
          {lastExecution?.target ? <small>Route: {lastExecution.target}{lastExecution.verification ? " · verificatie" : ""}{lastExecution.route_profile ? ` · ${lastExecution.route_profile}` : ""}</small> : null}
          {lastExecution?.reasoning_profile ? <small>Profiel: {lastExecution.reasoning_profile}</small> : null}
          {lastExecution?.run_id ? (
            <small className="flight-timeline-hook">
              Flight run: <code>{lastExecution.run_id}</code>
              {" · "}
              <a href={`#/mission-control?flight=${encodeURIComponent(lastExecution.run_id)}`}>Timeline in Mission Control</a>
              {" · "}
              <button
                type="button"
                className="linkish"
                onClick={() => {
                  void hadesApi.runEvents(String(lastExecution.run_id)).then((payload) => {
                    setLastExecution((prev) => prev ? {
                      ...prev,
                      live_events: (payload.events || []) as HighLevelExecutionEvent[],
                    } : prev);
                  }).catch(() => undefined);
                }}
              >
                Laad run-events
              </button>
            </small>
          ) : null}
          {lastExecution?.difficulty_router ? (
            <details className="working-state-box" open>
              <summary>Uitvoeringsbeleid</summary>
              <ul className="difficulty-router-list">
                <li>
                  Gekozen: {String(lastExecution.difficulty_router.selected_mode || lastExecution.selected_mode || lastExecution.reasoning_profile || "—")}
                  {" · effectief: "}
                  {String(lastExecution.difficulty_router.effective_policy || lastExecution.effective_policy || lastExecution.difficulty_router.profile || lastExecution.route_profile || "—")}
                </li>
                {lastExecution.difficulty_router.decision_reason || lastExecution.decision_reason ? (
                  <li>Reden: {String(lastExecution.difficulty_router.decision_reason || lastExecution.decision_reason)}</li>
                ) : null}
                <li>
                  Pad: {String(lastExecution.difficulty_router.path || (String(lastExecution.difficulty_router.target || "").includes("direct") ? "direct" : "uitgebreid"))}
                </li>
                {lastExecution.difficulty_router.complexity_total != null ? (
                  <li>Heuristiek (niet gekalibreerd): {String(lastExecution.difficulty_router.complexity_total)}</li>
                ) : null}
                {lastExecution.difficulty_router.target ? (
                  <li>Target: {String(lastExecution.difficulty_router.target)}{lastExecution.difficulty_router.agent_id ? ` · agent ${String(lastExecution.difficulty_router.agent_id)}` : ""}</li>
                ) : null}
                {lastExecution.difficulty_router.rationale ? (
                  <li>{String(lastExecution.difficulty_router.rationale)}</li>
                ) : null}
                {lastExecution.difficulty_router.require_verification != null ? (
                  <li>Verificatie vereist: {lastExecution.difficulty_router.require_verification ? "ja" : "nee"}</li>
                ) : null}
                {lastExecution.difficulty_router.stop_and_ask ? (
                  <li>
                    Stop-and-ask: ja
                    {Array.isArray(lastExecution.difficulty_router.ask_questions) && lastExecution.difficulty_router.ask_questions.length
                      ? ` — ${(lastExecution.difficulty_router.ask_questions as string[]).join(" · ")}`
                      : ""}
                  </li>
                ) : null}
              </ul>
            </details>
          ) : null}
          <VerificationSummary execution={lastExecution} />
          {!lastExecution?.acceptance_checklist?.length && lastExecution?.acceptance?.length ? (
            <details className="working-state-box">
              <summary>Acceptatiecriteria</summary>
              <ul>{lastExecution.acceptance.map((item) => <li key={item}>{item}</li>)}</ul>
            </details>
          ) : null}
          {(Number(lastExecution?.budget?.replans) > 0 || correctionNotes.length > 0) ? (
            <details className="working-state-box" open>
              <summary>Self-correction log</summary>
              <ul>
                {lastExecution?.budget?.replans != null ? (
                  <li>Herplanningen: {String(lastExecution.budget.replans)}/{String(lastExecution.budget.max_replans ?? "?")}</li>
                ) : null}
                {correctionNotes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </details>
          ) : null}
          {lastExecution?.linked_task_id ? <small>Gekoppelde taak: {lastExecution.linked_task_id}</small> : null}
          {lastExecution ? (
            <ChatProvenanceList retrieval={lastExecution.retrieval} compact />
          ) : null}
          {lastExecution?.budget ? (
            <small>
              Budget: {lastExecution.budget.model_calls != null ? String(lastExecution.budget.model_calls) : "—"}/{lastExecution.budget.max_model_calls != null ? String(lastExecution.budget.max_model_calls) : "—"} model
              · {lastExecution.budget.tool_rounds != null ? String(lastExecution.budget.tool_rounds) : "—"}/{lastExecution.budget.max_tool_rounds != null ? String(lastExecution.budget.max_tool_rounds) : "—"} tools
              {lastExecution.budget.replans != null ? ` · ${String(lastExecution.budget.replans)}/${lastExecution.budget.max_replans != null ? String(lastExecution.budget.max_replans) : "—"} replans` : ""}
              {lastExecution.budget.stop_reason ? ` · stop: ${String(lastExecution.budget.stop_reason)}` : ""}
              {lastExecution.budget.usage_kind ? ` · tokens: ${String(lastExecution.budget.usage_kind)}` : ""}
            </small>
          ) : null}
          <ExecutionTrace execution={lastExecution} running={sending} />
          <ToolResultCards cards={lastExecution?.tool_cards} />
          {lastExecution?.working_state ? (
            <details className="working-state-box">
              <summary>Working state</summary>
              <pre>{JSON.stringify(lastExecution.working_state, null, 2).slice(0, 2500)}</pre>
            </details>
          ) : null}
        </Panel>
      </aside>
    </div>
  );
}