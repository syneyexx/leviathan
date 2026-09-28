import { describe, expect, it } from "vitest";
import {
  centeredViewBox,
  clientPointToMeetViewBox,
  fitPointsTransform,
  zoomCenteredViewBoxAt,
} from "./brain-geometry";

describe("Brain viewport geometry", () => {
  it("maps pointer coordinates through xMidYMid meet letterboxing", () => {
    const point = clientPointToMeetViewBox(
      500,
      250,
      { left: 0, top: 0, width: 1000, height: 500 },
      { x: 100, y: 50, width: 400, height: 400 },
    );
    expect(point).not.toBeNull();
    expect(point!.x).toBeCloseTo(300, 6);
    expect(point!.y).toBeCloseTo(250, 6);
  });

  it("fits wide graph bounds instead of zooming farther into dense data", () => {
    const fitted = fitPointsTransform(
      [
        { x: -500, y: -120, radius: 10 },
        { x: 1500, y: 720, radius: 10 },
      ],
      1000,
      610,
      { padding: 50, minScale: 0.2, maxScale: 1 },
    );
    expect(fitted.scale).toBeLessThan(1);
    const left = -510 * fitted.scale + fitted.x;
    const right = 1510 * fitted.scale + fitted.x;
    expect(left).toBeGreaterThanOrEqual(49);
    expect(right).toBeLessThanOrEqual(951);
  });

  it("keeps the same world point anchored while zooming a cluster viewBox", () => {
    const baseWidth = 900;
    const baseHeight = 410;
    const oldScale = 1;
    const newScale = 2;
    const oldOffset = { x: 0, y: 0 };
    const world = { x: 225, y: 102.5 };
    const nextOffset = zoomCenteredViewBoxAt(
      baseWidth,
      baseHeight,
      oldScale,
      newScale,
      oldOffset,
      world,
    );
    const next = centeredViewBox(baseWidth, baseHeight, newScale, nextOffset);
    expect((world.x - next.x) / next.width).toBeCloseTo(0.25, 6);
    expect((world.y - next.y) / next.height).toBeCloseTo(0.25, 6);
  });
});
