(() => {
  const messagesEl = document.getElementById("messages");
  const sendBtn = document.getElementById("sendBtn");
  const composer = document.querySelector(".lv-composer textarea");
  const threadList = document.getElementById("threadList");
  const newChatBtn = document.querySelector(".lv-new-chat");
  const titleEl = document.querySelector(".lv-chat-title");
  const modelBtn = document.querySelector(".lv-model");
  const contextTitle = document.querySelector(".lv-context-active strong");
  const contextMeta = document.querySelector(".lv-context-active small");
  const toastEl = document.getElementById("toast");

  const state = {
    conversationId: null,
    busy: false,
    conversations: [],
  };

  let toastTimer = 0;

  function toast(message) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.add("show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toastEl.classList.remove("show"), 2200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });

    let data = null;
    try {
      data = await response.json();
    } catch (_) {
      data = null;
    }

    if (!response.ok) {
      const detail = data && data.detail ? data.detail : `Request failed (${response.status})`;
      throw new Error(detail);
    }
    return data;
  }

  function formatTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function botAvatar() {
    const el = document.createElement("div");
    el.className = "lv-msg-avatar bot";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 3v18M7 7l5-3 5 3M5 12h14M7 17l5 3 5-3"/></svg>';
    return el;
  }

  function messageNode(message, { pending = false, error = false } = {}) {
    const article = document.createElement("article");
    article.className = `lv-msg ${message.role === "user" ? "user" : "assistant"}`;
    if (pending) article.dataset.pending = "true";
    if (error) article.dataset.error = "true";

    if (message.role === "user") {
      const avatar = document.createElement("img");
      avatar.className = "lv-msg-avatar";
      avatar.src = "assets/avatar.jpg";
      avatar.alt = "";
      article.appendChild(avatar);
    } else {
      article.appendChild(botAvatar());
    }

    const body = document.createElement("div");
    const bubble = document.createElement("div");
    bubble.className = "lv-bubble";
    bubble.style.whiteSpace = "pre-wrap";
    bubble.textContent = message.content;
    if (pending) bubble.classList.add("lv-bubble-pending");
    if (error) bubble.classList.add("lv-bubble-error");

    const meta = document.createElement("div");
    meta.className = "lv-msg-meta";
    meta.textContent = formatTime(message.created_at) || (pending ? "thinking" : "");

    body.appendChild(bubble);
    body.appendChild(meta);
    article.appendChild(body);
    return article;
  }

  function scrollToBottom() {
    if (!messagesEl) return;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function renderMessages(messages) {
    if (!messagesEl) return;
    messagesEl.replaceChildren();

    if (!messages.length) {
      const empty = document.createElement("div");
      empty.className = "lv-chat-empty";
      empty.innerHTML = "<strong>Leviathan is ready.</strong><span>Start a conversation. Step 1 includes persistent chat, lightweight reasoning and local knowledge retrieval.</span>";
      messagesEl.appendChild(empty);
      return;
    }

    messages.forEach((message) => messagesEl.appendChild(messageNode(message)));
    scrollToBottom();
  }

  function appendMessage(message, options) {
    if (!messagesEl) return null;
    const empty = messagesEl.querySelector(".lv-chat-empty");
    if (empty) empty.remove();
    const node = messageNode(message, options);
    messagesEl.appendChild(node);
    scrollToBottom();
    return node;
  }

  function setBusy(busy) {
    state.busy = busy;
    if (sendBtn) sendBtn.disabled = busy;
    if (composer) composer.disabled = busy;
  }

  function setConversationHeader(conversation) {
    if (titleEl) titleEl.textContent = conversation ? conversation.title : "New conversation";
    if (contextTitle) contextTitle.textContent = conversation ? conversation.title : "No active context";
    if (contextMeta) contextMeta.textContent = conversation ? "Persistent local session" : "";
  }

  function renderThreads() {
    if (!threadList) return;
    threadList.replaceChildren();

    state.conversations.forEach((conversation) => {
      const button = document.createElement("button");
      button.className = "lv-thread" + (conversation.id === state.conversationId ? " is-active" : "");
      button.type = "button";

      const strong = document.createElement("strong");
      strong.textContent = conversation.title;
      const time = document.createElement("time");
      time.textContent = formatTime(conversation.updated_at);
      const small = document.createElement("small");
      small.textContent = conversation.id === state.conversationId ? "Active conversation" : "Persistent chat";

      button.append(strong, time, small);
      button.addEventListener("click", () => loadConversation(conversation.id));
      threadList.appendChild(button);
    });
  }

  async function refreshConversations({ selectFirst = false } = {}) {
    const data = await api("/api/conversations");
    state.conversations = data.conversations || [];

    if (selectFirst && !state.conversationId && state.conversations.length) {
      state.conversationId = state.conversations[0].id;
    }
    renderThreads();
  }

  async function loadConversation(conversationId) {
    if (state.busy) return;
    const data = await api(`/api/conversations/${encodeURIComponent(conversationId)}`);
    state.conversationId = conversationId;
    setConversationHeader(data.conversation);
    renderMessages(data.messages || []);
    await refreshConversations();
  }

  async function createConversation() {
    if (state.busy) return;
    const data = await api("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title: "New conversation" }),
    });
    state.conversationId = data.conversation.id;
    setConversationHeader(data.conversation);
    renderMessages([]);
    await refreshConversations();
    if (composer) composer.focus();
  }

  function showReasoningSummary(reasoning, sources) {
    if (!contextMeta || !reasoning) return;
    const sourceCount = Array.isArray(sources) ? sources.length : 0;
    const knowledgeText = sourceCount ? ` · ${sourceCount} knowledge source${sourceCount === 1 ? "" : "s"}` : "";
    contextMeta.textContent = `${reasoning.intent} · ${reasoning.complexity}${knowledgeText}`;
  }

  async function sendMessage() {
    if (!composer || state.busy) return;
    const text = composer.value.trim();
    if (!text) return;

    if (!state.conversationId) {
      await createConversation();
    }

    composer.value = "";
    appendMessage({ role: "user", content: text, created_at: new Date().toISOString() });
    const pending = appendMessage(
      { role: "assistant", content: "Thinking…", created_at: null },
      { pending: true },
    );

    setBusy(true);
    try {
      const data = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          conversation_id: state.conversationId,
          message: text,
        }),
      });

      if (pending) pending.remove();
      state.conversationId = data.conversation_id;
      appendMessage(data.assistant_message);
      showReasoningSummary(data.reasoning, data.knowledge_sources);
      if (modelBtn && data.model) modelBtn.firstChild.textContent = `${data.model} `;
      await refreshConversations();
      const active = state.conversations.find((item) => item.id === state.conversationId);
      if (active) setConversationHeader(active);
    } catch (error) {
      if (pending) pending.remove();
      appendMessage(
        {
          role: "assistant",
          content: `Leviathan could not reach the configured LLM. ${error.message}`,
          created_at: new Date().toISOString(),
        },
        { error: true },
      );
      toast(error.message);
      await refreshConversations();
    } finally {
      setBusy(false);
      composer.focus();
    }
  }

  async function loadHealth() {
    try {
      const health = await api("/api/health");
      if (modelBtn) {
        const label = health.llm && health.llm.available
          ? health.llm.model
          : "LLM Offline";
        modelBtn.firstChild.textContent = `${label} `;
        modelBtn.title = health.llm && health.llm.base_url ? health.llm.base_url : "";
      }
    } catch (_) {
      if (modelBtn) modelBtn.firstChild.textContent = "Backend Offline ";
    }
  }

  function wireStaticControls() {
    document.querySelectorAll(".lv-chip, .lv-right-tab").forEach((item) => {
      item.addEventListener("click", () => {
        const siblings = item.parentElement ? Array.from(item.parentElement.children) : [];
        siblings.forEach((el) => el.classList.remove("is-active"));
        item.classList.add("is-active");
      });
    });

    const quickPrompts = {
      "Deep Research": "Research this topic deeply and structure the important questions first: ",
      "Analyze Data": "Analyze the following data and explain the important patterns: ",
      "Generate Code": "Help me design and implement the following code: ",
      "Create Plan": "Create a concrete step-by-step plan for: ",
    };

    document.querySelectorAll(".lv-quick").forEach((button) => {
      button.addEventListener("click", () => {
        const label = button.textContent.trim();
        if (composer && quickPrompts[label]) {
          composer.value = quickPrompts[label];
          composer.focus();
        }
      });
    });

    document.querySelectorAll(".lv-tool-item, .lv-context-item, .lv-add-context").forEach((button) => {
      button.addEventListener("click", () => toast("This capability is reserved for a later Leviathan step."));
    });
  }

  async function bootstrap() {
    wireStaticControls();
    await loadHealth();

    try {
      await refreshConversations({ selectFirst: true });
      if (state.conversationId) {
        await loadConversation(state.conversationId);
      } else {
        await createConversation();
      }
    } catch (error) {
      renderMessages([]);
      setConversationHeader(null);
      toast(`Backend unavailable: ${error.message}`);
    }
  }

  if (sendBtn) sendBtn.addEventListener("click", sendMessage);
  if (newChatBtn) newChatBtn.addEventListener("click", createConversation);
  if (composer) {
    composer.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });
  }

  document.querySelectorAll("a.lv-nav-item, a.lv-dock-item").forEach((el) => {
    el.style.textDecoration = "none";
  });

  bootstrap();
})();
