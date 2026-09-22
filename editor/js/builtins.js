/**
 * Leviathan Visual Builder — built-in commands.
 */

export function registerBuiltins(ctx) {
  const reg = ctx.registry;
  const go = (id, title, keys, group, run, extra = {}) => reg.register({ id, title, keys, group, run, ...extra });

  go("palette", "Commandopalet", "Mod+K", "Algemeen", () => ctx.palette.toggle(), { allowTyping: true });
  go("save", "Opslaan", "Mod+S", "Algemeen", () => ctx.content.saveAll().catch((err) => ctx.content.setStatus(String(err.message || err), "dirty")), { allowTyping: true });
  go("undo", "Ongedaan maken", "Mod+Z", "Geschiedenis", () => ctx.commands.undo(), { allowTyping: true });
  go("redo", "Opnieuw", ["Mod+Shift+Z", "Mod+Y"], "Geschiedenis", () => ctx.commands.redo(), { allowTyping: true });
  go("copy", "Kopiëren", "Mod+C", "Selectie", () => ctx.widgets.copySelection());
  go("paste", "Plakken", "Mod+V", "Selectie", () => ctx.widgets.pasteClipboard());
  go("duplicate", "Dupliceren", "Mod+D", "Selectie", () => ctx.widgets.duplicateSelection());
  go("delete", "Verwijderen", ["Delete", "Backspace"], "Selectie", () => ctx.widgets.deleteSelection());
  go("lock", "Lock / unlock", "Mod+Shift+L", "Selectie", () => ctx.widgets.toggleLock());
  go("forward", "Naar voren", "Mod+]", "Selectie", () => ctx.widgets.bumpZ(1));
  go("backward", "Naar achter", "Mod+[", "Selectie", () => ctx.widgets.bumpZ(-1));
  go("group", "Groeperen", "Mod+G", "Selectie", () => ctx.widgets.groupSelection());
  go("ungroup", "Degroeperen", "Mod+Shift+G", "Selectie", () => ctx.widgets.ungroupSelection());
  go("flip-h", "Spiegel horizontaal", null, "Selectie", () => ctx.widgets.flip("x"));
  go("flip-v", "Spiegel verticaal", null, "Selectie", () => ctx.widgets.flip("y"));
  go("copy-style", "Kopieer stijl", null, "Selectie", () => ctx.widgets.copyStyle());
  go("paste-style", "Plak stijl", null, "Selectie", () => ctx.widgets.pasteStyle());
  go("detach", "Detach component", null, "Componenten", () => ctx.widgets.detachComponent());
  go("component-create", "Maak component", "Mod+Alt+K", "Componenten", () => ctx.widgets.createComponent());
  go("preset-full", "Layout volledig", null, "Panelen", () => ctx.chrome.applyPreset("full"));

  go("tool-select", "Selecteren", "V", "Weergave", () => ctx.store.setState({ tool: "select" }));
  go("tool-hand", "Hand", "H", "Weergave", () => ctx.store.setState({ tool: "hand" }));
  go("tool-rotate", "Roteren", "R", "Weergave", () => ctx.store.setState({ tool: "rotate" }));
  go("tool-measure", "Meten", "M", "Weergave", () => ctx.store.setState({ tool: "measure" }));
  go("zoom-100", "Zoom 100%", "0", "Weergave", () => ctx.camera.reset());
  go("zoom-fit", "Zoom breedte", "1", "Weergave", () => ctx.camera.fitWidth());
  go("zoom-selection", "Zoom selectie", "2", "Weergave", () => ctx.camera.fitSelection());
  go("zoom-in", "Zoom in", "Mod+=", "Weergave", () => ctx.camera.zoomAt(innerWidth / 2, innerHeight / 2, ctx.store.getState().zoom * 1.1));
  go("zoom-out", "Zoom uit", "Mod+-", "Weergave", () => ctx.camera.zoomAt(innerWidth / 2, innerHeight / 2, ctx.store.getState().zoom / 1.1));
  go("grid", "Pixelgrid", "Mod+'", "Weergave", () => ctx.store.setState({ showGrid: !ctx.store.getState().showGrid }));
  go("columns", "Kolomgrid", "Mod+Shift+'", "Weergave", () => ctx.store.setState({ showColumns: !ctx.store.getState().showColumns }));
  go("snap", "Snap aan/uit", "Mod+;", "Weergave", () => {
    ctx.store.setState({ snap: !ctx.store.getState().snap });
    ctx.content.setStatus(ctx.store.getState().snap ? "Snap aan" : "Snap uit", "ok");
  });

  go("bp-desktop", "Viewport desktop", "Mod+Alt+1", "Responsive", () => ctx.camera.setBreakpoint("desktop"));
  go("bp-tablet", "Viewport tablet", "Mod+Alt+2", "Responsive", () => ctx.camera.setBreakpoint("tablet"));
  go("bp-mobile", "Viewport mobile", "Mod+Alt+3", "Responsive", () => ctx.camera.setBreakpoint("mobile"));

  const align = (id, title, key, mode) => go(id, title, key, "Layout", () => ctx.layout.align(mode));
  align("align-left", "Uitlijnen links", "Alt+L", "left");
  align("align-center", "Uitlijnen midden", "Alt+C", "center");
  align("align-right", "Uitlijnen rechts", "Alt+R", "right");
  align("align-top", "Uitlijnen boven", "Alt+T", "top");
  align("align-middle", "Uitlijnen midden verticaal", "Alt+M", "middle");
  align("align-bottom", "Uitlijnen onder", "Alt+B", "bottom");
  go("distribute-h", "Verdeel horizontaal", "Alt+Shift+H", "Layout", () => ctx.layout.distribute("x"));
  go("distribute-v", "Verdeel verticaal", "Alt+Shift+V", "Layout", () => ctx.layout.distribute("y"));

  go("insert-text", "Invoegen tekst", "T", "Invoegen", () => ctx.widgets.insertPreset("text"));
  go("insert-heading", "Invoegen titel", null, "Invoegen", () => ctx.widgets.insertPreset("heading"));
  go("insert-box", "Invoegen box", "B", "Invoegen", () => ctx.widgets.insertPreset("box"));
  go("insert-button", "Invoegen knop", null, "Invoegen", () => ctx.widgets.insertPreset("button"));
  go("insert-divider", "Invoegen lijn", null, "Invoegen", () => ctx.widgets.insertPreset("divider"));
  go("insert-image", "Image toevoegen", "I", "Invoegen", () => ctx.chrome.openMedia("insert"));
  go("replace-image", "Image vervangen", null, "Invoegen", () => {
    const el = ctx.session.primary;
    if (!el) {
      ctx.content.setStatus("Selecteer een image", "dirty");
      return;
    }
    if (el.tagName !== "IMG" && !ctx.widgets.hasBackgroundImage?.(el)) {
      ctx.content.setStatus("Selectie is geen image", "dirty");
      return;
    }
    ctx.chrome.openMedia("replace");
  });
  go("image-fit-menu", "Image Fit / Fill / Stretch", null, "Invoegen", () => ctx.widgets.offerImageFit?.(ctx.session.primary));
  go("image-fit", "Image fit (contain)", null, "Invoegen", () => ctx.widgets.applyImageFit?.(ctx.session.primary, "fit"));
  go("image-fill", "Image fill (cover)", null, "Invoegen", () => ctx.widgets.applyImageFit?.(ctx.session.primary, "fill"));
  go("image-stretch", "Image stretch", null, "Invoegen", () => ctx.widgets.applyImageFit?.(ctx.session.primary, "stretch"));
  go("image-original", "Image original size", null, "Invoegen", () => ctx.widgets.applyImageFit?.(ctx.session.primary, "original"));
  go("aspect-lock", "Aspect ratio lock", "Shift+A", "Layout", () => {
    const node = ctx.session.primary;
    ctx.session.aspectLock = !ctx.session.aspectLock;
    if (node) {
      const z = ctx.store.getState().zoom || 1;
      const r = node.getBoundingClientRect();
      ctx.session.aspect = r.height ? (r.width / z) / (r.height / z) : 1;
    }
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    ctx.content.setStatus(ctx.session.aspectLock ? "Aspect vast" : "Aspect vrij", "ok");
  });
  go("group-resize-scale", "Group resize: Scale group", null, "Layout", () => {
    ctx.session.groupResizeMode = "scale";
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    ctx.content.setStatus("Group resize: scale", "ok");
  });
  go("group-resize-independent", "Group resize: Resize independently", null, "Layout", () => {
    ctx.session.groupResizeMode = "independent";
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    ctx.content.setStatus("Group resize: independent", "ok");
  });
  go("snap-density", "Snap density cycle", null, "Weergave", () => {
    const order = ["off", "sparse", "dense"];
    const cur = ctx.store.getState().snapDensity || "sparse";
    const next = order[(order.indexOf(cur) + 1) % order.length];
    ctx.store.setState({ snapDensity: next, snap: next !== "off" });
    ctx.content.setStatus(`Snap: ${next}`, "ok");
  });
  go("clear-measure-pin", "Clear last measurement pin", null, "Weergave", () => {
    ctx.session.measure = { a: null, b: null, pinned: null, between: null };
    ctx.chrome.schedulePaint();
    ctx.content.setStatus("Measurement pin cleared", "ok");
  });
  go("orphan-cleanup", "Orphan media cleanup…", null, "Media", () => {
    const used = ctx.widgets.referencedAssetUrls?.() || new Set();
    ctx.chrome.openMedia("insert");
    ctx.content.setStatus(`Orphan cleanup: ${used.size} assets in use — select unused in Media (no auto-delete)`, "ok");
  });
  go("stress-lab", "Responsive Stress Lab", null, "Studio", () => {
    ctx.studio?.runStressLab?.().then((r) =>
      ctx.content.setStatus(`${r.findings?.length || 0} container-probe findings (geen viewport MQ)`, "ok"),
    );
  });
  go("stress-lab-multi", "Stress: multi-resize + image + undo", null, "Studio", () => {
    ctx.studio?.runMultiPageGestureStress?.().then((r) => {
      ctx.content.setStatus(r?.ok ? `Stress multi OK (${r.steps || 0} steps)` : `Stress multi: ${r?.error || "fail"}`, r?.ok ? "ok" : "dirty");
    });
  });
  go("recovery-show", "Show recovery draft", null, "Studio", () => {
    const d = ctx.studio?.readRecoveryDraft?.();
    ctx.content.setStatus(d ? `Recovery ${new Date(d.savedAt).toLocaleString()}` : "Geen recovery", d ? "ok" : "dirty");
  });
  go("panel-problems", "Problems panel", null, "Panelen", () => {
    ctx.store.setState({ showRight: true, rightTab: "problems" });
    ctx.chrome.invalidate("problems");
  });

  const tab = (id, title, key, panel) =>
    go(id, title, key, "Panelen", () => {
      ctx.store.setState({ showRight: true, rightTab: panel });
      ctx.chrome.invalidate(panel);
    });
  tab("panel-inspector", "Inspector", "Mod+Alt+I", "inspector");
  go("panel-layers", "Lagen", "Mod+Alt+L", "Panelen", () => ctx.store.setState({ showLeft: true }));
  tab("panel-insert", "Invoegen-paneel", null, "insert");
  tab("panel-tokens", "Tokens", "Mod+Alt+T", "tokens");
  tab("panel-components", "Componenten", null, "components");
  tab("panel-ai", "AI-instructie", "Mod+Alt+A", "ai");
  tab("panel-diagnostics", "Diagnostics", "Mod+Alt+D", "diagnostics");
  tab("panel-help", "Help / shortcuts", "Mod+/", "help");
  go("panel-code", "Codepaneel", "Mod+Alt+C", "Panelen", () => ctx.store.setState({ showCode: !ctx.store.getState().showCode }));
  go("preset-studio", "Layout studio", null, "Panelen", () => ctx.chrome.applyPreset("studio"));
  go("preset-focus", "Layout focus", null, "Panelen", () => ctx.chrome.applyPreset("focus"));
  go("preset-code", "Layout code", null, "Panelen", () => ctx.chrome.applyPreset("code"));

  for (const page of ctx.pages?.EDITOR_PAGES || []) {
    const id = `page-${(page.path || "/").replace(/\W+/g, "_") || "root"}`;
    go(id, `Pagina: ${page.label}`, null, "Pagina's", () => ctx.pages.go(page.path));
  }
}
