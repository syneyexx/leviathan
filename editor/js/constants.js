/**
 * Leviathan Visual Builder — shared constants.
 * Shell classes are resized via CSS variables only; never deleted or reparented.
 */

export const FILES = ["tokens.css", "leviathan.css", "pages.css", "chat.css"];

export const SHELL_LOCK = new Set([
  ".lv-app",
  ".lv-body",
  ".lv-header",
  ".lv-sidebar",
  ".lv-footer",
  ".lv-right",
  ".lv-main",
]);

export const REGIONS = [
  { id: "header", selector: ".lv-header", label: "Header", varKey: "--lv-header-height", edge: "s", min: 48, max: 180 },
  { id: "sidebar", selector: ".lv-sidebar", label: "Sidebar", varKey: "--lv-sidebar-width", edge: "e", min: 110, max: 340 },
  { id: "right", selector: ".lv-right", label: "Right panel", varKey: "--lv-right-panel-width", edge: "w", min: 120, max: 420 },
  { id: "footer", selector: ".lv-footer", label: "Footer", varKey: "--lv-footer-height", edge: "n", min: 44, max: 140 },
  { id: "main", selector: ".lv-main", label: "Main", varKey: null, edge: null, min: 0, max: 64 },
];

export const BREAKPOINTS = {
  desktop: { id: "desktop", label: "Desktop", width: null },
  tablet: { id: "tablet", label: "Tablet", width: 834 },
  mobile: { id: "mobile", label: "Mobile", width: 390 },
};

/** Camera — frontier range for pixel work and large shells. */
export const ZOOM_MIN = 0.1;
export const ZOOM_MAX = 8;
export const HISTORY_MAX = 100;

/** Interaction / paint tuning (screen px unless noted). */
export const SNAP_THRESHOLD = 6;
export const LAYER_ROW_H = 28;
export const HANDLE_DIRS = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
export const LAYOUT_STORAGE_KEY = "lvb.dock.v1";
export const TOOLS = ["select", "hand", "rotate", "measure"];

export const TEXTISH = new Set([
  "H1", "H2", "H3", "H4", "H5", "H6", "P", "SPAN", "LABEL", "BUTTON", "A", "LI",
  "FIGCAPTION", "SMALL", "STRONG", "EM", "BLOCKQUOTE", "TD", "TH", "DT", "DD",
]);
