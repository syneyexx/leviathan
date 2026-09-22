import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { RuntimeEvent } from "../types/api";

const DEFAULT_BUFFER = 500;

export type LiveEventsConnectionState = "connecting" | "open" | "reconnecting" | "closed" | "error";

/**
 * Shared live observability feed for Console / Performance / cross-page invalidation.
 * Prefer a single EventSource when possible; falls back to polling /api/events.
 */
export function useLiveEvents(opts?: {
  enabled?: boolean;
  bufferSize?: number;
  level?: string;
  category?: string;
  pollMs?: number;
}) {
  const enabled = opts?.enabled ?? true;
  const bufferSize = opts?.bufferSize ?? DEFAULT_BUFFER;
  const pollMs = opts?.pollMs ?? 2500;
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [connection, setConnection] = useState<LiveEventsConnectionState>("closed");
  const [latestSequence, setLatestSequence] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const cursorRef = useRef(0);
  const pausedRef = useRef(false);
  const mounted = useRef(true);
  const bufferRef = useRef<RuntimeEvent[]>([]);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  const mergeEvents = useCallback(
    (incoming: RuntimeEvent[]) => {
      if (!incoming.length) return;
      const bySeq = new Map<number, RuntimeEvent>();
      for (const e of bufferRef.current) bySeq.set(e.sequence, e);
      for (const e of incoming) bySeq.set(e.sequence, e);
      const merged = Array.from(bySeq.values()).sort((a, b) => a.sequence - b.sequence);
      const trimmed = merged.length > bufferSize ? merged.slice(merged.length - bufferSize) : merged;
      bufferRef.current = trimmed;
      const maxSeq = trimmed.length ? trimmed[trimmed.length - 1].sequence : cursorRef.current;
      cursorRef.current = Math.max(cursorRef.current, maxSeq);
      if (!pausedRef.current) {
        setEvents([...trimmed].reverse());
        setLatestSequence(cursorRef.current);
      }
    },
    [bufferSize],
  );

  const refreshHistory = useCallback(async () => {
    try {
      const data = await api.listEvents({
        limit: Math.min(bufferSize, 200),
        level: opts?.level,
        category: opts?.category,
      });
      if (!mounted.current) return;
      mergeEvents(data.events.slice().reverse());
      setLatestSequence(data.latest_sequence);
      cursorRef.current = Math.max(cursorRef.current, data.latest_sequence);
      setError(null);
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof Error ? err.message : "Events unavailable");
    }
  }, [bufferSize, mergeEvents, opts?.category, opts?.level]);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) {
      setConnection("closed");
      return;
    }

    let es: EventSource | null = null;
    let pollId = 0;
    let reconnectTimer = 0;
    let stopped = false;

    const startPoll = () => {
      if (pollId) window.clearInterval(pollId);
      pollId = window.setInterval(() => {
        if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
        void (async () => {
          try {
            const data = await api.listEvents({
              limit: 100,
              after: cursorRef.current,
            });
            if (!mounted.current || stopped) return;
            // API returns newest-first; normalize
            mergeEvents(data.events.slice().reverse());
            setConnection((c) => (c === "open" ? c : "open"));
            setError(null);
          } catch (err) {
            if (!mounted.current || stopped) return;
            setConnection("reconnecting");
            setError(err instanceof Error ? err.message : "Events reconnecting");
          }
        })();
      }, pollMs);
    };

    const connect = () => {
      setConnection((c) => (c === "open" ? "reconnecting" : "connecting"));
      const url = `/api/events/stream?last_event_id=${encodeURIComponent(String(cursorRef.current))}`;
      try {
        es = new EventSource(url);
      } catch {
        setConnection("reconnecting");
        startPoll();
        return;
      }

      es.addEventListener("event", (msg) => {
        if (!mounted.current || stopped) return;
        try {
          const data = JSON.parse((msg as MessageEvent).data) as RuntimeEvent;
          mergeEvents([data]);
          setConnection("open");
          setError(null);
        } catch {
          /* ignore malformed */
        }
      });
      es.addEventListener("connected", () => {
        setConnection("open");
      });
      es.addEventListener("heartbeat", () => {
        setConnection("open");
      });
      es.onerror = () => {
        if (stopped) return;
        setConnection("reconnecting");
        es?.close();
        es = null;
        // Fall back to polling + retry SSE later
        startPoll();
        reconnectTimer = window.setTimeout(() => {
          if (stopped || !mounted.current) return;
          window.clearInterval(pollId);
          pollId = 0;
          connect();
        }, 4000);
      };
    };

    void refreshHistory().then(() => {
      if (!stopped && mounted.current) connect();
    });

    const onVis = () => {
      if (document.visibilityState === "visible") void refreshHistory();
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      stopped = true;
      mounted.current = false;
      document.removeEventListener("visibilitychange", onVis);
      es?.close();
      if (pollId) window.clearInterval(pollId);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      setConnection("closed");
    };
  }, [enabled, mergeEvents, pollMs, refreshHistory]);

  const clearLocal = useCallback(() => {
    bufferRef.current = [];
    setEvents([]);
  }, []);

  return {
    events,
    connection,
    latestSequence,
    error,
    paused,
    setPaused,
    refresh: refreshHistory,
    clearLocal,
  };
}
