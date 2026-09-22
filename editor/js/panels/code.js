/**
 * Leviathan Visual Builder — source code panel.
 */

import { FILES } from "../constants.js";
import { escapeHtml } from "../util.js";

export function createCode(ctx) {
  return {
    id: "code",
    title: "Code",
    zone: "bottom",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      const s = ctx.store.getState();
      return `${s.activeFile}|${s.uiEpoch || 0}`;
    },
    bind(host) {
      this.host = host;
      host.addEventListener("click", (event) => {
        const file = event.target.closest("[data-file]")?.dataset.file;
        if (!file) return;
        ctx.store.setState({ activeFile: file });
        ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
        ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
      });
      host.addEventListener("focusin", (event) => {
        if (event.target.dataset?.role === "code-area") ctx.commands.beginGesture("code");
      });
      host.addEventListener("input", (event) => {
        const area = event.target;
        if (area.dataset?.role !== "code-area") return;
        const file = ctx.store.getState().activeFile;
        if (file === "__content__") {
          try {
            ctx.content.setContentText(area.value);
          } catch {
            ctx.content.setStatus("Ongeldige JSON", "dirty");
          }
          return;
        }
        ctx.content.setFileText(file, area.value);
      });
      host.addEventListener("focusout", (event) => {
        if (event.target.dataset?.role === "code-area") ctx.commands.endGesture();
      });
    },
    render() {
      if (!this.host) return;
      const s = ctx.store.getState();
      const file = s.activeFile || "leviathan.css";
      const value = file === "__content__" ? JSON.stringify(s.content, null, 2) : s.files[file] || "";
      const area = this.host.querySelector("[data-role='code-area']");
      if (area && document.activeElement === area) return;
      const chips = [...FILES, "__content__"]
        .map((name) => {
          const label = name === "__content__" ? "content.json" : name;
          return `<button type="button" class="lvb-chip${name === file ? " is-on" : ""}" data-file="${name}">${label}</button>`;
        })
        .join("");
      this.host.innerHTML = `<div class="lvb-code-head"><span>${escapeHtml(file === "__content__" ? "lv-editor-content.json" : file)}</span><div class="lvb-chip-row">${chips}</div></div>
        <textarea data-role="code-area" spellcheck="false" wrap="off">${escapeHtml(value)}</textarea>`;
    },
  };
}
