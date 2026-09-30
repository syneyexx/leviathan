/**
 * Leviathan V2 primary navigation — Screen 1 sidebar contract.
 *
 * Route truth for expandable group children is adapted from MAIN_MENU
 * (canonical product IA) where possible. V2 presentation metadata (icons,
 * Screen 1 labels) lives here — do not maintain a second independent route tree.
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
  | "hades"
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
 * Dashboard Screen 1 children — home + Taken.
 * Chat moved under Hades AI (Chat V2 Screen 1). Coding Agent remains
 * reachable via MAIN_MENU / router without forcing it into this rail.
 */
const DASHBOARD_CHILDREN: readonly V2NavChild[] = [
  { id: "dashboard-home", label: "Dashboard", to: "/", match: ["/"] },
  { id: "taken", label: "Taken", to: "/tasks", match: ["/tasks"] },
];

/** Research / Onderzoek & Kennis — full canonical submenu from MAIN_MENU. */
const RESEARCH_CHILDREN = v2ChildrenFromMainMenu("research");

/**
 * Hades AI — Chat V2 Screen 1 submenu.
 * Routes map to existing product surfaces; Prompts / Evaluations are
 * first-class thin V2 pages over real backend capabilities.
 *
 * MAIN_MENU places Agents under LLM. Hades → Agents still deep-links to
 * `/agents`, but LM owns active highlighting / auto-expand for that route
 * so Hades does not stay falsely active after navigation.
 */
const HADES_CHILDREN: readonly V2NavChild[] = [
  { id: "chat", label: "Chat", to: "/chat", match: ["/chat"] },
  { id: "reasoning", label: "Reasoning", to: "/cognition", match: ["/cognition"] },
  { id: "hades-agents", label: "Agents", to: "/agents", match: ["/agents"] },
  { id: "bibliotheek", label: "Bibliotheek", to: "/knowledge", match: ["/knowledge"] },
  { id: "prompts", label: "Prompts", to: "/prompts", match: ["/prompts"] },
  { id: "evaluations", label: "Evaluations", to: "/evaluations", match: ["/evaluations"] },
];

/**
 * LM — expandable group derived from MAIN_MENU("llm") (Modellen / Agents /
 * Training / Dataset Management / Offline Datasets / Statestieken).
 *
 * Canonical ownership for `/agents` is LM → Agents (MAIN_MENU authority).
 * Training / dataset / analytics routes keep dedicated top-level owners where
 * those Screen 1 rail items already exist; LM children still deep-link to them.
 */
const LLM_CHILDREN = v2ChildrenFromMainMenu("llm");

/**
 * Screen 1 primary rail. Deep-link destinations for Media / Plugin & Runtime /
 * Coding / etc. remain registered in the router and MAIN_MENU; they are not
 * deleted — they stay reachable from those pages' own surfaces.
 *
 * Agents is intentionally NOT a standalone top-level owner — MAIN_MENU places
 * it under LLM, and `/agents` must light LM → Agents only.
 */
export const V2_PRIMARY_NAV: readonly V2NavItem[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    to: "/",
    match: ["/", "/tasks"],
    expandable: true,
    icon: "dashboard",
    children: DASHBOARD_CHILDREN,
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
    id: "hades",
    label: "Hades AI",
    to: "/chat",
    match: ["/chat", "/cognition", "/prompts", "/evaluations"],
    expandable: true,
    icon: "hades",
    children: HADES_CHILDREN,
  },
  {
    id: "lm",
    label: "LM",
    to: "/models",
    match: ["/models", "/agents"],
    expandable: true,
    icon: "lm",
    children: LLM_CHILDREN,
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
  // Hades owns Chat/Reasoning/Prompts/Evaluations expansion.
  // On /agents LM is the owner (MAIN_MENU); Hades must not auto-expand.
  // On /knowledge Research stays the owner (canonical research IA).
  if (item.id === "hades") {
    return item.match.some((prefix) => pathMatchesPrefix(pathname, prefix));
  }
  if (item.id === "research") {
    return isV2NavItemActive(item, pathname);
  }
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
