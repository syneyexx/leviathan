/**
 * Leviathan Visual Builder — boot.
 * One module inject. Editor UI only; normal Leviathan runs do not load this file.
 */

import { createApi } from "./js/api.js";
import { registerBuiltins } from "./js/builtins.js";
import { createCamera } from "./js/camera.js";
import { createCommands } from "./js/commands.js";
import { FILES } from "./js/constants.js";
import { createContent } from "./js/content.js";
import { createChrome } from "./js/chrome.js";
import { createInteractions } from "./js/interactions.js";
import { createLayout } from "./js/layout.js";
import { createPalette } from "./js/palette.js";
import { createAi } from "./js/panels/ai.js";
import { createCode } from "./js/panels/code.js";
import { createComponents } from "./js/panels/components.js";
import { createHelp } from "./js/panels/help.js";
import { createInsert } from "./js/panels/insert.js";
import { createInspector } from "./js/panels/inspector.js";
import { createLayers } from "./js/panels/layers.js";
import { createMedia } from "./js/panels/media.js";
import { createTokensPanel } from "./js/panels/tokens.js";
import { createRegistry } from "./js/registry.js";
import { createSelection } from "./js/selection.js";
import { createStore } from "./js/state.js";
import { parseTokens } from "./js/util.js";
import { createWidgets } from "./js/widgets.js";

const apiOrigin =
  globalThis.document?.querySelector("script[data-lv-editor-api]")?.getAttribute("data-lv-editor-api") ||
  "http://127.0.0.1:5199";

const store = createStore({
  enabled: true,
  tool: "select",
  zoom: 1,
  panX: 0,
  panY: 0,
  snap: true,
  showGrid: false,
  showColumns: false,
  autoSave: true,
  breakpoint: "desktop",
  files: Object.fromEntries(FILES.map((name) => [name, ""])),
  saved: Object.fromEntries(FILES.map((name) => [name, ""])),
  dirtyFiles: Object.fromEntries(FILES.map((name) => [name, false])),
  content: { version: 2, entries: {}, nodes: [], components: [] },
  contentDirty: false,
  activeFile: "leviathan.css",
  status: "Start…",
  statusKind: "",
  showLeft: true,
  showRight: true,
  showCode: false,
  rightTab: "inspector",
  leftW: 260,
  rightW: 340,
  sel: "",
  selCount: 0,
  canUndo: false,
  canRedo: false,
  historyLabel: "",
  uiEpoch: 0,
});

const ctx = {
  apiOrigin,
  store,
  session: {
    selected: [],
    primary: null,
    hoverEl: null,
    phase: "idle",
    clipboard: null,
    inlineEl: null,
    uiEpoch: 0,
    aspectLock: false,
    aspect: 1,
    styleClipboard: null,
    link: { padding: true, margin: true, radius: true },
    layerQuery: "",
    layerState: new Map(),
    measure: { a: null, b: null },
    space: false,
    imageMode: "insert",
    applying: false,
    swallow: false,
    dragLayer: "",
  },
};

let tokenCache = { src: "", list: [] };
ctx.tokens = () => {
  const src = store.getState().files["tokens.css"] || "";
  if (src !== tokenCache.src) tokenCache = { src, list: parseTokens(src) };
  return tokenCache.list;
};

ctx.api = createApi(apiOrigin);
ctx.commands = createCommands(ctx);
ctx.selection = createSelection(ctx);
ctx.content = createContent(ctx);
ctx.camera = createCamera(ctx);
ctx.layout = createLayout(ctx);
ctx.widgets = createWidgets(ctx);
ctx.registry = createRegistry(ctx);
ctx.palette = createPalette(ctx);

const panels = [
  createLayers(ctx),
  createInspector(ctx),
  createInsert(ctx),
  createTokensPanel(ctx),
  createComponents(ctx),
  createAi(ctx),
  createHelp(ctx),
  createCode(ctx),
  createMedia(ctx),
];

ctx.chrome = createChrome(ctx, panels);
ctx.interactions = createInteractions(ctx);

function boot() {
  try {
    registerBuiltins(ctx);
    ctx.chrome.build();
    ctx.registry.attach();
    ctx.interactions.attach();
    ctx.camera.apply();
    ctx.content.loadAll().catch((err) => {
      ctx.content.setStatus(`API offline? Start EDIT_LAYOUT.bat — ${err.message || err}`, "dirty");
    });
  } catch (err) {
    ctx.content.setStatus(`Studio start mislukt: ${err?.message || err}`, "dirty");
  }
}

if (globalThis.document) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
