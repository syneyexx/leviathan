/**
 * LEVIATHAN STUDIO — screen-space scene graph.
 * Colors map to studio tokens (ice blue accent, graphite).
 */

export const NodeType = {
  RECT: "rect",
  LINE: "line",
  CIRCLE: "circle",
  LABEL: "label",
};

export function rect(x, y, w, h, color, extra = {}) {
  return { type: NodeType.RECT, x, y, w, h, color, ...extra };
}

export function line(x1, y1, x2, y2, color, width = 1) {
  return { type: NodeType.LINE, x1, y1, x2, y2, color, width };
}

export function circle(x, y, r, color) {
  return { type: NodeType.CIRCLE, x, y, r, color };
}

export function label(x, y, text, color = [0.929, 0.949, 0.973, 1], align = "left") {
  return { type: NodeType.LABEL, x, y, text: String(text || ""), color, align };
}

/** Studio semantic colors as RGBA 0–1 */
export const COLORS = {
  accent: [0.447, 0.78, 1, 1],
  accentSoft: [0.447, 0.78, 1, 0.35],
  accentFill: [0.447, 0.78, 1, 0.1],
  // aliases for older gold references
  gold: [0.447, 0.78, 1, 1],
  goldSoft: [0.447, 0.78, 1, 0.35],
  goldFill: [0.447, 0.78, 1, 0.1],
  magenta: [1, 0.5, 0.535, 1],
  cyan: [0.447, 0.78, 1, 1],
  handle: [0.929, 0.949, 0.973, 1],
  ink: [0.031, 0.043, 0.063, 1],
  white: [0.929, 0.949, 0.973, 1],
  ghost: [0.447, 0.78, 1, 0.35],
  drop: [0.447, 0.78, 1, 0.25],
  marquee: [0.447, 0.78, 1, 0.12],
  success: [0.388, 0.839, 0.627, 1],
  warning: [0.953, 0.741, 0.412, 1],
  danger: [1, 0.498, 0.537, 1],
};

export function createScene() {
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
