import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { media } from "../assets/media";
import { BrandMark, BotAvatar } from "../components/BrandMark";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type {
  CapabilityListItem,
  Conversation,
  KnowledgeSource,
  ModelDescriptor,
  ReasoningDepth,
  ReasoningSummary,
} from "../types/api";
import { REASONING_DEPTH_OPTIONS } from "../types/api";

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
  requestedMode: string | null;
  effectiveMode: string | null;
  clampReason: string | null;
  nativeEffort: string | null;
  neuralAdaptation: string | null;
  expectedGain: number | null;
  maxReasoningTokens: number | null;
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
  requestedMode: null,
  effectiveMode: null,
  clampReason: null,
  nativeEffort: null,
  neuralAdaptation: null,
  expectedGain: null,
  maxReasoningTokens: null,
};

function formatTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function conversationDeepLink(id: string): string {
  return `${window.location.origin}/chat?conversation=${encodeURIComponent(id)}`;
}

const QUICK_PROMPTS: Record<string, string> = {
  "Deep Research": "Research this topic deeply and structure the important questions first: ",
  "Analyze Data": "Analyze the following data and explain the important patterns: ",
  "Generate Code": "Help me design and implement the following code: ",
  "Create Plan": "Create a concrete step-by-step plan for: ",
};

export function ChatPage() {
  const toast = useAppToast();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const draft = (location.state as LocationState | null)?.draft;

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [title, setTitle] = useState("New conversation");
  const [composer, setComposer] = useState(draft ?? "");
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeChip, setActiveChip] = useState<"All" | "Pinned">("All");
  const [rightTab, setRightTab] = useState<"Context" | "Tools" | "Agents">("Context");
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [reasoningMode, setReasoningMode] = useState<ReasoningDepth>("AUTO");
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [capabilities, setCapabilities] = useState<CapabilityListItem[]>([]);
  const [agentsEnabled, setAgentsEnabled] = useState<boolean | null>(null);
  const [codingEnabled, setCodingEnabled] = useState<boolean | null>(null);
  const [lastTurn, setLastTurn] = useState<LastTurnMeta>(EMPTY_TURN);
  const [bootstrapped, setBootstrapped] = useState(false);

  const messagesRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const modelMenuRef = useRef<HTMLDivElement | null>(null);
  const moreMenuRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const creatingRef = useRef(false);

  const activeConversation = useMemo(
    () => conversations.find((item) => item.id === conversationId) ?? null,
    [conversations, conversationId],
  );

  const filteredConversations = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return conversations.filter((item) => {
      if (activeChip === "Pinned" && !item.pinned) return false;
      if (!q) return true;
      return item.title.toLowerCase().includes(q);
    });
  }, [conversations, searchQuery, activeChip]);

  const modelLabel = useMemo(() => {
    if (!selectedModelId) return "Auto";
    const match = models.find((item) => item.id === selectedModelId);
    return match?.displayName || match?.id || selectedModelId;
  }, [models, selectedModelId]);

  const turnTags = useMemo(() => {
    const tags: string[] = [];
    if (lastTurn.model) tags.push(lastTurn.model);
    else if (selectedModelId) tags.push(modelLabel);
    else tags.push("Auto");
    if (lastTurn.intent) tags.push(lastTurn.intent);
    if (lastTurn.complexity) tags.push(lastTurn.complexity);
    if (lastTurn.cognitionMode) tags.push(`Reasoning ${lastTurn.cognitionMode}`);
    if (lastTurn.cognitionPhase) tags.push(lastTurn.cognitionPhase);
    tags.push(
      lastTurn.knowledgeCount === 1
        ? "1 knowledge source"
        : `${lastTurn.knowledgeCount} knowledge sources`,
    );
    if (lastTurn.streaming === "streaming") tags.push("Streaming");
    else if (lastTurn.streaming === "degraded") tags.push("Stream degraded");
    else if (lastTurn.streaming === "complete") tags.push("Complete");
    else if (lastTurn.streaming === "failed") tags.push("Failed");
    else tags.push("Idle");
    return tags;
  }, [lastTurn, modelLabel, selectedModelId]);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    creatingRef.current = creating;
  }, [creating]);

  useEffect(() => {
    if (!messagesRef.current) return;
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (modelMenuRef.current && !modelMenuRef.current.contains(target)) {
        setModelMenuOpen(false);
      }
      if (moreMenuRef.current && !moreMenuRef.current.contains(target)) {
        setMoreMenuOpen(false);
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
    setMessages(
      (data.messages || [])
        .filter((item) => item.role === "user" || item.role === "assistant")
        .map((item) => ({
          role: item.role as "user" | "assistant",
          content: item.content,
          created_at: item.created_at,
        })),
    );
    setLastTurn(EMPTY_TURN);
    const list = known ?? (await refreshConversations(id));
    setConversations(list);
  }

  async function reconcileConversation(id: string) {
    try {
      const data = await api.getConversation(id);
      setConversationId(id);
      syncUrl(id);
      setTitle(data.conversation.title);
      setMessages(
        (data.messages || [])
          .filter((item) => item.role === "user" || item.role === "assistant")
          .map((item) => ({
            role: item.role as "user" | "assistant",
            content: item.content,
            created_at: item.created_at,
          })),
      );
      await refreshConversations(id);
    } catch (error) {
      toast(
        `Could not reload conversation: ${error instanceof Error ? error.message : "unknown error"}`,
      );
    }
  }

  async function createConversation() {
    if (busyRef.current || creatingRef.current) return;
    setCreating(true);
    creatingRef.current = true;
    try {
      const data = await api.createConversation();
      setConversationId(data.conversation.id);
      setTitle(data.conversation.title);
      setMessages([]);
      setLastTurn(EMPTY_TURN);
      syncUrl(data.conversation.id);
      await refreshConversations(data.conversation.id);
      requestAnimationFrame(() => composerRef.current?.focus());
    } catch (error) {
      toast(`Could not create chat: ${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      creatingRef.current = false;
      setCreating(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const [health, coding, modelData, caps] = await Promise.all([
          api.health().catch(() => null),
          api.codingStatus().catch(() => null),
          api.listModels().catch(() => null),
          api.listCapabilities({ limit: 50 }).catch(() => null),
        ]);
        if (cancelled) return;
        if (health) {
          setAgentsEnabled(Boolean(health.agents?.enabled));
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
      } catch {
        /* parallel load already guarded */
      }

      try {
        const listed = await api.listConversations();
        if (cancelled) return;
        setConversations(listed.conversations);

        const deepLinkId = searchParams.get("conversation");
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
    const nextPinned = !activeConversation?.pinned;
    try {
      await api.updateConversation(conversationId, { pinned: nextPinned });
      await refreshConversations(conversationId);
      toast(nextPinned ? "Pinned" : "Unpinned");
    } catch (error) {
      toast(`Pin failed: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  async function renameConversation() {
    if (!conversationId) return;
    setMoreMenuOpen(false);
    const current = activeConversation?.title ?? title;
    const next = window.prompt("Rename conversation", current);
    if (next == null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === current) return;
    try {
      const data = await api.updateConversation(conversationId, { title: trimmed });
      setTitle(data.conversation.title);
      await refreshConversations(conversationId);
      toast("Renamed");
    } catch (error) {
      toast(`Rename failed: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  async function deleteCurrentConversation() {
    if (!conversationId) return;
    setMoreMenuOpen(false);
    const ok = window.confirm("Delete this conversation? This cannot be undone.");
    if (!ok) return;
    const deletingId = conversationId;
    try {
      await api.deleteConversation(deletingId);
      const list = await api.listConversations();
      setConversations(list.conversations);
      toast("Deleted");
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
    setLastTurn((prev) => ({ ...prev, streaming: "streaming" }));
    const abort = new AbortController();

    try {
      let doneOnce = false;
      const data = await api.chatStream(
        text,
        {
          conversationId: activeId,
          modelId: selectedModelId,
          reasoningMode,
        },
        {
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
        },
        { signal: abort.signal },
      );
      setConversationId(data.conversation_id);
      syncUrl(data.conversation_id);
      setMessages((current) => {
        const withoutPending = current.filter((item) => !item.pending);
        // Reconcile once: replace pending with canonical persisted assistant turn.
        if (doneOnce || data.assistant_message) {
          return [
            ...withoutPending,
            {
              role: "assistant",
              content: data.assistant_message.content,
              created_at: data.assistant_message.created_at,
            },
          ];
        }
        return withoutPending;
      });
      const degraded = Boolean(data.truth?.streaming_degraded);
      const cog = data.cognition && typeof data.cognition === "object" ? data.cognition : null;
      const cogRecord = cog as Record<string, unknown> | null;
      const cogDecision =
        cogRecord && "decision" in cogRecord && cogRecord.decision && typeof cogRecord.decision === "object"
          ? (cogRecord.decision as Record<string, unknown>)
          : null;
      const cogStatus =
        cogRecord && typeof cogRecord.status === "string" ? cogRecord.status : null;
      const neural =
        cogRecord &&
        "neural_budgets" in cogRecord &&
        cogRecord.neural_budgets &&
        typeof cogRecord.neural_budgets === "object"
          ? (cogRecord.neural_budgets as Record<string, unknown>)
          : null;
      const modeFromCog =
        (cogRecord && typeof cogRecord.mode === "string" && cogRecord.mode) ||
        (cogDecision && typeof cogDecision.mode === "string" && String(cogDecision.mode)) ||
        null;
      setLastTurn({
        model: data.model || null,
        intent: data.reasoning?.intent ?? null,
        complexity: data.reasoning?.complexity ?? null,
        knowledgeCount: data.knowledge_sources?.length ?? 0,
        streaming: degraded ? "degraded" : "complete",
        reasoning: data.reasoning ?? null,
        knowledgeSources: data.knowledge_sources ?? [],
        cognitionMode: modeFromCog,
        cognitionStatus: cogStatus,
        cognitionPhase:
          cogStatus && ["REASONING", "PERCEIVING", "VERIFYING", "EXECUTING"].includes(cogStatus)
            ? cogStatus.charAt(0) + cogStatus.slice(1).toLowerCase()
            : null,
        requestedMode:
          cogRecord && typeof cogRecord.requested_mode === "string"
            ? cogRecord.requested_mode
            : null,
        effectiveMode:
          cogRecord && typeof cogRecord.effective_mode === "string"
            ? cogRecord.effective_mode
            : modeFromCog,
        clampReason:
          cogRecord && typeof cogRecord.clamp_reason === "string" ? cogRecord.clamp_reason : null,
        nativeEffort:
          neural && typeof neural.native_effort === "string" ? neural.native_effort : null,
        neuralAdaptation:
          cogRecord && typeof cogRecord.neural_adaptation === "string"
            ? cogRecord.neural_adaptation
            : null,
        expectedGain:
          cogRecord && typeof cogRecord.expected_gain === "number"
            ? cogRecord.expected_gain
            : null,
        maxReasoningTokens:
          neural && typeof neural.max_reasoning_tokens === "number"
            ? neural.max_reasoning_tokens
            : null,
      });
      const list = await refreshConversations(data.conversation_id);
      const active = list.find((item) => item.id === data.conversation_id);
      if (active) setTitle(active.title);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Request failed";
      setLastTurn((prev) => ({ ...prev, streaming: "failed" }));
      setMessages((current) => {
        const withoutPending = current.filter((item) => !item.pending);
        return [
          ...withoutPending,
          {
            role: "assistant",
            content: `Leviathan could not reach the configured LLM. ${detail}`,
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

  const pinned = Boolean(activeConversation?.pinned);

  return (
    <AppShell activeMode="chat" chatApp searchPlaceholder="Search conversations, files, prompts...">
      <aside className="lv-chat-rail" id="chatRail">
        <div className="lv-chat-rail-head">
          <h2>Chat</h2>
          <button
            className="lv-new-chat"
            type="button"
            disabled={busy || creating}
            onClick={() => void createConversation()}
          >
            <svg className="lv-icon" viewBox="0 0 24 24">
              <path d="M12 5v14M5 12h14" />
            </svg>{" "}
            New Chat
          </button>
        </div>

        <label className="lv-chat-search">
          <svg className="lv-icon" viewBox="0 0 24 24">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3-3" />
          </svg>
          <input
            type="search"
            placeholder="Search chats..."
            aria-label="Search chats"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
        </label>

        <div className="lv-chat-filters">
          {(["All", "Pinned"] as const).map((chip) => (
            <button
              key={chip}
              className={`lv-chip${activeChip === chip ? " is-active" : ""}`}
              type="button"
              onClick={() => setActiveChip(chip)}
            >
              {chip}
            </button>
          ))}
        </div>

        <div className="lv-thread-list" id="threadList">
          {!bootstrapped ? (
            <div className="lv-chat-empty" style={{ padding: "1rem" }}>
              <span>Loading conversations…</span>
            </div>
          ) : filteredConversations.length === 0 ? (
            <div className="lv-chat-empty" style={{ padding: "1rem" }}>
              <span>
                {activeChip === "Pinned" ? "No pinned conversations." : "No matching conversations."}
              </span>
            </div>
          ) : (
            filteredConversations.map((conversation) => (
              <button
                key={conversation.id}
                className={`lv-thread${conversation.id === conversationId ? " is-active" : ""}`}
                type="button"
                disabled={busy}
                onClick={() => void loadConversation(conversation.id)}
              >
                <strong>
                  {conversation.pinned ? "★ " : ""}
                  {conversation.title}
                </strong>
                <time>{formatTime(conversation.updated_at)}</time>
                <small>
                  {conversation.id === conversationId
                    ? "Active conversation"
                    : conversation.pinned
                      ? "Pinned"
                      : "Persistent chat"}
                </small>
              </button>
            ))
          )}
        </div>
      </aside>

      <main className="lv-chat-main">
        <div className="lv-chat-top">
          <div className="lv-chat-title-wrap">
            <div className="lv-chat-title-row">
              <div className="lv-brand-mark" aria-hidden="true">
                <BrandMark id="chatBrand" />
              </div>
              <h1 className="lv-chat-title">{activeConversation?.title ?? title}</h1>
            </div>
            <div className="lv-tag-row">
              {turnTags.map((tag) => (
                <span className="lv-tag" key={tag}>
                  {tag}
                </span>
              ))}
            </div>
          </div>
          <div className="lv-chat-actions">
            <button
              className="lv-ghost-btn"
              type="button"
              onClick={() => void copyLocalLink(conversationId)}
            >
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M12 5v10M8 9l4-4 4 4M5 19h14" />
              </svg>
              Share
            </button>
            <button
              className="lv-ghost-btn icon-only"
              type="button"
              aria-label={pinned ? "Unpin conversation" : "Pin conversation"}
              aria-pressed={pinned}
              onClick={() => void togglePinned()}
            >
              <svg
                className="lv-icon"
                viewBox="0 0 24 24"
                style={pinned ? { fill: "currentColor" } : undefined}
              >
                <path d="M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.8 7.2 19l.9-5.4L4.2 9.7l5.4-.8L12 4z" />
              </svg>
            </button>
            <div ref={moreMenuRef} style={{ position: "relative" }}>
              <button
                className="lv-ghost-btn icon-only"
                type="button"
                aria-label="More"
                aria-expanded={moreMenuOpen}
                onClick={() => setMoreMenuOpen((open) => !open)}
              >
                <svg className="lv-icon" viewBox="0 0 24 24">
                  <circle cx="6" cy="12" r="1.3" fill="currentColor" stroke="none" />
                  <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
                  <circle cx="18" cy="12" r="1.3" fill="currentColor" stroke="none" />
                </svg>
              </button>
              {moreMenuOpen ? (
                <div
                  role="menu"
                  style={{
                    position: "absolute",
                    right: 0,
                    top: "calc(100% + 0.35rem)",
                    minWidth: "10rem",
                    zIndex: 20,
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.15rem",
                    padding: "0.35rem",
                    borderRadius: "0.5rem",
                    background: "var(--lv-panel, #12141a)",
                    border: "1px solid var(--lv-border, rgba(255,255,255,0.12))",
                    boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
                  }}
                >
                  <button
                    type="button"
                    className="lv-ghost-btn"
                    role="menuitem"
                    onClick={() => void renameConversation()}
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    className="lv-ghost-btn"
                    role="menuitem"
                    onClick={() => void copyLocalLink(conversationId)}
                  >
                    Copy local link
                  </button>
                  <button
                    type="button"
                    className="lv-ghost-btn"
                    role="menuitem"
                    onClick={() => void deleteCurrentConversation()}
                  >
                    Delete
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div className="lv-messages" id="messages" ref={messagesRef}>
          {messages.length === 0 ? (
            <div className="lv-chat-empty">
              <strong>Leviathan is ready.</strong>
              <span>
                Start a conversation. Persistent chat, lightweight reasoning and local knowledge
                retrieval are connected to the Python backend.
              </span>
            </div>
          ) : (
            messages.map((message, index) => (
              <article
                key={`${message.role}-${index}-${message.created_at ?? "pending"}`}
                className={`lv-msg ${message.role}`}
                data-pending={message.pending ? "true" : undefined}
                data-error={message.error ? "true" : undefined}
              >
                {message.role === "user" ? (
                  <img className="lv-msg-avatar" src={media.avatar} alt="" />
                ) : (
                  <BotAvatar />
                )}
                <div>
                  <div
                    className={`lv-bubble${message.pending ? " lv-bubble-pending" : ""}${
                      message.error ? " lv-bubble-error" : ""
                    }`}
                    style={{ whiteSpace: "pre-wrap" }}
                  >
                    {message.content}
                  </div>
                  <div className="lv-msg-meta">
                    {formatTime(message.created_at) || (message.pending ? "thinking" : "")}
                  </div>
                </div>
              </article>
            ))
          )}
        </div>

        <div className="lv-composer-wrap">
          <div className="lv-composer">
            <textarea
              ref={composerRef}
              rows={1}
              placeholder="Message Leviathan..."
              aria-label="Message Leviathan"
              value={composer}
              disabled={busy}
              onChange={(event) => setComposer(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage();
                }
              }}
            />
            <div ref={modelMenuRef} style={{ position: "relative" }}>
              <button
                className="lv-model"
                type="button"
                title="Session model (not saved)"
                aria-expanded={modelMenuOpen}
                disabled={busy}
                onClick={() => setModelMenuOpen((open) => !open)}
              >
                {modelLabel}{" "}
                <svg className="lv-icon" viewBox="0 0 24 24">
                  <path d="M7 10l5 5 5-5" />
                </svg>
              </button>
              {modelMenuOpen ? (
                <div
                  role="listbox"
                  aria-label="Session model"
                  style={{
                    position: "absolute",
                    right: 0,
                    bottom: "calc(100% + 0.35rem)",
                    minWidth: "12rem",
                    maxHeight: "16rem",
                    overflowY: "auto",
                    zIndex: 20,
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.15rem",
                    padding: "0.35rem",
                    borderRadius: "0.5rem",
                    background: "var(--lv-panel, #12141a)",
                    border: "1px solid var(--lv-border, rgba(255,255,255,0.12))",
                    boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
                  }}
                >
                  <button
                    type="button"
                    className="lv-ghost-btn"
                    role="option"
                    aria-selected={selectedModelId === null}
                    onClick={() => {
                      setSelectedModelId(null);
                      setModelMenuOpen(false);
                    }}
                  >
                    Auto
                  </button>
                  {models.map((model) => (
                    <button
                      key={model.id}
                      type="button"
                      className="lv-ghost-btn"
                      role="option"
                      aria-selected={selectedModelId === model.id}
                      onClick={() => {
                        setSelectedModelId(model.id);
                        setModelMenuOpen(false);
                      }}
                    >
                      {model.displayName || model.id}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <label
              className="lv-model"
              title="Session reasoning depth (not saved)"
              style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}
            >
              <span className="lv-muted" style={{ fontSize: "0.75rem" }}>
                Depth
              </span>
              <select
                aria-label="Reasoning depth"
                value={reasoningMode}
                disabled={busy}
                onChange={(event) => setReasoningMode(event.target.value as ReasoningDepth)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "inherit",
                  font: "inherit",
                  cursor: busy ? "not-allowed" : "pointer",
                }}
              >
                {REASONING_DEPTH_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="lv-prompt-send lv-button-primary"
              type="button"
              id="sendBtn"
              aria-label="Send"
              disabled={busy}
              onClick={() => void sendMessage()}
            >
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M5 12h12M13 6l6 6-6 6" />
              </svg>
            </button>
          </div>
          <div className="lv-quick-actions">
            {Object.keys(QUICK_PROMPTS).map((label) => (
              <button
                key={label}
                className="lv-quick"
                type="button"
                onClick={() => {
                  setComposer(QUICK_PROMPTS[label]);
                  composerRef.current?.focus();
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </main>

      <aside className="lv-chat-right">
        <div className="lv-right-tabs">
          {(["Context", "Tools", "Agents"] as const).map((tab) => (
            <button
              key={tab}
              className={`lv-right-tab${rightTab === tab ? " is-active" : ""}`}
              type="button"
              onClick={() => setRightTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>

        {rightTab === "Context" ? (
          <section className="lv-panel lv-side-card">
            <div className="lv-side-card-head">
              <h3>Current Context</h3>
            </div>
            <div className="lv-context-active">
              <strong>{activeConversation?.title ?? title}</strong>
              <small>
                {lastTurn.intent && lastTurn.complexity
                  ? `${lastTurn.intent} · ${lastTurn.complexity}`
                  : conversationId
                    ? "Persistent local session"
                    : "No active conversation"}
                {lastTurn.cognitionMode ? ` · ${lastTurn.cognitionMode}` : ""}
                {lastTurn.knowledgeCount
                  ? ` · ${lastTurn.knowledgeCount} knowledge source${
                      lastTurn.knowledgeCount === 1 ? "" : "s"
                    }`
                  : ""}
              </small>
            </div>
            {lastTurn.reasoning?.steps?.length ? (
              <div className="lv-context-list">
                {lastTurn.reasoning.steps.map((step, index) => (
                  <div className="lv-context-item" key={`step-${index}`}>
                    <span className="lv-mini-icon blue">
                      <svg className="lv-icon" viewBox="0 0 24 24">
                        <path d="M5 19V9M12 19V5M19 19v-7" />
                      </svg>
                    </span>
                    <span>
                      <strong>Step {index + 1}</strong>
                      <small>{step}</small>
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
            {(lastTurn.cognitionMode ||
              lastTurn.nativeEffort ||
              lastTurn.requestedMode ||
              lastTurn.effectiveMode) && (
              <div className="lv-context-list" aria-label="Cognition compute">
                <div className="lv-context-item">
                  <span>
                    <strong>Orchestration</strong>
                    <small>
                      {[
                        lastTurn.requestedMode
                          ? `requested ${lastTurn.requestedMode}`
                          : null,
                        lastTurn.effectiveMode || lastTurn.cognitionMode
                          ? `effective ${lastTurn.effectiveMode || lastTurn.cognitionMode}`
                          : null,
                        lastTurn.clampReason ? `clamp ${lastTurn.clampReason}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "—"}
                    </small>
                  </span>
                </div>
                <div className="lv-context-item">
                  <span>
                    <strong>Neural axis</strong>
                    <small>
                      {[
                        lastTurn.nativeEffort ? `effort ${lastTurn.nativeEffort}` : null,
                        lastTurn.maxReasoningTokens != null
                          ? `tokens ${lastTurn.maxReasoningTokens}`
                          : null,
                        lastTurn.expectedGain != null
                          ? `gain ${lastTurn.expectedGain.toFixed(2)}`
                          : null,
                        lastTurn.neuralAdaptation
                          ? `adapt ${lastTurn.neuralAdaptation}`
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "Unmeasured"}
                    </small>
                  </span>
                </div>
              </div>
            )}
            <div className="lv-context-list">
              {lastTurn.knowledgeSources.length === 0 ? (
                <div className="lv-context-item">
                  <span>
                    <strong>No knowledge sources</strong>
                    <small>Last turn did not retrieve knowledge.</small>
                  </span>
                </div>
              ) : (
                lastTurn.knowledgeSources.map((source) => (
                  <div className="lv-context-item" key={source.id}>
                    <span className="lv-mini-icon blue">
                      <svg className="lv-icon" viewBox="0 0 24 24">
                        <path d="M5 19V9M12 19V5M19 19v-7" />
                      </svg>
                    </span>
                    <span>
                      <strong>{source.title || source.id}</strong>
                      <small>{source.source || source.id}</small>
                    </span>
                  </div>
                ))
              )}
            </div>
          </section>
        ) : null}

        {rightTab === "Tools" ? (
          <section className="lv-panel lv-side-card">
            <div className="lv-side-card-head">
              <h3>Capabilities</h3>
            </div>
            <p style={{ margin: "0 0 0.75rem", fontSize: "0.85rem", opacity: 0.8 }}>
              Read-only catalog. Invocation goes through ExecutionGateway elsewhere — not from this
              panel.
            </p>
            <div className="lv-tool-list">
              {capabilities.length === 0 ? (
                <div className="lv-tool-item">
                  <span>
                    <strong>No capabilities listed</strong>
                    <small>Backend returned an empty catalog.</small>
                  </span>
                </div>
              ) : (
                capabilities.map((cap) => (
                  <div className="lv-tool-item" key={cap.id}>
                    <span className="lv-mini-icon cyan">
                      <svg className="lv-icon" viewBox="0 0 24 24">
                        <path d="M14 7l3 3-8 8H6v-3l8-8z" />
                      </svg>
                    </span>
                    <span>
                      <strong>{cap.name || cap.id}</strong>
                      <small>
                        {cap.description || "No description"}
                        {cap.available === false
                          ? " · unavailable"
                          : cap.enabled === false
                            ? " · disabled"
                            : " · registered"}
                        {cap.side_effects?.length ? ` · ${cap.side_effects.join(", ")}` : ""}
                      </small>
                    </span>
                  </div>
                ))
              )}
            </div>
          </section>
        ) : null}

        {rightTab === "Agents" ? (
          <section className="lv-panel lv-side-card">
            <div className="lv-side-card-head">
              <h3>Runtime status</h3>
              <Link className="lv-link" to="/agents">
                Agents
              </Link>
            </div>
            <div className="lv-agent-side-list">
              <div className="lv-agent-side">
                <span className="lv-mini-icon blue">
                  <svg className="lv-icon" viewBox="0 0 24 24">
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3-3" />
                  </svg>
                </span>
                <span>
                  <strong>Agents runtime</strong>
                  <small>
                    {agentsEnabled === null
                      ? "Status unavailable"
                      : agentsEnabled
                        ? "Enabled (health.agents.enabled)"
                        : "Disabled (health.agents.enabled)"}
                  </small>
                </span>
                <span className="lv-online-label">
                  {agentsEnabled ? "Enabled" : agentsEnabled === false ? "Disabled" : "Unknown"}
                </span>
              </div>
              <div className="lv-agent-side">
                <span className="lv-mini-icon blue">
                  <svg className="lv-icon" viewBox="0 0 24 24">
                    <path d="M8 7h8M8 12h8M8 17h5" />
                  </svg>
                </span>
                <span>
                  <strong>Coding agent</strong>
                  <small>
                    {codingEnabled === null
                      ? "Status unavailable"
                      : codingEnabled
                        ? "Enabled (codingStatus.enabled)"
                        : "Disabled (codingStatus.enabled)"}
                  </small>
                </span>
                <span className="lv-online-label">
                  {codingEnabled ? "Enabled" : codingEnabled === false ? "Disabled" : "Unknown"}
                </span>
              </div>
            </div>
            <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
              <Link className="lv-link" to="/agents">
                Open /agents
              </Link>
              <Link className="lv-link" to="/coding">
                Open /coding
              </Link>
            </div>
          </section>
        ) : null}
      </aside>
    </AppShell>
  );
}
