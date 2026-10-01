import { describe, expect, it, vi } from "vitest";
import {
  abortGeneration,
  beginGeneration,
  createGenerationGate,
  debounceMs,
  isCurrentGeneration,
  mayCommit,
} from "./raceSafety";

describe("raceSafety", () => {
  it("only the latest generation may commit", () => {
    const gate = createGenerationGate();
    const first = beginGeneration(gate);
    const second = beginGeneration(gate);
    expect(first.signal.aborted).toBe(true);
    expect(second.signal.aborted).toBe(false);
    expect(isCurrentGeneration(gate, first.generation)).toBe(false);
    expect(mayCommit(gate, second.generation, second.signal)).toBe(true);
    expect(mayCommit(gate, first.generation, first.signal)).toBe(false);
  });

  it("abortGeneration prevents commit", () => {
    const gate = createGenerationGate();
    const { generation, signal } = beginGeneration(gate);
    abortGeneration(gate);
    expect(signal.aborted).toBe(true);
    expect(mayCommit(gate, generation, signal)).toBe(false);
  });

  it("debounceMs coalesces calls", async () => {
    vi.useFakeTimers();
    const spy = vi.fn();
    const debounced = debounceMs(spy, 100);
    debounced("a");
    debounced("b");
    expect(spy).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("b");
    debounced.cancel();
    vi.useRealTimers();
  });
});
