/**
 * LEVIATHAN STUDIO — boot.
 * One module inject. Editor UI only; normal Leviathan runs do not load this file.
 */

import { createApi } from "./js/api.js";
import { registerBuiltins } from "./js/builtins.js";
import { createCamera } from "./js/camera.js";
import { seedStudioCapabilities, setCapability, Status } from "./js/capabilities/registry.js";
import { createIssues } from "./js/capabilities/issues.js";
import { createCommands } from "./js/commands.js";
import { FILES } from "./js/constants.js";
import { createContent } from "./js/content.js";
import { createChrome } from "./js/chrome.js";
import { createDiagnostics } from "./js/diagnostics.js";
import { createInteractions } from "./js/interactions.js";
import { createLayout } from "./js/layout.js";
import { createPages } from "./js/pages.js";
import { createPalette } from "./js/palette.js";
import { createAi } from "./js/panels/ai.js";
import { createCode } from "./js/panels/code.js";
import { createComponents } from "./js/panels/components.js";
import { createDiagnosticsPanel } from "./js/panels/diagnostics.js";
import { createHelp } from "./js/panels/help.js";
import { createHistoryPanel } from "./js/panels/history.js";
import { createInsert } from "./js/panels/insert.js";
import { createInspector } from "./js/panels/inspector.js";
import { createLayers } from "./js/panels/layers.js";
import { createMedia } from "./js/panels/media.js";
import { createPagesPanel } from "./js/panels/pages.js";
import { createProblemsPanel } from "./js/panels/problems.js";
import { createTokensPanel } from "./js/panels/tokens.js";
import { createRegistry } from "./js/registry.js";
import { createRenderer } from "./js/renderer.js";
import { createSelection } from "./js/selection.js";
import { createStore } from "./js/state.js";
import { createStudioFeatures } from "./js/studio/features.js";
import { createViewport } from "./js/studio/viewport.js";
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
  snapDensity: "sparse",
  showGrid: false,
  showColumns: false,
  autoSave: true,
  breakpoint: "desktop",
  viewMode: "design",
  page: typeof location !== "undefined" ? location.pathname || "/" : "/",
  files: Object.fromEntries(FILES.map((name) => [name, ""])),
  saved: Object.fromEntries(FILES.map((name) => [name, ""])),
  dirtyFiles: Object.fromEntries(FILES.map((name) => [name, false])),
  content: { version: 3, entries: {}, nodes: [], components: [], meta: { ambiguous: [] } },
  contentDirty: false,
  contentRevision: 0,
  contentHash: "",
  saveState: "clean",
  saveRevision: 0,
  savedRevision: 0,
  saveError: null,
  activeFile: "leviathan.css",
  status: "Start…",
  statusKind: "",
  showLeft: true,
  showRight: true,
  showCode: false,
  rightTab: "inspector",
  leftTab: "layers",
  leftW: 260,
  rightW: 320,
  codeH: 200,
  sel: "",
  selCount: 0,
  canUndo: false,
  canRedo: false,
  historyLabel: "",
  historyDepth: 0,
  issueCount: 0,
  issuesEpoch: 0,
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
    groupResizeMode: "scale",
    styleClipboard: null,
    link: { padding: true, margin: true, radius: true },
    layerQuery: "",
    layerState: new Map(),
    measure: { a: null, b: null, pinned: null },
    space: false,
    imageMode: "insert",
    applying: false,
    swallow: false,
    dragLayer: "",
    _snapGuides: null,
    _marquee: null,
    _resizeLive: null,
    dropEl: null,
    freePositionMode: false,
    rendererBackend: "dom",
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
ctx.renderer = createRenderer(ctx);
ctx.diagnostics = createDiagnostics(ctx);
ctx.pages = createPages(ctx);
ctx.viewport = createViewport(ctx);
ctx.studio = createStudioFeatures(ctx);
ctx.issues = createIssues(ctx);
seedStudioCapabilities();

const panels = [
  createPagesPanel(ctx),
  createLayers(ctx),
  createInsert(ctx),
  createComponents(ctx),
  createInspector(ctx),
  createTokensPanel(ctx),
  createAi(ctx),
  createProblemsPanel(ctx),
  createDiagnosticsPanel(ctx),
  createHelp(ctx),
  createCode(ctx),
  createHistoryPanel(ctx),
  createMedia(ctx),
];

ctx.chrome = createChrome(ctx, panels);
ctx.interactions = createInteractions(ctx);

function boot() {
  try {
    registerBuiltins(ctx);
    ctx.chrome.build();
    ctx.pages.attach();
    ctx.registry.attach();
    ctx.interactions.attach();
    ctx.camera.apply();

    const recovery = ctx.studio.readRecoveryDraft?.();
    if (recovery?.snap) {
      ctx.content.setStatus("Recovery draft beschikbaar (menu → Toon recovery draft)", "dirty");
    }

    ctx.api
      .boot()
      .then(() => ctx.content.loadAll())
      .then(() => {
        ctx.issues.schedule(400);
        setCapability("studio-shell", { status: Status.IMPLEMENTED, evidence: "chrome boot" });
        const caps = ctx.store.getState();
        void caps;
      })
      .catch((err) => {
        ctx.content.setStatus(`API offline? Start EDIT_LAYOUT.bat — ${err.message || err}`, "dirty");
        store.setState({ saveState: "offline" });
      });

    store.subscribe(() => {
      if (store.getState().contentDirty || store.getState().uiEpoch) ctx.issues.schedule();
    });
  } catch (err) {
    ctx.content.setStatus(`Studio start mislukt: ${err?.message || err}`, "dirty");
  }
}

if (globalThis.document) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}

export { ctx };
