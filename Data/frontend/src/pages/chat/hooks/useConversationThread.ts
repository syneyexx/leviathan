/**
 * useConversationThread — paginated messages + per-turn metadata hydration + race safety.
 */
import { useCallback, useRef, useState } from "react";
import { api } from "../../../api/client";
import { displayMessageContent, normalizeMessage } from "../../../api/chatContract";
import type { ChatTurn } from "../../../types/api";

export type ThreadMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string | null;
  pending?: boolean;
  error?: boolean;
  provisional?: boolean;
  turn?: ChatTurn | null;
};

export function useConversationThread() {
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [turnsByMessageId, setTurnsByMessageId] = useState<Record<string, ChatTurn>>({});
  const [hasMoreOlder, setHasMoreOlder] = useState(false);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [title, setTitle] = useState("New conversation");
  const genRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const conversationIdRef = useRef<string | null>(null);

  const applyTurns = useCallback((turns: Record<string, ChatTurn> | undefined) => {
    if (!turns) return;
    setTurnsByMessageId((prev) => ({ ...prev, ...turns }));
  }, []);

  const loadConversation = useCallback(async (conversationId: string | null) => {
    conversationIdRef.current = conversationId;
    const gen = ++genRef.current;
    abortRef.current?.abort();
    if (!conversationId) {
      setMessages([]);
      setTurnsByMessageId({});
      setHasMoreOlder(false);
      setNextBeforeId(null);
      setTitle("New conversation");
      return;
    }
    const abort = new AbortController();
    abortRef.current = abort;
    setLoading(true);
    try {
      const data = await api.getConversation(conversationId, {
        limit: 100,
        includeTurns: true,
        signal: abort.signal,
      });
      if (gen !== genRef.current || conversationIdRef.current !== conversationId) return;
      setTitle(data.conversation.title);
      const mapped: ThreadMessage[] = [];
      for (const item of data.messages || []) {
        const normalized = normalizeMessage(item);
        if (!normalized) continue;
        if (normalized.role !== "user" && normalized.role !== "assistant") continue;
        const turn = data.turns?.[String(normalized.id)] ?? null;
        mapped.push({
          id: normalized.id,
          role: normalized.role,
          content: displayMessageContent(normalized.content),
          created_at: normalized.created_at,
          turn,
        });
      }
      setMessages(mapped);
      applyTurns(data.turns);
      setHasMoreOlder(Boolean(data.has_more));
      setNextBeforeId(data.next_before_id ?? null);
    } catch (err) {
      if ((err as { name?: string })?.name === "AbortError") return;
      if (gen !== genRef.current) return;
      setMessages([]);
    } finally {
      if (gen === genRef.current) setLoading(false);
    }
  }, [applyTurns]);

  const loadOlder = useCallback(async () => {
    const conversationId = conversationIdRef.current;
    if (!conversationId || nextBeforeId == null || loadingOlder) return;
    const gen = genRef.current;
    setLoadingOlder(true);
    try {
      const data = await api.getConversation(conversationId, {
        limit: 100,
        beforeId: nextBeforeId,
        includeTurns: true,
      });
      if (gen !== genRef.current || conversationIdRef.current !== conversationId) return;
      const older: ThreadMessage[] = [];
      for (const item of data.messages || []) {
        const normalized = normalizeMessage(item);
        if (!normalized) continue;
        if (normalized.role !== "user" && normalized.role !== "assistant") continue;
        older.push({
          id: normalized.id,
          role: normalized.role,
          content: displayMessageContent(normalized.content),
          created_at: normalized.created_at,
          turn: data.turns?.[String(normalized.id)] ?? null,
        });
      }
      setMessages((prev) => {
        const seen = new Set(prev.map((m) => m.id));
        const merged = [...older.filter((m) => !seen.has(m.id)), ...prev];
        return merged;
      });
      applyTurns(data.turns);
      setHasMoreOlder(Boolean(data.has_more));
      setNextBeforeId(data.next_before_id ?? null);
    } finally {
      if (gen === genRef.current) setLoadingOlder(false);
    }
  }, [applyTurns, loadingOlder, nextBeforeId]);

  return {
    messages,
    setMessages,
    turnsByMessageId,
    hasMoreOlder,
    loading,
    loadingOlder,
    title,
    setTitle,
    loadConversation,
    loadOlder,
    conversationIdRef,
  };
}
