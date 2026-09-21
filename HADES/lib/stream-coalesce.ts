/** Coalesce fine-grained stream deltas into bounded React commits. */

export const STREAM_COMMIT_INTERVAL_MS = 40; // ~25 visual updates/sec

export const TERMINAL_RUN_EVENTS = new Set([
  "final_outcome",
  "error",
  "cancelled",
]);

export type StreamCoalesceMetrics = {
  incomingDeltas: number;
  commits: number;
  firstCommitImmediate: boolean;
};

export type StreamCoalescer = {
  pushDelta: (delta: string) => void;
  flush: (reason: string) => void;
  discard: () => void;
  snapshot: () => string;
  metrics: () => StreamCoalesceMetrics;
};

type ScheduleHandle = { cancel: () => void };

export function createStreamCoalescer(options: {
  intervalMs?: number;
  onCommit: (text: string, meta: { reason: string }) => void;
  schedule?: (fn: () => void, ms: number) => ScheduleHandle;
}): StreamCoalescer {
  const intervalMs = options.intervalMs ?? STREAM_COMMIT_INTERVAL_MS;
  const schedule =
    options.schedule
    ?? ((fn, ms) => {
      const id = setTimeout(fn, ms);
      return { cancel: () => clearTimeout(id) };
    });

  let committed = "";
  let pending = "";
  let first = true;
  let timer: ScheduleHandle | null = null;
  const metrics: StreamCoalesceMetrics = {
    incomingDeltas: 0,
    commits: 0,
    firstCommitImmediate: false,
  };

  const emit = (reason: string) => {
    if (timer) {
      timer.cancel();
      timer = null;
    }
    committed += pending;
    pending = "";
    metrics.commits += 1;
    options.onCommit(committed, { reason });
  };

  return {
    pushDelta(delta: string) {
      if (!delta) return;
      metrics.incomingDeltas += 1;
      if (first) {
        first = false;
        metrics.firstCommitImmediate = true;
        pending += delta;
        emit("first");
        return;
      }
      pending += delta;
      if (!timer) {
        timer = schedule(() => {
          timer = null;
          if (pending) emit("interval");
        }, intervalMs);
      }
    },
    flush(reason: string) {
      if (pending || reason === "terminal" || reason === "cancel") {
        emit(reason);
      }
    },
    discard() {
      pending = "";
      if (timer) {
        timer.cancel();
        timer = null;
      }
    },
    snapshot() {
      return committed + pending;
    },
    metrics() {
      return { ...metrics };
    },
  };
}
