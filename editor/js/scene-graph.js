/**
 * Leviathan Visual Builder — screen-space scene graph.
 * Drawable primitives consumed by WebGPU or DOM paint backends.
 */

export const NodeType = {
  RECT: "rect",
  LINE: "line",
  CIRCLE: "circle",
  LABEL: "label",
};

/** @typedef {{ type:string, x:number, y:number, w:number, h:number, color:number[], stroke?:number[], strokeW?:number }} RectNode */
/** @typedef {{ type:string, x1:number, y1:number, x2:number, y2:number, color:number[], width?:number }} LineNode */
/** @typedef {{ type:string, x:number, y:number, r:number, color:number[] }} CircleNode */
/** @typedef {{ type:string, x:number, y:number, text:string, color?:number[], align?:string }} LabelNode */

export function rect(x, y, w, h, color, extra = {}) {
  return { type: NodeType.RECT, x, y, w, h, color, ...extra };
}

export function line(x1, y1, x2, y2, color, width = 1) {
  return { type: NodeType.LINE, x1, y1, x2, y2, color, width };
}

export function circle(x, y, r, color) {
  return { type: NodeType.CIRCLE, x, y, r, color };
}

export function label(x, y, text, color = [0.94, 0.78, 0.45, 1], align = "left") {
  return { type: NodeType.LABEL, x, y, text: String(text || ""), color, align };
}

export const COLORS = {
  gold: [0.839, 0.663, 0.341, 1],
  goldSoft: [0.839, 0.663, 0.341, 0.35],
  goldFill: [0.839, 0.663, 0.341, 0.08],
  magenta: [1, 0.31, 0.847, 1],
  cyan: [0.494, 0.784, 1, 1],
  handle: [0.941, 0.784, 0.459, 1],
  ink: [0.094, 0.063, 0.02, 1],
  white: [0.96, 0.94, 0.9, 1],
  ghost: [0.839, 0.663, 0.341, 0.35],
  drop: [0.494, 0.784, 1, 0.25],
  marquee: [0.839, 0.663, 0.341, 0.12],
};

/**
 * Mutable scene for one paint frame.
 */
export function createScene() {
  /** @type {Array<RectNode|LineNode|CircleNode|LabelNode>} */
  const nodes = [];
  return {
    clear() {
      nodes.length = 0;
      return this;
    },
    push(...items) {
      for (const item of items) if (item) nodes.push(item);
      return this;
    },
    get nodes() {
      return nodes;
    },
    get count() {
      return nodes.length;
    },
  };
}
