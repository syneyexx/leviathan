import assert from "node:assert/strict";
import test from "node:test";

import {
  equalSpacingGuides,
  groupAabb,
  handleHitPx,
  handleScreenPx,
  layoutBoxFromScreen,
  measureBetween,
  resizeGroupMembers,
  resizeRect,
  roundLayoutBox,
  snapThresholdForDensity,
} from "../js/geometry.js";

const start = { left: 100, top: 50, width: 240, height: 120 };

function rightEdge(box) {
  return box.left + box.width;
}

function bottomEdge(box) {
  return box.top + box.height;
}

test("east drag +10: width+10, height/left/top frozen", () => {
  const next = resizeRect({ start, dir: "e", dx: 10, dy: 99 });
  assert.equal(next.width, 250);
  assert.equal(next.height, 120);
  assert.equal(next.left, 100);
  assert.equal(next.top, 50);
});

test("west drag dx negative: left decreases, right edge identical, height same", () => {
  const next = resizeRect({ start, dir: "w", dx: -10, dy: 40 });
  assert.equal(next.width, 250);
  assert.equal(next.height, 120);
  assert.equal(next.top, 50);
  assert.equal(rightEdge(next), rightEdge(start));
  assert.equal(next.left, 90);
});

test("west drag until minW: further dx does not move left; right stays", () => {
  const atMin = resizeRect({ start, dir: "w", dx: 300, minW: 16, minH: 16 });
  assert.equal(atMin.width, 16);
  assert.equal(rightEdge(atMin), rightEdge(start));
  const leftAtMin = atMin.left;
  const further = resizeRect({ start, dir: "w", dx: 500, minW: 16, minH: 16 });
  assert.equal(further.width, 16);
  assert.equal(further.left, leftAtMin);
  assert.equal(rightEdge(further), rightEdge(start));
  assert.equal(atMin.hitLimit, true);
  assert.equal(atMin.hitMinW, true);
});

test("north drag: top moves, bottom frozen, width same", () => {
  const next = resizeRect({ start, dir: "n", dx: 40, dy: -10 });
  assert.equal(next.height, 130);
  assert.equal(next.width, 240);
  assert.equal(next.left, 100);
  assert.equal(bottomEdge(next), bottomEdge(start));
  assert.equal(next.top, 40);
});

test("north until minH: further dy does not move top; bottom stays", () => {
  const atMin = resizeRect({ start, dir: "n", dy: 400, minW: 16, minH: 16 });
  assert.equal(atMin.height, 16);
  assert.equal(bottomEdge(atMin), bottomEdge(start));
  const further = resizeRect({ start, dir: "n", dy: 800, minW: 16, minH: 16 });
  assert.equal(further.top, atMin.top);
  assert.equal(bottomEdge(further), bottomEdge(start));
});

test("south drag: height grows, left/top/width frozen", () => {
  const next = resizeRect({ start, dir: "s", dx: -20, dy: 15 });
  assert.equal(next.height, 135);
  assert.equal(next.width, 240);
  assert.equal(next.left, 100);
  assert.equal(next.top, 50);
});

test("se corner free: w and h change, left/top frozen", () => {
  const next = resizeRect({ start, dir: "se", dx: 20, dy: 10 });
  assert.equal(next.width, 260);
  assert.equal(next.height, 130);
  assert.equal(next.left, 100);
  assert.equal(next.top, 50);
});

test("se corner with aspect: ratio preserved, top-left frozen", () => {
  const aspect = start.width / start.height;
  const next = resizeRect({ start, dir: "se", dx: 40, dy: 0, aspect });
  assert.ok(Math.abs(next.width / next.height - aspect) < 1e-9);
  assert.equal(next.left, 100);
  assert.equal(next.top, 50);
});

test("nw corner with aspect: bottom-right frozen", () => {
  const aspect = start.width / start.height;
  const next = resizeRect({ start, dir: "nw", dx: -20, dy: -10, aspect });
  assert.ok(Math.abs(next.width / next.height - aspect) < 1e-6);
  assert.ok(Math.abs(rightEdge(next) - rightEdge(start)) < 1e-6);
  assert.ok(Math.abs(bottomEdge(next) - bottomEdge(start)) < 1e-6);
});

test("Alt fromCenter: center stays", () => {
  const next = resizeRect({ start, dir: "e", dx: 20, fromCenter: true });
  assert.equal(next.width, 280);
  assert.ok(Math.abs(next.left + next.width / 2 - (start.left + start.width / 2)) < 1e-9);
  assert.ok(Math.abs(next.top + next.height / 2 - (start.top + start.height / 2)) < 1e-9);
});

test("start.left 0 is a real absolute left (not missing style)", () => {
  const origin = { left: 0, top: 80, width: 200, height: 100 };
  const next = resizeRect({ start: origin, dir: "w", dx: -10 });
  assert.equal(next.left, -10);
  assert.equal(rightEdge(next), 200);
  assert.equal(next.height, 100);
});

test("zoom 0.5 and zoom 2: same layout deltas (already converted)", () => {
  // Callers divide screen delta by zoom before calling resizeRect.
  const dxLayout = 10;
  const a = resizeRect({ start, dir: "e", dx: dxLayout });
  const b = resizeRect({ start, dir: "e", dx: dxLayout });
  assert.equal(a.width, b.width);
  assert.equal(a.left, b.left);
  const screenHalf = layoutBoxFromScreen({ left: 50, top: 20, width: 100, height: 40 }, 0.5);
  const screenDouble = layoutBoxFromScreen({ left: 200, top: 80, width: 400, height: 160 }, 2);
  assert.deepEqual(screenHalf, { left: 100, top: 40, width: 200, height: 80 });
  assert.deepEqual(screenDouble, { left: 100, top: 40, width: 200, height: 80 });
});

test("west/north at zoom 0.25 / 1 / 4: layout deltas identical after screen→layout convert", () => {
  for (const zoom of [0.25, 1, 4]) {
    const screenDx = -40;
    const screenDy = -20;
    const dx = screenDx / zoom;
    const dy = screenDy / zoom;
    const west = resizeRect({ start, dir: "w", dx, dy });
    const north = resizeRect({ start, dir: "n", dx, dy });
    assert.equal(west.top, start.top, `zoom ${zoom} west must not touch top`);
    assert.equal(west.height, start.height);
    assert.equal(rightEdge(west), rightEdge(start));
    assert.equal(north.left, start.left, `zoom ${zoom} north must not touch left`);
    assert.equal(north.width, start.width);
    assert.equal(bottomEdge(north), bottomEdge(start));
  }
});

test("west must not touch top; north must not touch left", () => {
  const west = resizeRect({ start, dir: "w", dx: -5, dy: -50 });
  assert.equal(west.top, start.top);
  const north = resizeRect({ start, dir: "n", dx: -50, dy: -5 });
  assert.equal(north.left, start.left);
});

test("fromCenter + aspect + min-size simultaneously", () => {
  const aspect = 2;
  const box = { left: 0, top: 0, width: 40, height: 20 };
  const next = resizeRect({
    start: box,
    dir: "se",
    dx: -100,
    dy: -100,
    aspect,
    fromCenter: true,
    minW: 16,
    minH: 8,
  });
  assert.equal(next.width, 16);
  assert.equal(next.height, 8);
  assert.ok(Math.abs(next.width / next.height - aspect) < 1e-9);
  assert.ok(Math.abs(next.left + next.width / 2 - 20) < 1e-6);
  assert.ok(Math.abs(next.top + next.height / 2 - 10) < 1e-6);
  assert.equal(next.hitLimit, true);
});

test("maxW soft clamp flashes hitLimit", () => {
  const next = resizeRect({ start, dir: "e", dx: 500, maxW: 280, minW: 16 });
  assert.equal(next.width, 280);
  assert.equal(next.hitMaxW, true);
  assert.equal(next.hitLimit, true);
});

test("roundLayoutBox rounds on commit", () => {
  const rounded = roundLayoutBox({ left: 10.4, top: 20.6, width: 100.2, height: 50.8 });
  assert.deepEqual(rounded, { left: 10, top: 21, width: 100, height: 51 });
});

test("measureBetween reports horizontal gap labels", () => {
  const a = { left: 0, top: 0, width: 10, height: 10, right: 10, bottom: 10 };
  const b = { left: 30, top: 0, width: 10, height: 10, right: 40, bottom: 10 };
  const m = measureBetween(a, b);
  assert.equal(m.dx, 20);
  assert.equal(m.labelX.value, 20);
});

test("groupAabb unions layout boxes", () => {
  const aabb = groupAabb([
    { left: 10, top: 20, width: 40, height: 30 },
    { left: 60, top: 10, width: 20, height: 50 },
  ]);
  assert.deepEqual(aabb, { left: 10, top: 10, width: 70, height: 50, right: 80, bottom: 60 });
});

test("multi-select proportional scale keeps relative geometry", () => {
  const members = [
    { left: 0, top: 0, width: 100, height: 50 },
    { left: 100, top: 0, width: 100, height: 50 },
  ];
  const next = resizeGroupMembers({
    members,
    primaryIndex: 0,
    dir: "e",
    dx: 100,
    mode: "scale",
    aspect: null,
  });
  assert.equal(next.length, 2);
  // Group width 200 → 300 (sx=1.5); heights unchanged without aspect on E-only group.
  assert.ok(Math.abs(next[0].width - 150) < 1e-6);
  assert.ok(Math.abs(next[1].width - 150) < 1e-6);
  assert.ok(Math.abs(next[1].left - 150) < 1e-6);
  assert.equal(next[0].top, 0);
});

test("multi-select independent only moves primary", () => {
  const members = [
    { left: 0, top: 0, width: 100, height: 50 },
    { left: 120, top: 10, width: 40, height: 40 },
  ];
  const next = resizeGroupMembers({
    members,
    primaryIndex: 0,
    dir: "e",
    dx: 20,
    mode: "independent",
  });
  assert.equal(next[0].width, 120);
  assert.equal(next[1].left, 120);
  assert.equal(next[1].width, 40);
});

test("image height:auto preservation: east without aspect leaves height unchanged", () => {
  // Pure width drag must not invent a new height — caller skips writing height.
  const next = resizeRect({ start, dir: "e", dx: 30, dy: 80 });
  assert.equal(next.height, start.height);
  assert.equal(next.width, 270);
  assert.equal(next.top, start.top);
});

test("handle hit targets stay ≥ 10px at 0.25 and 4 zoom", () => {
  assert.equal(handleScreenPx(0.25), 10);
  assert.equal(handleScreenPx(4), 10);
  assert.ok(handleHitPx(0.25).hit >= 10);
  assert.ok(handleHitPx(4).hit >= 10);
  assert.ok(handleHitPx(0.25).hit >= handleHitPx(1).hit);
});

test("snap density thresholds", () => {
  assert.equal(snapThresholdForDensity("off"), 0);
  assert.equal(snapThresholdForDensity("sparse", 6), 6);
  assert.equal(snapThresholdForDensity("dense", 6), 10);
});

test("equalSpacingGuides for three siblings", () => {
  const boxes = [
    { left: 0, top: 0, width: 10, height: 10 },
    { left: 20, top: 0, width: 10, height: 10 },
    { left: 40, top: 0, width: 10, height: 10 },
  ];
  const guides = equalSpacingGuides(boxes, "x");
  assert.ok(guides.some((g) => g.kind === "equal-spacing" && g.gap === 10));
});
