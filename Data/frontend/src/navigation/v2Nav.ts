/**
 * Leviathan V2 primary navigation — left sidebar contract.
 *
 * Route truth for expandable group children is adapted from MAIN_MENU
 * (canonical product IA). V2 presentation metadata (icons, labels) lives
 * here — do not maintain a second independent route tree.
 *
 * Exact left-nav groups (nothing else between):
 * Dashboard · LLM · Media Control · Trading Center · Onderzoek & Kennis ·
 * Plugins & Runtime · Instellingen
 */

import { MAIN_MENU, normalizePath, type SubMenuItem } from "./menu";

export type V2NavChild = {
  id: string;
  label: string;
  to: string;
  /** Exact or prefix match for active child highlighting. */
  match?: readonly string[];
};

export type V2NavItem = {
  id: string;
  label: string;
  to: string;
  /** Path prefixes that keep this item (or its group) active. */
  match: readonly string[];
  expandable?: boolean;
  children?: readonly V2NavChild[];
  icon: V2NavIconId;
};

export type V2NavIconId =
  | "dashboard"
  | "llm"
  | "media"
  | "trading"
  | "research"
  | "runtime"
  | "settings";

/** Map MAIN_MENU submenu rows into V2 child presentation nodes. */
export function v2ChildrenFromMainMenu(mainMenuId: string): readonly V2NavChild[] {
  const section = MAIN_MENU.find((item) => item.id === mainMenuId);
  if (!section) return [];
  return section.submenu.map((item: SubMenuItem) => {
    const pathOnly = item.to.split("?")[0] || item.to;
    return {
      id: item.id,
      label: item.label,
      to: item.to,
      match: [pathOnly],
    };
  });
}

/**
 * Build an expandable V2 group from a MAIN_MENU section.
 * Instellingen stays a single non-expandable link (no left-nav dropdown).
 */
function v2GroupFromMainMenu(
  mainMenuId: string,
  icon: V2NavIconId,
  options?: { expandable?: boolean; includeChildren?: boolean },
): V2NavItem {
  const section = MAIN_MENU.find((item) => item.id === mainMenuId);
  if (!section) {
    throw new Error(`MAIN_MENU section missing: ${mainMenuId}`);
  }
  const expandable = options?.expandable ?? true;
  const includeChildren = options?.includeChildren ?? expandable;
  return {
    id: section.id,
    label: section.label,
    to: section.to,
    match: section.match,
    expandable,
    icon,
    children: includeChildren ? v2ChildrenFromMainMenu(mainMenuId) : undefined,
  };
}

/**
 * Screen 1 primary rail — exact canonical IA from MAIN_MENU.
 * Deep-link destinations not listed here remain registered in the router.
 */
export const V2_PRIMARY_NAV: readonly V2NavItem[] = [
  v2GroupFromMainMenu("dashboard", "dashboard"),
  v2GroupFromMainMenu("llm", "llm"),
  v2GroupFromMainMenu("media", "media"),
  v2GroupFromMainMenu("trading", "trading"),
  v2GroupFromMainMenu("research", "research"),
  v2GroupFromMainMenu("runtime", "runtime"),
  v2GroupFromMainMenu("settings", "settings", { expandable: false, includeChildren: false }),
];

export function pathMatchesPrefix(pathname: string, prefix: string): boolean {
  const path = normalizePath(pathname);
  const normalized = normalizePath(prefix);
  if (normalized === "/") return path === "/";
  return path === normalized || path.startsWith(`${normalized}/`);
}

export function isV2NavItemActive(item: V2NavItem, pathname: string): boolean {
  return item.match.some((prefix) => pathMatchesPrefix(pathname, prefix));
}

export function findActiveV2Child(
  item: V2NavItem,
  pathname: string,
): V2NavChild | null {
  if (!item.children?.length) return null;
  const path = normalizePath(pathname);

  // Prefer exact "/" only for the dashboard home child.
  for (const child of item.children) {
    const prefixes = child.match ?? [child.to];
    for (const prefix of prefixes) {
      if (normalizePath(prefix) === "/" && path === "/") return child;
    }
  }

  let best: V2NavChild | null = null;
  let bestLen = -1;
  for (const child of item.children) {
    const prefixes = child.match ?? [child.to];
    for (const prefix of prefixes) {
      const normalized = normalizePath(prefix);
      if (normalized === "/") continue;
      if (path === normalized || path.startsWith(`${normalized}/`)) {
        if (normalized.length > bestLen) {
          best = child;
          bestLen = normalized.length;
        }
      }
    }
  }
  return best;
}

/** Expandable groups auto-open when their match prefixes are active. */
export function shouldAutoExpandV2Group(item: V2NavItem, pathname: string): boolean {
  if (!item.expandable) return false;
  return isV2NavItemActive(item, pathname);
}

export function findV2NavByPath(pathname: string): V2NavItem {
  let best: V2NavItem | null = null;
  let bestLen = -1;
  for (const item of V2_PRIMARY_NAV) {
    for (const prefix of item.match) {
      const normalized = normalizePath(prefix);
      if (normalized === "/") {
        if (normalizePath(pathname) === "/" && bestLen < 1) {
          best = item;
          bestLen = 1;
        }
        continue;
      }
      if (pathMatchesPrefix(pathname, normalized) && normalized.length > bestLen) {
        best = item;
        bestLen = normalized.length;
      }
    }
  }
  return best ?? V2_PRIMARY_NAV[0];
}
