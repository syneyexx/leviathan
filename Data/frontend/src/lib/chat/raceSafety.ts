/**
 * Race-safety helpers for catalog / thread fetches.
 * Generation ids + AbortController: only the latest in-flight request may commit.
 */

export type GenerationGate = {
  /** Monotonic counter — bump before each request. */
  generation: number;
  /** Current AbortController for the latest request (if any). */
  controller: AbortController | null;
};

export function createGenerationGate(): GenerationGate {
  return { generation: 0, controller: null };
}

/**
 * Begin a new generation: aborts the previous controller and returns
 * `{ generation, signal }` for the new request.
 */
export function beginGeneration(gate: GenerationGate): {
  generation: number;
  signal: AbortSignal;
  controller: AbortController;
} {
  gate.controller?.abort();
  const controller = new AbortController();
  gate.controller = controller;
  gate.generation += 1;
  return {
    generation: gate.generation,
    signal: controller.signal,
    controller,
  };
}

/** True when this generation is still the latest (safe to commit state). */
export function isCurrentGeneration(gate: GenerationGate, generation: number): boolean {
  return gate.generation === generation;
}

/**
 * Commit guard: returns true iff the generation is current and the signal
 * was not aborted. Call before applying async results.
 */
export function mayCommit(
  gate: GenerationGate,
  generation: number,
  signal?: AbortSignal | null,
): boolean {
  if (!isCurrentGeneration(gate, generation)) return false;
  if (signal?.aborted) return false;
  return true;
}

export function abortGeneration(gate: GenerationGate): void {
  gate.controller?.abort();
  gate.controller = null;
}

/** Simple debounce helper used by catalog search. */
export function debounceMs<T extends unknown[]>(
  fn: (...args: T) => void,
  waitMs: number,
): ((...args: T) => void) & { cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const wrapped = ((...args: T) => {
    if (timer != null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, waitMs);
  }) as ((...args: T) => void) & { cancel: () => void };
  wrapped.cancel = () => {
    if (timer != null) {
      clearTimeout(timer);
      timer = null;
    }
  };
  return wrapped;
}
