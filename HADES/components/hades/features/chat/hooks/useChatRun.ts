"use client";

import { useCallback, useEffect, useRef } from "react";
import { API_BASE, hadesApi } from "@/lib/hades-api";
import type { ChatToolCall, HighLevelExecutionEvent } from "@/components/hades/features/chat/types";
import { createStreamCoalescer, TERMINAL_RUN_EVENTS, type StreamCoalescer } from "@/lib/stream-coalesce";
import { CHAT_RUN_EVENT_POLL_FALLBACK_MS } from "@/lib/ui-poll-intervals";

export type ChatRunProgress = {
  events: HighLevelExecutionEvent[];
  tools: ChatToolCall[];
  streamDelta: string;
  streamText?: string;
  target?: string;
  routeProfile?: string;
  modelUsage?: Record<string, unknown>;
  streamFlush?: boolean;
};

export function useChatRun({ onProgress }: { onProgress: (progress: ChatRunProgress) => void }) {
  const progressRef = useRef(onProgress);
  const stopRef = useRef<() => void>(() => undefined);
  const runIdRef = useRef<string | null>(null);
  progressRef.current = onProgress;

  const stop = useCallback(() => stopRef.current(), []);

  const cancelRun = useCallback(async (runId?: string) => {
    const id = runId || runIdRef.current;
    stop();
    if (!id) return;
    try {
      await fetch(`${API_BASE}/runs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
    } catch {
      // UI already left the generating state; backend close is best-effort.
    }
  }, [stop]);

  const start = useCallback((requestId: string) => {
    stopRef.current();
    runIdRef.current = requestId;
    let afterSequence = 0;
    let poll: number | undefined;
    let firstFrameTimer: number | undefined;
    let streamHealthy = false;
    let lastCommitted = "";
    const controller = new AbortController();

    const coalescer: StreamCoalescer = createStreamCoalescer({
      onCommit: (text, meta) => {
        const delta = text.slice(lastCommitted.length);
        lastCommitted = text;
        progressRef.current({
          events: [],
          tools: [],
          streamDelta: delta,
          streamText: text,
          streamFlush: meta.reason === "terminal" || meta.reason === "cancel" || meta.reason === "first",
        });
      },
    });

    const applyEvents = (events: HighLevelExecutionEvent[], latestSequence?: number) => {
      if (!events.length || controller.signal.aborted) return;
      if (typeof latestSequence === "number" && Number.isFinite(latestSequence)) {
        afterSequence = Math.max(afterSequence, latestSequence);
      } else {
        const sequences = events.map((event) => Number(event.sequence) || 0).filter((sequence) => sequence > 0);
        if (sequences.length) afterSequence = Math.max(afterSequence, ...sequences);
      }
      const tools = events
        .filter((event) => event.type === "tool_status")
        .map((event) => (event.payload || {}) as ChatToolCall);
      const streamEvents = events.filter((event) => event.type === "stream_delta");
      for (const event of streamEvents) {
        coalescer.pushDelta(String(event.payload?.delta || ""));
      }
      const terminal = events.some((event) => TERMINAL_RUN_EVENTS.has(String(event.type)));
      if (terminal) coalescer.flush("terminal");
      const route = [...events].reverse().find((event) => event.type === "route_chosen")?.payload;
      const modelUsage = [...events].reverse().find((event) => event.type === "model_usage")?.payload;
      const nonStream = events.filter((event) => event.type !== "stream_delta");
      if (!nonStream.length && !terminal) return;
      progressRef.current({
        events: nonStream,
        tools,
        streamDelta: "",
        streamText: coalescer.snapshot(),
        target: route?.target ? String(route.target) : undefined,
        routeProfile: route?.profile ? String(route.profile) : undefined,
        modelUsage,
        streamFlush: terminal,
      });
    };

    const startPollFallback = () => {
      if (poll || controller.signal.aborted) return;
      poll = window.setInterval(() => {
        void hadesApi.runEvents(requestId, afterSequence)
          .then((payload) => applyEvents(
            (payload.events || []) as HighLevelExecutionEvent[],
            payload.latest_sequence,
          ))
          .catch(() => undefined);
      }, CHAT_RUN_EVENT_POLL_FALLBACK_MS);
    };

    void hadesApi.openRunEventStream(requestId, {
      after: afterSequence,
      signal: controller.signal,
      onEvent: (event) => {
        streamHealthy = true;
        if (poll) {
          window.clearInterval(poll);
          poll = undefined;
        }
        if (firstFrameTimer) {
          window.clearTimeout(firstFrameTimer);
          firstFrameTimer = undefined;
        }
        const sequence = Number(event.sequence);
        applyEvents([event as HighLevelExecutionEvent], Number.isFinite(sequence) ? sequence : undefined);
      },
    }).catch(() => {
      if (!controller.signal.aborted && !streamHealthy) startPollFallback();
    });

    firstFrameTimer = window.setTimeout(() => {
      if (!controller.signal.aborted && !streamHealthy) startPollFallback();
    }, 800);

    stopRef.current = () => {
      coalescer.discard();
      controller.abort();
      if (poll) window.clearInterval(poll);
      if (firstFrameTimer) window.clearTimeout(firstFrameTimer);
      stopRef.current = () => undefined;
    };
  }, []);

  useEffect(() => stop, [stop]);

  return { start, stop, cancelRun };
}
