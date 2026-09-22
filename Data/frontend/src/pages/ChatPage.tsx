import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api/client";
import { media } from "../assets/media";
import { BrandMark, BotAvatar } from "../components/BrandMark";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { Conversation, ReasoningSummary } from "../types/api";

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

function formatTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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
  const draft = (location.state as LocationState | null)?.draft;

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [title, setTitle] = useState("New conversation");
  const [composer, setComposer] = useState(draft ?? "");
  const [busy, setBusy] = useState(false);
  const [modelLabel, setModelLabel] = useState("LLM Offline");
  const [contextMeta, setContextMeta] = useState("");
  const [activeChip, setActiveChip] = useState("All");
  const [rightTab, setRightTab] = useState("Context");
  const messagesRef = useRef<HTMLDivElement | null>(null);

  const activeConversation = useMemo(
    () => conversations.find((item) => item.id === conversationId) ?? null,
    [conversations, conversationId],
  );

  useEffect(() => {
    if (!messagesRef.current) return;
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const health = await api.health();
        if (cancelled) return;
        setModelLabel(health.llm.available ? health.llm.model ?? "Model Ready" : "LLM Offline");
      } catch {
        if (!cancelled) setModelLabel("Backend Offline");
      }

      try {
        const listed = await api.listConversations();
        if (cancelled) return;
        setConversations(listed.conversations);
        if (listed.conversations.length > 0) {
          await loadConversation(listed.conversations[0].id, listed.conversations);
        } else {
          await createConversation();
        }
      } catch (error) {
        if (cancelled) return;
        setMessages([]);
        setTitle("New conversation");
        toast(`Backend unavailable: ${error instanceof Error ? error.message : "unknown error"}`);
      }
    })();

    return () => {
      cancelled = true;
    };
    // Bootstrap once on mount. toast is stable enough for this shell.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshConversations(selectId?: string | null) {
    const data = await api.listConversations();
    setConversations(data.conversations);
    if (selectId) {
      setConversationId(selectId);
    }
    return data.conversations;
  }

  async function loadConversation(id: string, known?: Conversation[]) {
    if (busy) return;
    const data = await api.getConversation(id);
    setConversationId(id);
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
    setContextMeta("Persistent local session");
    const list = known ?? (await refreshConversations(id));
    setConversations(list);
  }

  async function createConversation() {
    if (busy) return;
    const data = await api.createConversation();
    setConversationId(data.conversation.id);
    setTitle(data.conversation.title);
    setMessages([]);
    setContextMeta("");
    await refreshConversations(data.conversation.id);
  }

  function showReasoningSummary(reasoning: ReasoningSummary, sources: { id: string }[]) {
    const knowledgeText = sources.length
      ? ` · ${sources.length} knowledge source${sources.length === 1 ? "" : "s"}`
      : "";
    setContextMeta(`${reasoning.intent} · ${reasoning.complexity}${knowledgeText}`);
  }

  async function sendMessage() {
    const text = composer.trim();
    if (!text || busy) return;

    let activeId = conversationId;
    if (!activeId) {
      const created = await api.createConversation();
      activeId = created.conversation.id;
      setConversationId(activeId);
      setTitle(created.conversation.title);
    }

    setComposer("");
    setMessages((current) => [
      ...current,
      { role: "user", content: text, created_at: new Date().toISOString() },
      { role: "assistant", content: "Thinking…", created_at: null, pending: true },
    ]);
    setBusy(true);

    try {
      const data = await api.chat(text, activeId);
      setConversationId(data.conversation_id);
      setMessages((current) => {
        const withoutPending = current.filter((item) => !item.pending);
        return [
          ...withoutPending,
          {
            role: "assistant",
            content: data.assistant_message.content,
            created_at: data.assistant_message.created_at,
          },
        ];
      });
      showReasoningSummary(data.reasoning, data.knowledge_sources);
      setModelLabel(data.model);
      const list = await refreshConversations(data.conversation_id);
      const active = list.find((item) => item.id === data.conversation_id);
      if (active) setTitle(active.title);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Request failed";
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
      await refreshConversations(activeId);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell activeMode="chat" chatApp searchPlaceholder="Search conversations, files, prompts...">
      <aside className="lv-chat-rail" id="chatRail">
        <div className="lv-chat-rail-head">
          <h2>Chat</h2>
          <button className="lv-new-chat" type="button" onClick={() => void createConversation()}>
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
          <input type="search" placeholder="Search chats..." aria-label="Search chats" />
        </label>

        <div className="lv-chat-filters">
          {["All", "Pinned", "Agents", "Projects"].map((chip) => (
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
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              className={`lv-thread${conversation.id === conversationId ? " is-active" : ""}`}
              type="button"
              onClick={() => void loadConversation(conversation.id)}
            >
              <strong>{conversation.title}</strong>
              <time>{formatTime(conversation.updated_at)}</time>
              <small>
                {conversation.id === conversationId ? "Active conversation" : "Persistent chat"}
              </small>
            </button>
          ))}
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
              <span className="lv-tag">Trading</span>
              <span className="lv-tag">Multi-Agent</span>
              <span className="lv-tag">Strategy</span>
              <button className="lv-tag-add" type="button" aria-label="Add tag">
                +
              </button>
            </div>
          </div>
          <div className="lv-chat-actions">
            <button className="lv-ghost-btn" type="button" onClick={() => toast("Share")}>
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M12 5v10M8 9l4-4 4 4M5 19h14" />
              </svg>
              Share
            </button>
            <button className="lv-ghost-btn icon-only" type="button" aria-label="Favorite">
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.8 7.2 19l.9-5.4L4.2 9.7l5.4-.8L12 4z" />
              </svg>
            </button>
            <button className="lv-ghost-btn icon-only" type="button" aria-label="More">
              <svg className="lv-icon" viewBox="0 0 24 24">
                <circle cx="6" cy="12" r="1.3" fill="currentColor" stroke="none" />
                <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
                <circle cx="18" cy="12" r="1.3" fill="currentColor" stroke="none" />
              </svg>
            </button>
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
            <div className="lv-composer-tools">
              <button type="button" aria-label="Attach" onClick={() => toast("Attach")}>
                <svg className="lv-icon" viewBox="0 0 24 24">
                  <path d="M8 12l6-6a3 3 0 114 4l-8 8a4.2 4.2 0 11-6-6l8-8" />
                </svg>
              </button>
              <button type="button" aria-label="Scan">
                <svg className="lv-icon" viewBox="0 0 24 24">
                  <path d="M5 9V5h4M15 5h4v4M19 15v4h-4M9 19H5v-4" />
                </svg>
              </button>
              <button type="button" aria-label="Focus">
                <svg className="lv-icon" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="7" />
                  <circle cx="12" cy="12" r="2" />
                </svg>
              </button>
            </div>
            <textarea
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
            <button className="lv-model" type="button" title="Configured model">
              {modelLabel}{" "}
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M7 10l5 5 5-5" />
              </svg>
            </button>
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
                }}
              >
                {label}
              </button>
            ))}
            <button className="lv-quick" type="button" onClick={() => toast("+ More")}>
              + More
            </button>
          </div>
        </div>
      </main>

      <aside className="lv-chat-right">
        <div className="lv-right-tabs">
          {["Context", "Tools", "Agents"].map((tab) => (
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

        <section className="lv-panel lv-side-card">
          <div className="lv-side-card-head">
            <h3>Current Context</h3>
            <button type="button" aria-label="Close">
              ×
            </button>
          </div>
          <div className="lv-context-active">
            <strong>{activeConversation?.title ?? title}</strong>
            <small>{contextMeta || (conversationId ? "Persistent local session" : "")}</small>
          </div>
          <div className="lv-context-list">
            {["Market Data Analysis", "Trading Strategies", "Risk Parameters"].map((label) => (
              <button
                key={label}
                className="lv-context-item"
                type="button"
                onClick={() => toast("This capability is reserved for a later Leviathan step.")}
              >
                <span className="lv-mini-icon blue">
                  <svg className="lv-icon" viewBox="0 0 24 24">
                    <path d="M5 19V9M12 19V5M19 19v-7" />
                  </svg>
                </span>
                <span>
                  <strong>{label}</strong>
                  <small>Reserved</small>
                </span>
              </button>
            ))}
          </div>
          <button
            className="lv-add-context"
            type="button"
            onClick={() => toast("This capability is reserved for a later Leviathan step.")}
          >
            + Add context
          </button>
        </section>

        <section className="lv-panel lv-side-card">
          <div className="lv-side-card-head">
            <h3>Suggested Tools</h3>
          </div>
          <div className="lv-tool-list">
            {["Web Search", "Code Interpreter", "Data Analysis", "File Search", "Create Document"].map(
              (label) => (
                <button
                  key={label}
                  className="lv-tool-item"
                  type="button"
                  onClick={() => toast("This capability is reserved for a later Leviathan step.")}
                >
                  <span className="lv-mini-icon cyan">
                    <svg className="lv-icon" viewBox="0 0 24 24">
                      <path d="M14 7l3 3-8 8H6v-3l8-8z" />
                    </svg>
                  </span>
                  <span>
                    <strong>{label}</strong>
                    <small>Reserved</small>
                  </span>
                </button>
              ),
            )}
          </div>
        </section>

        <section className="lv-panel lv-side-card">
          <div className="lv-side-card-head">
            <h3>Active Agents</h3>
            <button className="lv-link" type="button" onClick={() => toast("Manage")}>
              Manage
            </button>
          </div>
          <div className="lv-agent-side-list">
            {["Research Agent", "Code Agent", "Trading Agent", "Analysis Agent"].map((label) => (
              <div className="lv-agent-side" key={label}>
                <span className="lv-mini-icon blue">
                  <svg className="lv-icon" viewBox="0 0 24 24">
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3-3" />
                  </svg>
                </span>
                <span>
                  <strong>{label}</strong>
                  <small>Shell preview</small>
                </span>
                <span className="lv-online-label">
                  <span className="lv-status-online" />
                  Online
                </span>
              </div>
            ))}
          </div>
        </section>
      </aside>
    </AppShell>
  );
}
