/**
 * Leviathan V2 primary navigation — Screen 1 sidebar contract.
 *
 * Route truth for expandable group children is adapted from MAIN_MENU
 * (canonical product IA). V2 presentation metadata (icons, Screen 1 labels)
 * lives here — do not maintain a second independent route tree.
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
  | "chat"
  | "tasks"
  | "agents"
  | "research"
  | "trading"
  | "lm"
  | "training"
  | "data"
  | "automation"
  | "system"
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
 * Dashboard Screen 1 children (subset of Hades AI submenu).
 * Kept explicit so Coding Agent stays reachable via MAIN_MENU / router
 * without forcing it into the V2 Dashboard rail.
 */
const DASHBOARD_CHILDREN: readonly V2NavChild[] = [
  { id: "dashboard-home", label: "Dashboard", to: "/", match: ["/"] },
  { id: "chat", label: "Chat", to: "/chat", match: ["/chat"] },
  { id: "taken", label: "Taken", to: "/tasks", match: ["/tasks"] },
];

/** Research / Onderzoek & Kennis — full canonical submenu from MAIN_MENU. */
const RESEARCH_CHILDREN = v2ChildrenFromMainMenu("research");

/**
 * Screen 1 primary rail. Deep-link destinations for Media / Plugin & Runtime /
 * Coding / etc. remain registered in the router and MAIN_MENU; they are not
 * deleted — they stay reachable from those pages' own surfaces.
 */
export const V2_PRIMARY_NAV: readonly V2NavItem[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    to: "/",
    match: ["/", "/chat", "/tasks"],
    expandable: true,
    icon: "dashboard",
    children: DASHBOARD_CHILDREN,
  },
  {
    id: "agents",
    label: "Agents",
    to: "/agents",
    match: ["/agents"],
    icon: "agents",
  },
  {
    id: "research",
    label: "Research",
    to: "/research",
    match: ["/research", "/brain", "/memory", "/knowledge", "/evidence"],
    expandable: true,
    icon: "research",
    children: RESEARCH_CHILDREN,
  },
  {
    id: "trading",
    label: "Trading",
    to: "/trading/simulatie",
    match: ["/trading"],
    icon: "trading",
  },
  {
    id: "lm",
    label: "LM",
    to: "/models",
    match: ["/models"],
    icon: "lm",
  },
  {
    id: "training",
    label: "Training",
    to: "/training",
    match: ["/training"],
    icon: "training",
  },
  {
    id: "data",
    label: "Data",
    to: "/datasets",
    match: ["/datasets", "/dataset-management", "/offline-datasets"],
    icon: "data",
  },
  {
    id: "automation",
    label: "Automation",
    to: "/workflows",
    match: ["/workflows"],
    icon: "automation",
  },
  {
    id: "system",
    label: "System",
    to: "/performance",
    match: ["/performance", "/console", "/tools", "/modules", "/skills", "/mcp"],
    icon: "system",
  },
  {
    id: "settings",
    label: "Settings",
    to: "/settings",
    match: ["/settings"],
    icon: "settings",
  },
] as const;

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
