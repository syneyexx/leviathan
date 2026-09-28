import { describe, expect, it } from "vitest";
import type { LiveBrainNode } from "./brain-live";
import {
  BRAIN_SPACE_MAX_NODE_ORBIT,
  BRAIN_SPACE_MAX_NODE_SPEED,
  BRAIN_SPACE_MAX_SYSTEM_SPEED,
  buildBrainSpaceProjection,
  createBrainSpaceAnimationLoop,
} from "./brain-space";

function denseNodes(count: number): LiveBrainNode[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `knowledge:${index}`,
    type: "knowledge.document",
    label: `Knowledge ${String(index).padStart(3, "0")}`,
    created_at: "2026-01-01T00:00:00Z",
    meta: {},
  }));
}

describe("bounded celestial density", () => {
  it("keeps a 250-node single domain inside the visual orbit budget", () => {
    const projection = buildBrainSpaceProjection(denseNodes(250), []);
    const all = projection.systems.flatMap((system) => system.nodes);
    expect(all).toHaveLength(250);
    expect(Math.max(...all.map((node) => node.orbit))).toBeLessThanOrEqual(
      BRAIN_SPACE_MAX_NODE_ORBIT,
    );
    expect(Math.max(...all.map((node) => Math.abs(node.speed)))).toBeLessThanOrEqual(
      BRAIN_SPACE_MAX_NODE_SPEED,
    );
    expect(
      Math.max(...projection.systems.map((system) => Math.abs(system.orbitSpeed))),
    ).toBeLessThanOrEqual(BRAIN_SPACE_MAX_SYSTEM_SPEED);
  });

  it("does not linearly increase radius with node count", () => {
    const hundred = buildBrainSpaceProjection(denseNodes(100), []);
    const twoHundred = buildBrainSpaceProjection(denseNodes(200), []);
    const max100 = Math.max(...hundred.systems[0].nodes.map((node) => node.orbit));
    const max200 = Math.max(...twoHundred.systems[0].nodes.map((node) => node.orbit));
    expect(max200 - max100).toBeLessThan(90);
  });
});

describe("calm animation clock", () => {
  it("uses real-time scale by default and never catches up a paused wall-clock gap", () => {
    const callbacks = new Map<number, FrameRequestCallback>();
    let next = 1;
    const loop = createBrainSpaceAnimationLoop({
      requestAnimationFrame: (cb) => {
        const id = next++;
        callbacks.set(id, cb);
        return id;
      },
      cancelAnimationFrame: (id) => {
        callbacks.delete(id);
      },
      onFrame: () => undefined,
    });
    const step = (at: number) => {
      const [[id, cb]] = [...callbacks.entries()];
      callbacks.delete(id);
      cb(at);
    };

    loop.start();
    step(1000);
    step(1016);
    expect(loop.getSimTime()).toBe(16);
    loop.setPaused(true);
    step(50_000);
    expect(loop.getSimTime()).toBe(16);
    loop.setPaused(false);
    step(80_000);
    expect(loop.getSimTime()).toBe(16);
    step(80_016);
    expect(loop.getSimTime()).toBe(32);
    loop.stop();
  });
});
