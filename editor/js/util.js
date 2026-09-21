/**
 * Leviathan Visual Builder — pure helpers (CSS, tokens, fuzzy, color).
 */

export function escapeReg(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function uid(prefix = "lvb") {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
}

export function parseClamp(value) {
  const m = String(value || "")
    .trim()
    .match(/^clamp\(\s*([\d.]+)(px|vh|vw|%)\s*,\s*([\d.]+)(px|vh|vw|%)\s*,\s*([\d.]+)(px|vh|vw|%)\s*\)$/i);
  if (!m) return null;
  return {
    min: Number(m[1]),
    minUnit: m[2],
    preferred: Number(m[3]),
    preferredUnit: m[4],
    max: Number(m[5]),
    maxUnit: m[6],
  };
}

export function formatClamp(p) {
  return `clamp(${p.min}${p.minUnit}, ${p.preferred}${p.preferredUnit}, ${p.max}${p.maxUnit})`;
}

export function getVar(css, key) {
  const m = String(css || "").match(new RegExp(`(${escapeReg(key)}\\s*:\\s*)([^;]+);`));
  return m ? m[2].trim() : null;
}

export function setVar(css, key, value) {
  const re = new RegExp(`(${escapeReg(key)}\\s*:\\s*)([^;]+)(;)`);
  if (!re.test(css)) return css;
  return css.replace(re, `$1${value}$3`);
}

export function pxFromCssValue(value, fallback = 80) {
  const clamp = parseClamp(value);
  if (clamp) {
    if (clamp.preferredUnit === "px") return clamp.preferred;
    if (clamp.maxUnit === "px") return clamp.max;
    return fallback;
  }
  const m = String(value || "").match(/^([\d.]+)px$/i);
  return m ? Number(m[1]) : fallback;
}

export function cssFromPx(current, px, def) {
  const clamp = parseClamp(current || "");
  if (clamp) {
    const next = { ...clamp };
    next.preferred = px;
    next.preferredUnit = "px";
    if (next.maxUnit === "px" && next.max < px) next.max = px;
    if (next.minUnit === "px" && next.min > px) next.min = Math.max(def?.min || 0, Math.round(px * 0.75));
    return formatClamp(next);
  }
  return `${Math.round(px)}px`;
}

export const BEGIN = (sel) => `/* === LV-EDITOR:BEGIN ${sel} === */`;
export const END = (sel) => `/* === LV-EDITOR:END ${sel} === */`;

export function upsertOverride(css, selector, declarations) {
  const re = new RegExp(`${escapeReg(BEGIN(selector))}[\\s\\S]*?${escapeReg(END(selector))}\\n?`);
  if (!String(declarations || "").trim()) {
    return String(css || "").replace(re, "").replace(/\n{3,}/g, "\n\n");
  }
  const block = `${BEGIN(selector)}\n${selector} {\n${declarations}\n}\n${END(selector)}\n`;
  const source = String(css || "");
  if (re.test(source)) return source.replace(re, block);
  return `${source.replace(/\s*$/, "")}\n\n${block}`;
}

export function readOverrideDecls(css, selector) {
  if (!selector) return {};
  const re = new RegExp(
    `${escapeReg(BEGIN(selector))}[\\s\\S]*?${escapeReg(selector)}\\s*\\{([\\s\\S]*?)\\}[\\s\\S]*?${escapeReg(END(selector))}`,
  );
  const m = String(css || "").match(re);
  if (!m) return {};
  return parseDecls(m[1]);
}

export function parseDecls(text) {
  const out = {};
  const body = String(text || "");
  let buf = "";
  let depth = 0;
  const push = (chunk) => {
    const line = chunk.trim();
    if (!line) return;
    const idx = line.indexOf(":");
    if (idx <= 0) return;
    const k = line.slice(0, idx).trim();
    const v = line.slice(idx + 1).trim().replace(/;$/, "");
    if (k) out[k] = v;
  };
  for (const ch of body) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    if (ch === ";" && depth <= 0) {
      push(buf);
      buf = "";
      continue;
    }
    buf += ch;
  }
  push(buf);
  return out;
}

export function declsToText(decls) {
  return Object.entries(decls || {})
    .filter(([, v]) => v != null && String(v).trim() !== "")
    .map(([k, v]) => `  ${k}: ${v};`)
    .join("\n");
}

export function splitTopLevel(input) {
  const parts = [];
  let buf = "";
  let depth = 0;
  for (const ch of String(input || "")) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    if (ch === "," && depth === 0) {
      if (buf.trim()) parts.push(buf.trim());
      buf = "";
      continue;
    }
    buf += ch;
  }
  if (buf.trim()) parts.push(buf.trim());
  return parts;
}

export function parseShorthand(value) {
  const parts = String(value || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return { top: "", right: "", bottom: "", left: "" };
  if (parts.length === 1) return { top: parts[0], right: parts[0], bottom: parts[0], left: parts[0] };
  if (parts.length === 2) return { top: parts[0], right: parts[1], bottom: parts[0], left: parts[1] };
  if (parts.length === 3) return { top: parts[0], right: parts[1], bottom: parts[2], left: parts[1] };
  return { top: parts[0], right: parts[1], bottom: parts[2], left: parts[3] };
}

export function shorthandFromSides(sides, linked) {
  const top = sides.top || "0";
  const right = sides.right || top;
  const bottom = sides.bottom || top;
  const left = sides.left || right;
  if (linked || (top === right && right === bottom && bottom === left)) return top;
  if (top === bottom && left === right) return top === left ? top : `${top} ${left}`;
  if (left === right) return `${top} ${right} ${bottom}`;
  return `${top} ${right} ${bottom} ${left}`;
}

export function parseShadowList(input) {
  const chunks = splitTopLevel(input);
  if (!chunks.length) return [];
  return chunks.map((raw) => {
    const inset = /\binset\b/i.test(raw);
    let rest = raw.replace(/\binset\b/gi, "").trim();
    const colorMatch = rest.match(/(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\)|var\(--[^)]+\))$/);
    let color = "rgba(0,0,0,0.35)";
    if (colorMatch) {
      color = colorMatch[1];
      rest = rest.slice(0, colorMatch.index).trim();
    }
    const nums = rest.split(/\s+/).filter(Boolean);
    return {
      inset,
      x: nums[0] || "0px",
      y: nums[1] || "0px",
      blur: nums[2] || "0px",
      spread: nums[3] || "0px",
      color,
    };
  });
}

export function serializeShadows(layers) {
  return (layers || [])
    .filter((layer) => layer && (layer.x || layer.y || layer.blur || layer.color))
    .map((layer) => {
      const bits = [
        layer.inset ? "inset" : "",
        layer.x || "0px",
        layer.y || "0px",
        layer.blur || "0px",
        layer.spread || "0px",
        layer.color || "rgba(0,0,0,0.35)",
      ].filter(Boolean);
      return bits.join(" ");
    })
    .join(", ");
}

export function toHexColor(value) {
  const v = String(value || "").trim();
  if (/^#[0-9a-fA-F]{6}$/.test(v)) return v.toLowerCase();
  if (/^#[0-9a-fA-F]{3}$/.test(v)) return `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`.toLowerCase();
  const m = v.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
  if (m) {
    const h = (n) => Number(n).toString(16).padStart(2, "0");
    return `#${h(m[1])}${h(m[2])}${h(m[3])}`;
  }
  return "#ffffff";
}

export function alphaFromColor(value) {
  const m = String(value || "").match(/rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([\d.]+)\s*\)/i);
  if (m) return Math.max(0, Math.min(1, Number(m[1])));
  return 1;
}

export function colorWithAlpha(hex, alpha) {
  const h = toHexColor(hex);
  const r = parseInt(h.slice(1, 3), 16);
  const g = parseInt(h.slice(3, 5), 16);
  const b = parseInt(h.slice(5, 7), 16);
  const a = Math.max(0, Math.min(1, Number(alpha)));
  if (a >= 0.999) return h;
  return `rgba(${r}, ${g}, ${b}, ${Math.round(a * 100) / 100})`;
}

export function isTokenValue(value) {
  return /var\(\s*--lv-[\w-]+/.test(String(value || ""));
}

export function tokenName(value) {
  const m = String(value || "").match(/var\(\s*(--lv-[\w-]+)/);
  return m ? m[1] : "";
}

export function classifyToken(name, value) {
  const n = name || "";
  const v = String(value || "").trim();
  if (/gradient|shadow|glow/.test(n)) return "Effecten";
  if (/^#|rgba?\(|hsla?\(/i.test(v) && !/gradient/.test(v)) return "Kleuren";
  if (/font/.test(n) && /"|'|[A-Za-z]/.test(v) && !/clamp|px|em/.test(v)) return "Lettertypen";
  if (/clamp\(|\d+px|\d+rem|\d+em|\d+vh|\d+vw/.test(v)) return "Maten";
  return "Overig";
}

export function parseTokens(css) {
  const tokens = [];
  let section = "Algemeen";
  for (const line of String(css || "").split("\n")) {
    const heading = line.match(/^\s*([A-Z][A-Z0-9 /—-]{3,})\s*$/);
    if (heading && !line.includes("--")) section = heading[1].trim();
    const m = line.match(/^\s*(--lv-[\w-]+)\s*:\s*([^;]+);/);
    if (!m) continue;
    const name = m[1];
    const value = m[2].trim();
    tokens.push({
      name,
      value,
      section,
      group: classifyToken(name, value),
    });
  }
  return tokens;
}

export function fuzzyScore(query, text) {
  const q = String(query || "").trim().toLowerCase();
  const t = String(text || "").toLowerCase();
  if (!q) return 1;
  const direct = t.indexOf(q);
  if (direct >= 0) return 120 - direct;
  let qi = 0;
  let score = 0;
  let prev = -2;
  for (let i = 0; i < t.length && qi < q.length; i += 1) {
    if (t[i] !== q[qi]) continue;
    score += prev === i - 1 ? 8 : 3;
    if (i === 0 || /[^a-z0-9]/.test(t[i - 1])) score += 5;
    prev = i;
    qi += 1;
  }
  return qi === q.length ? score : 0;
}

export function numFrom(value) {
  const m = String(value || "").match(/-?[\d.]+/);
  return m ? Number(m[0]) : null;
}

export function swatchStore() {
  const key = "lvb.swatches";
  return {
    read() {
      try {
        const raw = JSON.parse(localStorage.getItem(key) || "[]");
        return Array.isArray(raw) ? raw.slice(0, 8) : [];
      } catch {
        return [];
      }
    },
    push(color) {
      const hex = toHexColor(color);
      const next = [hex, ...this.read().filter((c) => c !== hex)].slice(0, 8);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* ignore quota */
      }
      return next;
    },
  };
}
