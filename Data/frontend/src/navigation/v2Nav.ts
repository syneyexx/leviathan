/**
 * Leviathan V2 navigation — visual adapter over canonical MAIN_MENU.
 *
 * Route truth lives in menu.ts. V2 applies Screen 1 rail styling/order and the
 * approved Dashboard group exception, while preserving legacy submenu deep links.
 */

import {
  MAIN_MENU,
  normalizePath,
  type MainMenuItem,
  type SubMenuItem,
} from "./menu";

export type V2NavChild = {
  id: string;
  label: string;
  to: string;
  match?: readonly string[];
};

export type V2NavItem = {
  id: string;
  label: string;
  to: string;
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
  | "settings"
  | "media"
  | "coding";

const DASHBOARD_OWNED = new Set(["/", "/chat", "/tasks", "/status"]);

const DASHBOARD_GROUP: V2NavItem = {
  id: "dashboard",
  label: "Dashboard",
  to: "/",
  match: ["/", "/chat", "/tasks"],
  expandable: true,
  icon: "dashboard",
  children: [
    { id: "dashboard-home", label: "Dashboard", to: "/", match: ["/"] },
    { id: "chat", label: "Chat", to: "/chat", match: ["/chat"] },
    { id: "taken", label: "Taken", to: "/tasks", match: ["/tasks"] },
  ],
};

function childFromSub(item: SubMenuItem): V2NavChild {
  const path = item.to.split("?")[0] || item.to;
  return {
    id: item.id,
    label: item.label,
    to: item.to,
    match: [normalizePath(path)],
  };
}

function findMain(id: string): MainMenuItem {
  const item = MAIN_MENU.find((m) => m.id === id);
  if (!item) throw new Error(`MAIN_MENU missing section: ${id}`);
  return item;
}

function expandableFromMain(
  mainId: string,
  opts: { id: string; label: string; icon: V2NavIconId; to?: string; extraMatch?: string[]; extraChildren?: V2NavChild[] },
): V2NavItem {
  const main = findMain(mainId);
  const children = [
    ...main.submenu
      .filter((sub) => !DASHBOARD_OWNED.has(normalizePath(sub.to.split("?")[0] || sub.to)))
      .map(childFromSub),
    ...(opts.extraChildren ?? []),
  ];
  const match = [
    ...main.match.filter((m) => !DASHBOARD_OWNED.has(normalizePath(m))),
    ...(opts.extraMatch ?? []),
  ];
  return {
    id: opts.id,
    label: opts.label,
    to: opts.to ?? main.to,
    match: match.length ? match : [...main.match],
    expandable: children.length > 0,
    children: children.length ? children : undefined,
    icon: opts.icon,
  };
}

/**
 * Screen 1 rail order + full legacy submenu coverage.
 * Media is retained even when Screen 1 omits it (menu content > screenshot).
 */
export const V2_PRIMARY_NAV: readonly V2NavItem[] = [
  DASHBOARD_GROUP,
  {
    id: "agents",
    label: "Agents",
    to: "/agents",
    match: ["/agents"],
    icon: "agents",
  },
  (() => {
    const research = expandableFromMain("research", {
      id: "research",
      label: "Research",
      icon: "research",
    });
    // Data top-level owns /datasets active state; submenu link remains.
    const stripped = research.match.filter((m) => normalizePath(m) !== "/datasets");
    return { ...research, match: stripped.length ? stripped : research.match };
  })(),
  expandableFromMain("trading", {
    id: "trading",
    label: "Trading",
    icon: "trading",
  }),
  (() => {
    const lm = expandableFromMain("llm", {
      id: "lm",
      label: "LM",
      icon: "lm",
    });
    // Top-level Agents/Training/Data own these prefixes for active highlighting.
    const stripped = lm.match.filter(
      (m) => !["/agents", "/training", "/datasets", "/dataset-management", "/offline-datasets"].includes(normalizePath(m)),
    );
    return { ...lm, match: stripped.length ? stripped : ["/models"] };
  })(),
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
    expandable: true,
    icon: "data",
    children: [
      { id: "datasets", label: "Datasets", to: "/datasets", match: ["/datasets"] },
      {
        id: "dataset-management",
        label: "Dataset Management",
        to: "/dataset-management",
        match: ["/dataset-management"],
      },
      {
        id: "offline-datasets",
        label: "Offline Datasets",
        to: "/offline-datasets",
        match: ["/offline-datasets"],
      },
    ],
  },
  {
    id: "automation",
    label: "Automation",
    to: "/workflows",
    match: ["/workflows"],
    icon: "automation",
  },
  expandableFromMain("media", {
    id: "media",
    label: "Media",
    icon: "media",
  }),
  (() => {
    const system = expandableFromMain("runtime", {
      id: "system",
      label: "System",
      icon: "system",
      extraMatch: ["/coding"],
      extraChildren: [
        { id: "coding", label: "Coding Agent", to: "/coding", match: ["/coding"] },
      ],
    });
    // Automation owns /workflows for active highlight.
    const stripped = system.match.filter((m) => normalizePath(m) !== "/workflows");
    return { ...system, match: stripped.length ? stripped : system.match };
  })(),
  expandableFromMain("settings", {
    id: "settings",
    label: "Settings",
    icon: "settings",
  }),
];

export function allV2SubMenuRoutes(): readonly V2NavChild[] {
  return V2_PRIMARY_NAV.flatMap((item) => [...(item.children ?? [])]);
}

/** Legacy MAIN_MENU routes that must remain reachable via V2 (excl. Dashboard-owned). */
export function expectedPreservedLegacyRoutes(): readonly string[] {
  const routes = new Set<string>();
  for (const section of MAIN_MENU) {
    for (const sub of section.submenu) {
      const path = normalizePath(sub.to.split("?")[0] || sub.to);
      if (DASHBOARD_OWNED.has(path)) continue;
      routes.add(sub.to);
    }
  }
  routes.add("/coding");
  return [...routes];
}

export function pathMatchesPrefix(pathname: string, prefix: string): boolean {
  const path = normalizePath(pathname);
  const normalized = normalizePath(prefix);
  if (normalized === "/") return path === "/";
  return path === normalized || path.startsWith(`${normalized}/`);
}

export function isV2NavItemActive(item: V2NavItem, pathname: string): boolean {
  // Only the longest-matching rail item is active (Agents wins over LM on /agents).
  return findV2NavByPath(pathname).id === item.id;
}

export function findActiveV2Child(
  item: V2NavItem,
  pathname: string,
  search = "",
): V2NavChild | null {
  if (!item.children?.length) return null;
  const path = normalizePath(pathname);
  const searchParams = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);

  // Exact path + query match first (settings sections).
  for (const child of item.children) {
    const [pathPart, queryPart = ""] = child.to.split("?");
    const childPath = normalizePath(pathPart || "/");
    if (childPath !== path) continue;
    if (!queryPart) {
      if (childPath === "/" && path === "/") return child;
      if (childPath !== "/") return child;
      continue;
    }
    const wanted = new URLSearchParams(queryPart);
    let ok = true;
    for (const [key, value] of wanted.entries()) {
      if (searchParams.get(key) !== value) {
        ok = false;
        break;
      }
    }
    if (ok) return child;
  }

  for (const child of item.children) {
    const prefixes = child.match ?? [child.to.split("?")[0] || child.to];
    for (const prefix of prefixes) {
      if (normalizePath(prefix) === "/" && path === "/") return child;
    }
  }

  let best: V2NavChild | null = null;
  let bestLen = -1;
  for (const child of item.children) {
    const prefixes = child.match ?? [child.to.split("?")[0] || child.to];
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
