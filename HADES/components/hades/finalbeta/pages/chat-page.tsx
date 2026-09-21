"use client";

import {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  MentionAutocompleteList,
  useMentionAutocomplete,
  type MentionSuggestion,
} from "@/components/hades/chat-mention-autocomplete";
import { ChatProvenanceList } from "@/components/hades/chat-provenance";
import { ExecutionCompletionBanner } from "@/components/hades/execution-completion-banner";
import { ApprovalCard, WorkCard } from "@/components/hades/features/chat/ApprovalWorkCards";
import { ChatDoctorBanner } from "@/components/hades/features/chat/ChatDoctorBanner";
import { CodingCard } from "@/components/hades/features/chat/CodingCard";
import { ContextTurnPanel } from "@/components/hades/features/chat/ContextTurnPanel";
import { ExecutionTrace } from "@/components/hades/features/chat/ExecutionTrace";
import { ResearchCard } from "@/components/hades/features/chat/ResearchCard";
import { VerificationSummary } from "@/components/hades/features/chat/VerificationSummary";
import { ModelUsageCard } from "@/components/hades/model-usage-card";
import { ResultsPanel } from "@/components/hades/results-panel";
import { ToolResultCards } from "@/components/hades/tool-result-cards";
import {
  VoiceComposerControls,
  VoiceMessageActions,
  VoicePanel,
  VoiceSetupWizard,
  isVoiceSetupDone,
} from "@/components/hades/voice";
import { assessChatCompletion } from "@/lib/execution-completion";
import { writeCodingHandoff } from "@/lib/chat-handoff";
import { hadesSpeechPlayer } from "@/lib/hades-speech";
import { REASONING_MODE_OPTIONS, type ProductReasoningMode } from "@/lib/reasoning-mode";
import { shortModelName } from "../hooks/dashboard-live-utils";
import { conversationListTime, useChatLive } from "../hooks/use-chat-live";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };
type InspTab = "context" | "runtime" | "more";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function InspFold({
  id,
  title,
  open,
  onToggle,
  children,
}: {
  id: string;
  title: string;
  open: boolean;
  onToggle: (id: string) => void;
  children: ReactNode;
}) {
  return (
    <section className="insp-section">
      <button
        type="button"
        className="insp-title insp-fold-toggle"
        aria-expanded={open}
        onClick={() => onToggle(id)}
      >
        <span>{title}</span>
        <span className="muted" aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>
      {open ? children : null}
    </section>
  );
}

export function ChatPage({ onNavigate }: Props) {
  const chat = useChatLive();
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const stickToBottom = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const [inspTab, setInspTab] = useState<InspTab>("context");
  const [openFolds, setOpenFolds] = useState<Record<string, boolean>>({
    context: true,
    runtime: true,
    usage: false,
    budget: false,
    pins: true,
    linked: false,
    canvas: false,
    voice: false,
    actions: true,
    results: false,
    branches: true,
  });
  const [pinDraft, setPinDraft] = useState("");
  const [showVoiceSetup, setShowVoiceSetup] = useState(false);
  const [runtimeOpen, setRuntimeOpen] = useState(true);

  const mention = useMentionAutocomplete(chat.draft, chat.draftCursor);

  const modelLabel = shortModelName(chat.modelId || chat.health?.active_model);
  const backendOk = chat.health?.backend === "ok";
  const lmConnected = chat.health?.lm_studio === "connected" || chat.modelConnected;
  const lmHasModel = Boolean(chat.health?.active_model || chat.modelId);

  const connectionStatus = useMemo(() => {
    if (!chat.health && chat.loading) return { label: "Laden…", className: "v", tag: "Laden" };
    if (!backendOk) return { label: "Backend offline", className: "v", tag: "Backend offline" };
    if (!lmConnected) return { label: "Backend · LM offline", className: "v", tag: "LM offline" };
    if (!lmHasModel) return { label: "Backend · LM zonder model", className: "v", tag: "Geen model" };
    if (chat.sending) return { label: "Backend · LM · bezig", className: "v green", tag: "Bezig" };
    return { label: "Backend · LM online", className: "v green", tag: "Online" };
  }, [chat.health, chat.loading, backendOk, lmConnected, lmHasModel, chat.sending]);

  const subtitle = useMemo(() => {
    const count = chat.messages.length;
    const countLabel = `${count} bericht${count === 1 ? "" : "en"}`;
    const modelPart = modelLabel !== "—" ? modelLabel : "Lokaal model";
    return `${countLabel} · ${modelPart} · ${chat.reasoningLabel}`;
  }, [chat.messages.length, modelLabel, chat.reasoningLabel]);

  const chatCompletion = useMemo(
    () =>
      assessChatCompletion({
        status: chat.lastExecution?.status,
        verification_called: chat.lastExecution?.verification,
        route: chat.lastExecution?.route,
        executed_route: chat.lastExecution?.executed_route,
        reasoning_profile: chat.lastExecution?.reasoning_profile,
        verification_notes: chat.lastExecution?.verification_notes,
        acceptance_checklist: chat.lastExecution?.acceptance_checklist as Array<Record<string, unknown>> | undefined,
      }),
    [chat.lastExecution],
  );

  const budgetMeta = useMemo(() => {
    const retrieval = chat.lastExecution?.retrieval;
    const compiler = asRecord(retrieval?.context_compiler);
    const budget = asRecord(retrieval?.context_budget);
    const used =
      typeof budget?.used_tokens === "number"
        ? budget.used_tokens
        : typeof compiler?.used_tokens === "number"
          ? compiler.used_tokens
          : null;
    const max =
      typeof budget?.max_tokens === "number"
        ? budget.max_tokens
        : typeof compiler?.max_tokens === "number"
          ? compiler.max_tokens
          : null;
    const dropReasons = [
      ...((Array.isArray(compiler?.drop_reasons) ? compiler?.drop_reasons : []) as unknown[]),
      ...((Array.isArray(budget?.drop_events)
        ? (budget?.drop_events as Array<Record<string, unknown>>).map((row) => row.drop_reason)
        : []) as unknown[]),
    ]
      .map((item) => String(item || "").trim())
      .filter(Boolean);
    return {
      used,
      max,
      drops: Array.from(new Set(dropReasons)),
      linked: chat.lastExecution?.linked_runs || [],
      toolRounds: chat.chatTelemetry.toolRounds ?? null,
      maxToolRounds: chat.chatTelemetry.maxToolRounds ?? null,
    };
  }, [chat.lastExecution, chat.chatTelemetry]);

  const doctorHasIssues = chat.chatDoctor.state.kind !== "ok" && chat.chatDoctor.state.kind !== "lexical_only";
  const showRuntimeStrip = Boolean(
    chat.pendingApprovals.length
    || chat.workCards.length
    || chat.codingCards.length
    || chat.researchCards.length
    || chat.lastExecution
    || chatCompletion,
  );

  const visibleMessages = useMemo(
    () => chat.messages.filter((message) => message.role === "user" || message.role === "assistant"),
    [chat.messages],
  );

  const toggleFold = useCallback((id: string) => {
    setOpenFolds((current) => ({ ...current, [id]: !current[id] }));
  }, []);

  const onMessagesScroll = useCallback(() => {
    const el = messagesRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = distance < 72;
  }, []);

  useEffect(() => {
    if (!stickToBottom.current) return;
    const el = messagesRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [visibleMessages.length, chat.streamText, chat.sending, chat.error]);

  const applyMention = useCallback(
    (item: MentionSuggestion) => {
      const applied = mention.applySuggestion(item, chat.draft, chat.draftCursor);
      chat.setDraft(applied.next, applied.nextCursor);
      window.setTimeout(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(applied.nextCursor, applied.nextCursor);
      }, 0);
    },
    [mention, chat],
  );

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
      if (!chat.sending) void chat.sendMessage();
    }
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (chat.sending) {
      void chat.cancelGeneration();
      return;
    }
    void chat.sendMessage();
  };

  const confirmDelete = () => {
    if (!chat.selectedId) return;
    const title = chat.selected?.title || "dit gesprek";
    if (!window.confirm(`Gesprek “${title}” verwijderen inclusief gekoppeld geheugen?`)) return;
    void chat.deleteConversation();
  };

  const stopSpeaking = () => {
    chat.playback.stop();
    void chat.voiceSession.interrupt();
    void hadesSpeechPlayer.stop().catch(() => undefined);
  };

  const pinAccepted = chat.pinBundle?.accepted || [];

  const body = (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Chatten</h1>
          <p className="page-sub">Chat-first werkruimte met context, tools en lokale modellen.</p>
        </div>
        <div className="page-actions">
          <button
            className="btn btn-outline"
            type="button"
            onClick={() => void chat.refresh()}
            disabled={chat.loading}
          >
            Refresh
          </button>
          <button
            className="btn btn-gold"
            type="button"
            onClick={() => void chat.createConversation()}
            disabled={chat.loading}
          >
            + Nieuw gesprek
          </button>
        </div>
      </div>

      {doctorHasIssues ? (
        <ChatDoctorBanner
          health={chat.health || chat.chatDoctor.health}
          settings={chat.chatDoctor.settings}
          onRetry={() => {
            chat.chatDoctor.refresh();
            void chat.refresh();
          }}
        />
      ) : null}

      <div className="chat-layout">
        <section className="card" style={{ padding: 10, overflow: "auto" }}>
          <div className="search-bar" style={{ marginBottom: 10 }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-4-4" />
            </svg>
            <input
              placeholder="Gesprekken zoeken..."
              value={chat.searchQuery}
              onChange={(event) => chat.setSearchQuery(event.target.value)}
              aria-label="Gesprekken zoeken"
            />
          </div>
          {chat.loading && !chat.filteredConversations.length ? (
            <div className="list-row">
              <div className="grow">
                <strong>Laden…</strong>
                <div className="muted" style={{ fontSize: 10 }}>Gesprekken ophalen</div>
              </div>
            </div>
          ) : null}
          {!chat.loading && !chat.filteredConversations.length ? (
            <div className="list-row">
              <div className="grow">
                <strong>Geen gesprekken</strong>
                <div className="muted" style={{ fontSize: 10 }}>
                  {chat.searchQuery.trim() ? "Geen treffers" : "Maak een nieuw gesprek"}
                </div>
              </div>
            </div>
          ) : null}
          {chat.filteredConversations.map((item) => {
            const active = item.id === chat.selectedId;
            return (
              <div
                key={item.id}
                className="list-row"
                role="button"
                tabIndex={0}
                onClick={() => chat.selectConversation(item.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    chat.selectConversation(item.id);
                  }
                }}
                style={
                  active
                    ? {
                        borderRadius: 6,
                        background: "rgba(240,180,41,.08)",
                        border: "1px solid rgba(240,180,41,.25)",
                        cursor: "pointer",
                      }
                    : { cursor: "pointer" }
                }
              >
                <div className="grow">
                  <strong>{item.title || "Nieuw gesprek"}</strong>
                  <div className="muted" style={{ fontSize: 10 }}>
                    {conversationListTime(item.updated_at)}
                  </div>
                </div>
              </div>
            );
          })}
        </section>

        <section className="card chat-thread">
          <div className="chat-thread-head">
            <div className="chat-thread-title">
              <input
                className="chat-title-input"
                value={chat.titleDraft}
                onChange={(event) => chat.setTitleDraft(event.target.value)}
                onBlur={() => {
                  if (!chat.selectedId) return;
                  if ((chat.selected?.title || "") === chat.titleDraft.trim()) return;
                  void chat.renameConversation();
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    (event.target as HTMLInputElement).blur();
                  }
                }}
                placeholder={chat.loading ? "Laden…" : "Gesprekstitel"}
                aria-label="Gesprekstitel hernoemen"
                disabled={!chat.selectedId}
              />
              <div className="muted" style={{ fontSize: 11 }}>{subtitle}</div>
            </div>
            <div className="chat-thread-controls">
              <select
                className="chat-select"
                value={chat.modelId || ""}
                onChange={(event) => void chat.changeModel(event.target.value)}
                aria-label="Model"
                disabled={!chat.models.length}
              >
                {!chat.models.length ? <option value="">Geen model</option> : null}
                {chat.models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {shortModelName(model.id)}
                  </option>
                ))}
              </select>
              <select
                className="chat-select"
                value={chat.reasoningMode}
                onChange={(event) => void chat.changeReasoningMode(event.target.value as ProductReasoningMode)}
                aria-label="Denkmodus"
                disabled={!chat.reasoningReady || chat.reasoningSaving}
              >
                {REASONING_MODE_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id} title={option.hint}>
                    {option.label}
                  </option>
                ))}
              </select>
              <span className={`tag ${connectionStatus.tag === "Online" || connectionStatus.tag === "Bezig" ? "green" : ""}`}>
                {connectionStatus.tag}
              </span>
              <button
                className="btn btn-sm btn-outline"
                type="button"
                disabled={!chat.selectedId}
                onClick={confirmDelete}
              >
                Verwijder
              </button>
            </div>
          </div>

          {(chat.branches.length > 0 || chat.branchesLoading || chat.branchesError) ? (
            <div className="chat-branch-bar">
              <span className="muted">
                {chat.branchesLoading
                  ? "Vertakkingen laden…"
                  : chat.activeBranch
                    ? `Branch: ${chat.activeBranch.title}`
                    : "Hoofdlijn"}
              </span>
              {chat.branchesError ? <span className="chat-inline-error">{chat.branchesError}</span> : null}
              <div className="chat-branch-actions">
                {chat.branches.filter((branch) => !branch.is_active).slice(0, 4).map((branch) => (
                  <button
                    key={branch.id}
                    type="button"
                    className="btn btn-sm btn-outline"
                    disabled={chat.branchActivatingId === branch.id}
                    onClick={() => void chat.activateBranch(branch.id)}
                  >
                    {chat.branchActivatingId === branch.id ? "…" : branch.title}
                  </button>
                ))}
                {chat.compareReady ? (
                  <button
                    type="button"
                    className={`btn btn-sm ${chat.compareMode ? "btn-gold" : "btn-outline"}`}
                    onClick={() => chat.setCompareMode(!chat.compareMode)}
                  >
                    Vergelijk
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {chat.compareMode && chat.compareReady ? (
            <div className="chat-compare-panel">
              <div className="chat-compare-picks">
                <select
                  className="chat-select"
                  value={chat.compareLeftId}
                  onChange={(event) => chat.setCompareLeftId(event.target.value)}
                  aria-label="Linker vertakking"
                >
                  {chat.branches.map((branch) => (
                    <option key={`left-${branch.id}`} value={branch.id}>{branch.title}</option>
                  ))}
                </select>
                <select
                  className="chat-select"
                  value={chat.compareRightId}
                  onChange={(event) => chat.setCompareRightId(event.target.value)}
                  aria-label="Rechter vertakking"
                >
                  {chat.branches.map((branch) => (
                    <option key={`right-${branch.id}`} value={branch.id}>{branch.title}</option>
                  ))}
                </select>
              </div>
              {chat.compareLoading ? <div className="muted">Vergelijken…</div> : null}
              <div className="chat-compare-sides">
                {chat.compareSides.map((side, index) => (
                  <div key={index} className="chat-compare-side">
                    <strong>{side?.title || "—"}</strong>
                    <pre>{side?.empty ? "(leeg)" : (side?.text || "")}</pre>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="messages" ref={messagesRef} onScroll={onMessagesScroll}>
            {chat.messagesLoading && !visibleMessages.length ? (
              <div className="bubble muted">Berichten laden…</div>
            ) : null}
            {!chat.messagesLoading && !visibleMessages.length && !chat.sending ? (
              <div className="bubble muted">Nog geen berichten. Stuur een bericht om te beginnen.</div>
            ) : null}
            {visibleMessages.map((message) => {
              const speakingThis =
                chat.speechState.speaking && chat.speechState.messageId === message.id;
              return (
                <div key={message.id} className="chat-msg">
                  <div className={`bubble${message.role === "user" ? " user" : ""}`}>
                    {message.content}
                  </div>
                  <div className="chat-msg-actions">
                    <button type="button" className="btn btn-sm btn-ghost" onClick={() => void chat.copyMessage(message)}>
                      {chat.copiedId === message.id ? "Gekopieerd" : "Kopieer"}
                    </button>
                    {message.role === "user" ? (
                      <button type="button" className="btn btn-sm btn-ghost" disabled={chat.sending} onClick={() => void chat.reviseMessage(message)}>
                        Herzien
                      </button>
                    ) : (
                      <button type="button" className="btn btn-sm btn-ghost" disabled={chat.sending} onClick={() => void chat.regenerateMessage(message)}>
                        Opnieuw
                      </button>
                    )}
                    <button type="button" className="btn btn-sm btn-ghost" disabled={chat.sending} onClick={() => void chat.branchFromMessage(message)}>
                      Vertak
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      disabled={chat.sending}
                      onClick={() => {
                        if (speakingThis) stopSpeaking();
                        else void chat.speakMessage(message);
                      }}
                    >
                      {speakingThis ? "Stop" : "Spreek"}
                    </button>
                    {chat.voiceEnabled && message.role === "assistant" ? (
                      <VoiceMessageActions
                        speaking={chat.playback.speaking || chat.voiceSession.audioPlaying}
                        isCurrentMessage={
                          chat.playback.messageId === message.id
                          || (Boolean(chat.lastSpokenAnswer) && chat.lastSpokenAnswer === message.content && chat.voiceSession.audioPlaying)
                        }
                        disabled={chat.sending}
                        onReplay={() => {
                          if (chat.voiceSession.state.sessionId) {
                            void chat.voiceSession.speakAssistantResponse(message.content, message.id, { forceReplay: true });
                          } else if (chat.ttsProvider === "voicestudio") {
                            void chat.speakMessage(message);
                          } else {
                            void chat.playback.replay();
                          }
                        }}
                        onStop={stopSpeaking}
                      />
                    ) : null}
                  </div>
                </div>
              );
            })}
            {chat.sending && chat.streamText ? <div className="bubble">{chat.streamText}</div> : null}
            {chat.sending && !chat.streamText ? <div className="bubble muted">Genereren…</div> : null}
            {chat.error ? (
              <div className="bubble" style={{ borderColor: "rgba(232,91,91,.45)" }}>
                {chat.error}
              </div>
            ) : null}
          </div>

          {showRuntimeStrip ? (
            <div className="chat-runtime-panel">
              <button
                type="button"
                className="chat-runtime-toggle"
                aria-expanded={runtimeOpen}
                onClick={() => setRuntimeOpen((open) => !open)}
              >
                Runtime {runtimeOpen ? "▾" : "▸"}
              </button>
              {runtimeOpen ? (
                <div className="chat-runtime-body">
                  <ExecutionCompletionBanner assessment={chatCompletion} />
                  {chat.pendingApprovals.length ? (
                    <div className="chat-runtime-block" aria-label="Goedkeuringen">
                      {chat.pendingApprovals.slice(0, 5).map((item) => (
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
                          busy={chat.approvalBusy === String(item.id)}
                          onApprove={() => void chat.decideApproval(String(item.id), true)}
                          onReject={() => void chat.decideApproval(String(item.id), false)}
                        />
                      ))}
                    </div>
                  ) : null}
                  {chat.workCards.length ? (
                    <div className="chat-runtime-block" aria-label="Work Runtime">
                      {chat.workCards.map((work) => (
                        <WorkCard key={work.task_id} work={work} onOpenAdvanced={() => onNavigate("tasks")} />
                      ))}
                    </div>
                  ) : null}
                  {chat.codingCards.length ? (
                    <div className="chat-runtime-block" aria-label="Coding">
                      {chat.codingCards.map((job) => (
                        <CodingCard
                          key={job.job_id}
                          job={job}
                          busy={chat.codingBusy}
                          onOpenAdvanced={() => {
                            window.location.hash = `/fb/coding?codingJob=${encodeURIComponent(job.job_id)}`;
                          }}
                          onRefresh={() => void chat.refreshCodingJob(job.job_id)}
                          onApplyAll={() => void chat.applyCodingJob(job.job_id)}
                          onReject={() => void chat.rejectCodingJob(job.job_id)}
                        />
                      ))}
                    </div>
                  ) : null}
                  {chat.researchCards.length ? (
                    <div className="chat-runtime-block" aria-label="Research">
                      {chat.researchCards.map((research) => (
                        <ResearchCard
                          key={research.project_id}
                          research={research}
                          busy={chat.researchBusy}
                          onOpenAdvanced={() => onNavigate("research")}
                          onRefresh={() => void chat.refreshResearch(research.project_id)}
                          onStop={() => void chat.stopResearch(research.project_id)}
                          onGoDeeper={() => void chat.goDeeperResearch(research.project_id)}
                        />
                      ))}
                    </div>
                  ) : null}
                  <ContextTurnPanel retrieval={chat.lastExecution?.retrieval} />
                  <VerificationSummary execution={chat.lastExecution} />
                  <ExecutionTrace execution={chat.lastExecution} running={chat.sending} />
                  {chat.lastExecution?.run_id ? (
                    <div className="chat-runtime-actions">
                      <button
                        type="button"
                        className="btn btn-sm btn-outline"
                        onClick={() => void chat.loadRunEvents(String(chat.lastExecution?.run_id))}
                      >
                        Laad run-events
                      </button>
                    </div>
                  ) : null}
                  <ToolResultCards cards={chat.lastExecution?.tool_cards} />
                  {chat.lastExecution?.retrieval ? (
                    <ChatProvenanceList retrieval={chat.lastExecution.retrieval} compact />
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="chat-pins-compact" aria-label="Gesprekspins">
            <div className="chat-pins-compact-row">
              <button
                type="button"
                className="btn btn-sm btn-outline"
                disabled={chat.pinsBusy || !chat.selectedId}
                onClick={() => void chat.pickPinFolder()}
              >
                Map pinnen
              </button>
              <input
                className="chat-pin-input"
                value={pinDraft}
                placeholder="Pad plakken…"
                aria-label="Pad om te pinnen"
                disabled={chat.pinsBusy || !chat.selectedId}
                onChange={(event) => setPinDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && pinDraft.trim()) {
                    event.preventDefault();
                    void chat.addPinPath(pinDraft.trim());
                    setPinDraft("");
                  }
                }}
              />
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={chat.pinsBusy || !chat.selectedId || !pinDraft.trim()}
                onClick={() => {
                  if (!pinDraft.trim()) return;
                  void chat.addPinPath(pinDraft.trim());
                  setPinDraft("");
                }}
              >
                +
              </button>
            </div>
            {chat.pinBundle?.summary ? (
              <small className="muted">
                {chat.pinBundle.summary.indexed} idx · {chat.pinBundle.summary.stale} stale · {chat.pinBundle.summary.skipped} skip
              </small>
            ) : (
              <small className="muted">Geen pins</small>
            )}
            {pinAccepted.length ? (
              <div className="chat-pin-chips">
                {pinAccepted.map((item) => {
                  const path = String(item.path || "");
                  const status = String(item.status || "indexed");
                  return (
                    <span key={path} className="chat-attach-chip" title={path}>
                      <span>{path.split(/[/\\]/).slice(-2).join("/") || path}</span>
                      <small className="muted">{status}</small>
                      <button type="button" aria-label={`Pin ${path} verwijderen`} onClick={() => void chat.removePinPath(path)}>
                        ×
                      </button>
                    </span>
                  );
                })}
              </div>
            ) : null}
          </div>

          {chat.voiceEnabled && showVoiceSetup ? (
            <div className="chat-voice-inline">
              <VoiceSetupWizard
                open={showVoiceSetup}
                onComplete={() => {
                  setShowVoiceSetup(false);
                  chat.chatDoctor.refresh();
                }}
                onClose={() => setShowVoiceSetup(false)}
              />
            </div>
          ) : null}

          {chat.voiceEnabled && chat.voiceSession.state.sessionId ? (
            <VoicePanel
              status={chat.voiceSession.status}
              level={chat.voiceSession.level}
              micActive={chat.voiceSession.micActive}
              modelGenerating={chat.voiceSession.modelGenerating}
              audioPlaying={chat.voiceSession.audioPlaying}
              transcript={chat.voiceSession.state.lastTranscript || chat.dictation.partialText}
              lastAnswer={chat.lastSpokenAnswer}
              error={chat.voiceSession.state.lastError}
              muted={chat.voiceSession.state.micState === "muted"}
              outputMuted={chat.voiceSession.outputMuted}
              turnMode={chat.voiceSession.turnMode}
              lastInterruptLatencyMs={chat.voiceSession.lastInterruptLatencyMs}
              onToggleMute={() => chat.voiceSession.setMicMuted(chat.voiceSession.state.micState !== "muted")}
              onToggleOutputMute={() => chat.voiceSession.setOutputMuted(!chat.voiceSession.outputMuted)}
              onHoldPushToTalk={(down) => chat.voiceSession.holdPushToTalk(down)}
              onInterrupt={() => void chat.voiceSession.interrupt()}
              onStop={() => void chat.voiceSession.stopSession()}
            />
          ) : null}

          {chat.attachmentReport.length ? (
            <div className="chat-attach-report">
              {chat.attachmentReport.map((item) => (
                <small key={String(item.id)} className="muted">
                  {String(item.filename)}: {String(item.extract_status)}
                  {item.used_in_context ? " · gelezen" : " · niet in context"}
                </small>
              ))}
            </div>
          ) : null}

          <form className="composer" onSubmit={onSubmit}>
            <div className="composer-main">
              {chat.attachments.length ? (
                <div className="chat-attach-chips">
                  {chat.attachments.map((item) => (
                    <span key={item.artifact_id} className="chat-attach-chip">
                      <span>{item.filename}</span>
                      <button type="button" aria-label={`${item.filename} verwijderen`} onClick={() => chat.removeAttachment(item.artifact_id)}>
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="composer-input-row">
                <textarea
                  ref={textareaRef}
                  placeholder="Stuur een bericht… (Enter = verstuur, Shift+Enter = nieuwe regel)"
                  value={chat.draft}
                  rows={2}
                  onChange={(event) => {
                    const el = event.target;
                    chat.setDraft(el.value, el.selectionStart ?? el.value.length);
                  }}
                  onSelect={(event) => {
                    const el = event.currentTarget;
                    chat.setDraftCursor(el.selectionStart ?? el.value.length);
                  }}
                  onKeyDown={onComposerKeyDown}
                  disabled={chat.loading}
                  aria-label="Bericht"
                />
                <MentionAutocompleteList
                  open={mention.open}
                  items={mention.items}
                  loading={mention.loading}
                  error={mention.error}
                  activeIndex={mention.activeIndex}
                  onPick={applyMention}
                  onHover={mention.setActiveIndex}
                />
              </div>
              <div className="composer-toolbar">
                <input
                  ref={fileRef}
                  type="file"
                  multiple
                  hidden
                  onChange={(event) => {
                    const files = Array.from(event.target.files || []);
                    event.target.value = "";
                    if (files.length) void chat.addFiles(files);
                  }}
                />
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  disabled={!chat.selectedId || chat.sending}
                  onClick={() => fileRef.current?.click()}
                >
                  Bijlage
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${chat.micRecording ? "btn-gold" : "btn-outline"}`}
                  disabled={!chat.selectedId || chat.sending}
                  aria-pressed={chat.micRecording}
                  onClick={() => void chat.toggleMic()}
                >
                  {chat.micRecording ? "Mic aan" : "Mic"}
                </button>
                {chat.voiceEnabled ? (
                  <VoiceComposerControls
                    dictationActive={chat.dictation.listening}
                    dictationLevel={chat.dictation.level}
                    sessionActive={Boolean(chat.voiceSession.state.sessionId)}
                    speaking={chat.playback.speaking || chat.voiceSession.audioPlaying}
                    disabled={chat.sending}
                    error={chat.dictation.error || chat.voiceSession.state.lastError}
                    onToggleDictation={() => void chat.dictation.toggle()}
                    onStartConversation={() => {
                      if (!isVoiceSetupDone()) {
                        setShowVoiceSetup(true);
                        return;
                      }
                      void chat.voiceSession.startSession();
                    }}
                    onStopConversation={() => void chat.voiceSession.stopSession()}
                    onHoldPushToTalk={(down) => {
                      if (chat.voiceSession.state.sessionId) chat.voiceSession.holdPushToTalk(down);
                      else chat.dictation.holdPushToTalk(down);
                    }}
                    onStopSpeaking={stopSpeaking}
                  />
                ) : null}
                <span className="composer-spacer" />
                <button
                  className="btn btn-gold"
                  type="submit"
                  disabled={chat.loading || (!chat.sending && !chat.draft.trim() && !chat.attachments.length)}
                >
                  {chat.sending ? "Stop" : "Verstuur"}
                </button>
              </div>
            </div>
          </form>
        </section>
      </div>
    </>
  );

  const inspector = (
    <>
      <p className="quote">
        “Sovereign AI. Local power.
        <br />
        Infinite possibilities.”
      </p>
      <div style={{ marginBottom: 10 }}>
        <span className="badge-outline">CHAT</span>
      </div>

      <div className="insp-tabs" role="tablist" aria-label="Inspector">
        {([
          ["context", "Context"],
          ["runtime", "Runtime"],
          ["more", "Meer"],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={inspTab === id}
            className={`insp-tab${inspTab === id ? " active" : ""}`}
            onClick={() => setInspTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {inspTab === "context" ? (
        <>
          <InspFold id="context" title="Context" open={Boolean(openFolds.context)} onToggle={toggleFold}>
            <div className="insp-card">
              <div className="detail-row">
                <span className="k">Status</span>
                <span className={connectionStatus.className}>{connectionStatus.label}</span>
              </div>
              <div className="detail-row">
                <span className="k">Backend</span>
                <span className={`v ${backendOk ? "green" : ""}`}>{backendOk ? "ok" : (chat.health?.backend || "—")}</span>
              </div>
              <div className="detail-row">
                <span className="k">LM Studio</span>
                <span className={`v ${lmConnected ? "green" : ""}`}>
                  {lmConnected ? (lmHasModel ? "connected" : "geen model") : (chat.health?.lm_studio || "offline")}
                </span>
              </div>
              <div className="detail-row">
                <span className="k">Host</span>
                <span className="v">{chat.hostname || "—"}</span>
              </div>
              <div className="detail-row">
                <span className="k">Model</span>
                <span className="v">{modelLabel}</span>
              </div>
              <div className="detail-row">
                <span className="k">Denkmodus</span>
                <span className="v">{chat.reasoningLabel}{chat.reasoningSaving ? "…" : ""}</span>
              </div>
            </div>
          </InspFold>

          <InspFold id="usage" title="Model usage" open={Boolean(openFolds.usage)} onToggle={toggleFold}>
            <div className="insp-card">
              <ModelUsageCard
                models={chat.models}
                modelId={chat.modelId}
                onModelChange={(next) => void chat.changeModel(next)}
                usage={chat.modelUsage}
                telemetry={chat.chatTelemetry}
              />
            </div>
          </InspFold>

          <InspFold id="budget" title="Context budget / drops" open={Boolean(openFolds.budget)} onToggle={toggleFold}>
            <div className="insp-card">
              <div className="detail-row">
                <span className="k">Tokens</span>
                <span className="v">
                  {budgetMeta.used != null || budgetMeta.max != null
                    ? `${budgetMeta.used ?? "—"} / ${budgetMeta.max ?? "—"}`
                    : "—"}
                </span>
              </div>
              <div className="detail-row">
                <span className="k">Tool rounds</span>
                <span className="v">
                  {budgetMeta.toolRounds != null || budgetMeta.maxToolRounds != null
                    ? `${budgetMeta.toolRounds ?? "—"} / ${budgetMeta.maxToolRounds ?? "—"}`
                    : "—"}
                </span>
              </div>
              <div className="detail-row">
                <span className="k">Wall</span>
                <span className="v">{chat.runWallMs != null ? `${Math.round(chat.runWallMs)} ms` : "—"}</span>
              </div>
              {budgetMeta.drops.length ? (
                <ul className="insp-drop-list">
                  {budgetMeta.drops.slice(0, 8).map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted" style={{ fontSize: 11, margin: "8px 0 0" }}>Geen drop-redenen voor deze beurt.</p>
              )}
            </div>
          </InspFold>
        </>
      ) : null}

      {inspTab === "runtime" ? (
        <>
          <InspFold id="runtime" title="Runtime" open={Boolean(openFolds.runtime)} onToggle={toggleFold}>
            <div className="insp-card">
              <div className="detail-row">
                <span className="k">Status</span>
                <span className="v">{chat.lastExecution?.status || (chat.sending ? "running" : "idle")}</span>
              </div>
              <div className="detail-row">
                <span className="k">Route</span>
                <span className="v">{chat.lastExecution?.target || chat.lastExecution?.route_profile || "—"}</span>
              </div>
              <div className="detail-row">
                <span className="k">Verificatie</span>
                <span className="v">
                  {chat.lastExecution?.verification == null
                    ? "—"
                    : chat.lastExecution.verification
                      ? "aangeroepen"
                      : "niet"}
                </span>
              </div>
              <div className="detail-row">
                <span className="k">Tools</span>
                <span className="v">{chat.lastExecution?.tools?.length ?? 0}</span>
              </div>
              <div className="detail-row">
                <span className="k">Wall</span>
                <span className="v">{chat.runWallMs != null ? `${Math.round(chat.runWallMs)} ms` : "—"}</span>
              </div>
            </div>
          </InspFold>

          <InspFold id="pins" title="Pins" open={Boolean(openFolds.pins)} onToggle={toggleFold}>
            <div className="insp-card">
              {pinAccepted.length ? (
                <ul className="insp-drop-list">
                  {pinAccepted.map((item) => (
                    <li key={String(item.path)}>{String(item.path)}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted" style={{ fontSize: 11 }}>Geen pins in dit gesprek.</p>
              )}
            </div>
          </InspFold>

          <InspFold id="linked" title="Linked runs" open={Boolean(openFolds.linked)} onToggle={toggleFold}>
            <div className="insp-card">
              {budgetMeta.linked.length ? (
                <ul className="insp-drop-list">
                  {budgetMeta.linked.map((run) => (
                    <li key={run.id}>
                      {run.run_type}: {run.run_id}
                      {run.status ? ` · ${run.status}` : ""}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted" style={{ fontSize: 11 }}>Geen gekoppelde runs.</p>
              )}
              {chat.lastExecution?.linked_task_id ? (
                <div className="detail-row" style={{ marginTop: 8 }}>
                  <span className="k">Task</span>
                  <span className="v">{chat.lastExecution.linked_task_id}</span>
                </div>
              ) : null}
            </div>
          </InspFold>

          <InspFold id="branches" title="Branches" open={Boolean(openFolds.branches)} onToggle={toggleFold}>
            <div className="insp-card">
              {chat.branchesLoading ? <p className="muted" style={{ fontSize: 11 }}>Laden…</p> : null}
              {chat.branchesError ? <p className="chat-inline-error">{chat.branchesError}</p> : null}
              {!chat.branchesLoading && !chat.branches.length ? (
                <p className="muted" style={{ fontSize: 11 }}>Geen vertakkingen.</p>
              ) : null}
              {chat.branches.map((branch) => (
                <div key={branch.id} className="detail-row">
                  <span className="k">{branch.is_active ? "Actief" : "Branch"}</span>
                  <span className="v">
                    {branch.title}
                    {!branch.is_active ? (
                      <>
                        {" "}
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          disabled={chat.branchActivatingId === branch.id}
                          onClick={() => void chat.activateBranch(branch.id)}
                        >
                          Activeer
                        </button>
                      </>
                    ) : null}
                  </span>
                </div>
              ))}
            </div>
          </InspFold>

          <InspFold id="canvas" title="Canvas / scratchpad" open={Boolean(openFolds.canvas)} onToggle={toggleFold}>
            <div className="insp-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div className="page-actions" style={{ justifyContent: "flex-start" }}>
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  onClick={() => chat.setCanvasOpen(!chat.canvasOpen)}
                >
                  {chat.canvasOpen ? "Inklappen" : "Uitklappen"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-gold"
                  disabled={chat.canvasSaving || !chat.selectedId}
                  onClick={() => void chat.saveCanvas()}
                >
                  {chat.canvasSaving ? "Opslaan…" : "Opslaan"}
                </button>
              </div>
              {chat.canvasLoading ? <p className="muted" style={{ fontSize: 11 }}>Canvas laden…</p> : null}
              {chat.canvasError ? <p className="chat-inline-error">{chat.canvasError}</p> : null}
              {chat.canvasOpen && !chat.canvasLoading ? (
                <textarea
                  className="chat-canvas-editor"
                  value={chat.canvasContent}
                  onChange={(event) => chat.setCanvasContent(event.target.value)}
                  placeholder="Lang antwoord, outline of notities naast de chat."
                  aria-label="Canvas scratchpad"
                  rows={8}
                />
              ) : null}
              {!chat.canvasOpen ? (
                <p className="muted" style={{ fontSize: 11 }}>
                  {chat.canvasError
                    ? "Canvas niet geladen — zie fout hierboven."
                    : chat.canvasContent.trim()
                      ? "Ingeklapt — bevat tekst."
                      : "Ingeklapt — nog leeg."}
                </p>
              ) : null}
              <small className="muted">
                {chat.canvasArtifactId
                  ? `Versie: ${chat.canvasArtifactId.slice(0, 10)}…`
                  : "Nog geen opgeslagen canvas."}
                {chat.canvasDirty ? " · niet opgeslagen" : ""}
              </small>
            </div>
          </InspFold>
        </>
      ) : null}

      {inspTab === "more" ? (
        <>
          <InspFold id="voice" title="Voice" open={Boolean(openFolds.voice)} onToggle={toggleFold}>
            <div className="insp-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <label className="detail-row" style={{ cursor: "pointer" }}>
                <span className="k">Gesproken antwoorden</span>
                <input
                  type="checkbox"
                  checked={chat.spokenAnswers}
                  onChange={(event) => void chat.toggleSpokenAnswers(event.target.checked)}
                />
              </label>
              <div className="detail-row">
                <span className="k">Sessie</span>
                <span className="v">{chat.voiceSession.state.sessionId ? chat.voiceSession.status : "uit"}</span>
              </div>
              <div className="detail-row">
                <span className="k">STT / TTS</span>
                <span className="v">{chat.sttProvider} / {chat.ttsProvider}</span>
              </div>
              {chat.voiceEnabled && !isVoiceSetupDone() ? (
                <button type="button" className="btn btn-sm btn-outline btn-block" onClick={() => setShowVoiceSetup(true)}>
                  Spraaksetup
                </button>
              ) : null}
            </div>
          </InspFold>

          <InspFold id="results" title="Resultaten" open={Boolean(openFolds.results)} onToggle={toggleFold}>
            <div className="insp-card">
              {chat.selectedId ? (
                <ResultsPanel conversationId={chat.selectedId} onReuse={(artifact) => chat.reuseArtifact(artifact)} />
              ) : (
                <p className="muted" style={{ fontSize: 11 }}>Selecteer een gesprek.</p>
              )}
            </div>
          </InspFold>

          <InspFold id="actions" title="Acties" open={Boolean(openFolds.actions)} onToggle={toggleFold}>
            <div className="insp-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <button className="btn btn-sm btn-outline btn-block" type="button" onClick={() => void chat.refresh()}>
                Refresh
              </button>
              <button
                className="btn btn-sm btn-outline btn-block"
                type="button"
                disabled={!chat.selectedId}
                onClick={() => void chat.exportConversation()}
              >
                Export gesprek
              </button>
              <button className="btn btn-sm btn-gold btn-block" type="button" onClick={() => onNavigate("tasks")}>
                Open Work Runtime
              </button>
              <button
                className="btn btn-sm btn-outline btn-block"
                type="button"
                onClick={() => {
                  const goal = chat.draft.trim();
                  if (goal) writeCodingHandoff(goal, false);
                  onNavigate("coding");
                }}
              >
                Open Coding
              </button>
              <button className="btn btn-sm btn-outline btn-block" type="button" onClick={() => onNavigate("research")}>
                Open Research
              </button>
            </div>
          </InspFold>
        </>
      ) : null}
    </>
  );

  return <FinalBetaShell page="chat" body={body} inspector={inspector} onNavigate={onNavigate} />;
}
