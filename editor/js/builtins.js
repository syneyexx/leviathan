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
  tab("panel-help", "Help / shortcuts", "Mod+/", "help");
  go("panel-code", "Codepaneel", "Mod+Alt+C", "Panelen", () => ctx.store.setState({ showCode: !ctx.store.getState().showCode }));
  go("preset-studio", "Layout studio", null, "Panelen", () => ctx.chrome.applyPreset("studio"));
  go("preset-focus", "Layout focus", null, "Panelen", () => ctx.chrome.applyPreset("focus"));
  go("preset-code", "Layout code", null, "Panelen", () => ctx.chrome.applyPreset("code"));
}
