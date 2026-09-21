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
              (cmd) => `<div class="lvb-help-row"><span>${escapeHtml(cmd.title)}</span><kbd>${escapeHtml(cmd.keys.join("  ") || "—")}</kbd></div>`,
            )
            .join("")}</div>`,
        )
        .join("");
      this.host.innerHTML = `<p class="lvb-muted">Studio-layout. Presets blijven in deze browser.</p>
        <div class="lvb-chip-row">
          <button type="button" class="lvb-chip" data-preset="studio">Studio</button>
          <button type="button" class="lvb-chip" data-preset="focus">Focus</button>
          <button type="button" class="lvb-chip" data-preset="code">Code</button>
        </div>
        ${body}`;
    },
  };
}
