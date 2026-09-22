/**
 * Leviathan Visual Builder — shortcut help, generated from the registry.
 */

import { escapeHtml } from "../util.js";

export function createHelp(ctx) {
  return {
    id: "help",
    title: "Help",
    zone: "right",
    place: "dock",
    host: null,
    _sig: null,
    signature() {
      return String(ctx.registry.list().length);
    },
    bind(host) {
      this.host = host;
      host.addEventListener("click", (event) => {
        const preset = event.target.closest("[data-preset]")?.dataset.preset;
        if (preset) ctx.chrome.applyPreset(preset);
        const run = event.target.closest("[data-run]")?.dataset.run;
        if (run) ctx.registry.run(run);
      });
    },
    render() {
      if (!this.host) return;
      const groups = new Map();
      for (const cmd of ctx.registry.list()) {
        if (!groups.has(cmd.group)) groups.set(cmd.group, []);
        groups.get(cmd.group).push(cmd);
      }
      const body = [...groups.entries()]
        .map(
          ([group, cmds]) => `<div class="lvb-section">${escapeHtml(group)}</div><div class="lvb-help-list">${cmds
            .map(
              (cmd) => `<button type="button" class="lvb-help-row" data-run="${escapeHtml(cmd.id)}"><span>${escapeHtml(cmd.title)}</span><kbd>${escapeHtml(cmd.keys.join("  ") || "—")}</kbd></button>`,
            )
            .join("")}</div>`,
        )
        .join("");
      this.host.innerHTML = `<p class="lvb-muted">Frontier studio met WebGPU chrome (DOM fallback). Klik een rij om het commando te draaien. Presets blijven in deze browser.</p>
        <div class="lvb-section">Gestures</div>
        <div class="lvb-help-list">
          <div class="lvb-help-row"><span>Shift + resize</span><kbd>aspect</kbd></div>
          <div class="lvb-help-row"><span>Alt + resize</span><kbd>from center</kbd></div>
          <div class="lvb-help-row"><span>Alt + drag start</span><kbd>dupliceren</kbd></div>
          <div class="lvb-help-row"><span>Ctrl/⌘ + drag</span><kbd>reparent</kbd></div>
          <div class="lvb-help-row"><span>Alt + hover</span><kbd>afstand meten</kbd></div>
          <div class="lvb-help-row"><span>Shift + rotate</span><kbd>15°</kbd></div>
        </div>
        <div class="lvb-section">Studio</div>
        <div class="lvb-help-list">
          <div class="lvb-help-row"><span>Pagina-switcher</span><kbd>top bar</kbd></div>
          <div class="lvb-help-row"><span>Diagnostics</span><kbd>Mod+Alt+D</kbd></div>
          <div class="lvb-help-row"><span>WebGPU / DOM paint</span><kbd>auto</kbd></div>
        </div>
        <div class="lvb-chip-row">
          <button type="button" class="lvb-chip" data-preset="studio">Studio</button>
          <button type="button" class="lvb-chip" data-preset="focus">Focus</button>
          <button type="button" class="lvb-chip" data-preset="code">Code</button>
          <button type="button" class="lvb-chip" data-preset="full">Volledig</button>
        </div>
        ${body}`;
    },
  };
}
