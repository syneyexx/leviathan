/**
 * Leviathan Visual Builder — command registry + key dispatcher.
 */

import { fuzzyScore } from "./util.js";

const RECENT_KEY = "lvb.recent";

export function eventToSpec(event) {
  const parts = [];
  if (event.metaKey || event.ctrlKey) parts.push("Mod");
  if (event.shiftKey) parts.push("Shift");
  if (event.altKey) parts.push("Alt");
  let key = event.key;
  if (key === " ") key = "Space";
  if (key === "Esc") key = "Escape";
  if (key.length === 1) key = key.toUpperCase();
  if (["Control", "Shift", "Alt", "Meta"].includes(key)) return "";
  parts.push(key);
  return parts.join("+");
}

function normalize(spec) {
  return String(spec || "")
    .split("+")
    .map((part) => {
      const p = part.trim();
      if (/^mod|cmd|ctrl|meta$/i.test(p)) return "Mod";
      if (/^shift$/i.test(p)) return "Shift";
      if (/^alt|option$/i.test(p)) return "Alt";
      if (p.length === 1) return p.toUpperCase();
      if (/^esc$/i.test(p)) return "Escape";
      if (/^space$/i.test(p)) return "Space";
      return p;
    })
    .join("+");
}

export function createRegistry(ctx) {
  const commands = new Map();

  function readRecent() {
    try {
      const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      return Array.isArray(raw) ? raw : [];
    } catch {
      return [];
    }
  }

  function register({ id, title, keys, group = "Algemeen", run, allowTyping = false, palette = true }) {
    const list = keys == null ? [] : Array.isArray(keys) ? keys : [keys];
    commands.set(id, {
      id,
      title,
      keys: list.map(normalize).filter(Boolean),
      group,
      run,
      allowTyping,
      palette,
    });
  }

  function list() {
    return [...commands.values()];
  }

  function get(id) {
    return commands.get(id) || null;
  }

  function noteRecent(id) {
    const next = [id, ...readRecent().filter((item) => item !== id)].slice(0, 8);
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }

  function run(id) {
    const cmd = commands.get(id);
    if (!cmd) return;
    noteRecent(id);
    cmd.run();
  }

  function search(query) {
    const q = String(query || "").trim();
    const ranked = list()
      .filter((cmd) => cmd.palette)
      .map((cmd) => ({
        cmd,
        score: Math.max(fuzzyScore(q, cmd.title), fuzzyScore(q, cmd.id), fuzzyScore(q, cmd.keys.join(" "))),
      }))
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score);
    return ranked.map((item) => item.cmd);
  }

  function recent() {
    return readRecent().map((id) => commands.get(id)).filter(Boolean);
  }

  function isTyping(event) {
    const el = event.target;
    if (!(el instanceof Element)) return false;
    if (el.closest?.("#lvb-palette")) return true;
    const tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
  }

  function onKey(event) {
    if (!ctx.store.getState().enabled) return;
    if (ctx.palette?.isOpen?.()) {
      if (event.key === "Escape") {
        event.preventDefault();
        ctx.palette.close();
        return;
      }
      if (eventToSpec(event) !== "Mod+K") return;
    }
    const spec = eventToSpec(event);
    if (!spec) return;
    const typing = isTyping(event);
    for (const cmd of commands.values()) {
      if (!cmd.keys.includes(spec)) continue;
      if (typing && !cmd.allowTyping) continue;
      event.preventDefault();
      event.stopPropagation();
      run(cmd.id);
      return;
    }
  }

  function attach() {
    window.addEventListener("keydown", onKey, true);
  }

  return { register, list, get, run, search, recent, attach, onKey };
}
