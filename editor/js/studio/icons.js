/**
 * LEVIATHAN STUDIO — inline SVG icon set (no CDN).
 */

const ICONS = {
  select: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M3 2.5 12.5 8l-4.2 1.2L7 13.5 3 2.5z"/></svg>`,
  hand: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M7 1.5a1 1 0 0 1 1 1V7h.5V3a1 1 0 1 1 2 0v4h.5V4a1 1 0 1 1 2 0v5.5a3.5 3.5 0 0 1-3.5 3.5H7A3.5 3.5 0 0 1 3.5 9V6a1 1 0 0 1 2 0v1H7V2.5a1 1 0 0 1 0-1z"/></svg>`,
  frame: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" d="M3 3h10v10H3z"/><path fill="currentColor" d="M2 2h2v2H2zm10 0h2v2h-2zM2 12h2v2H2zm10 0h2v2h-2z"/></svg>`,
  text: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M3 3h10v2H9.5v8h-3V5H3V3z"/></svg>`,
  measure: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" d="M2 12 12 2"/><path fill="currentColor" d="M3 11h2v2H3zm3-3h2v2H6zm3-3h2v2H9z"/></svg>`,
  undo: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.5" d="M4 7h6a3 3 0 1 1 0 6H8"/><path fill="currentColor" d="M4 4.5 1.5 7 4 9.5z"/></svg>`,
  redo: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.5" d="M12 7H6a3 3 0 1 0 0 6h2"/><path fill="currentColor" d="M12 4.5 14.5 7 12 9.5z"/></svg>`,
  save: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M3 2h8l2 2v10H3V2zm2 0v4h5V2H5zm0 7h6v4H5V9z"/></svg>`,
  menu: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M3 4h10v1.4H3zm0 3.3h10v1.4H3zm0 3.3h10V12H3z"/></svg>`,
  layers: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="m8 2 6 3-6 3-6-3 6-3zm0 7.2 5.2-2.6L8 12.2 2.8 6.6 8 9.2zm0 3 5.2-2.6L8 15.2 2.8 9.6 8 12.2z"/></svg>`,
  search: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.2" fill="none" stroke="currentColor" stroke-width="1.4"/><path stroke="currentColor" stroke-width="1.4" d="m10.2 10.2 3 3"/></svg>`,
  close: `<svg viewBox="0 0 16 16" aria-hidden="true"><path stroke="currentColor" stroke-width="1.6" d="m4 4 8 8M12 4 4 12"/></svg>`,
  chevron: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.5" d="m5 3 5 5-5 5"/></svg>`,
  warning: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 1.5 15 14H1L8 1.5zM7.2 6h1.6v3.5H7.2zm0 4.5h1.6V12H7.2z"/></svg>`,
  check: `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.6" d="m3.5 8.2 3 3 6-6"/></svg>`,
};

export function icon(name, { label = "" } = {}) {
  const svg = ICONS[name] || ICONS.menu;
  if (label) return `<span class="lvb-icon" role="img" aria-label="${label}">${svg}</span>`;
  return `<span class="lvb-icon" aria-hidden="true">${svg}</span>`;
}

export function iconNames() {
  return Object.keys(ICONS);
}
