/**
 * Applies saved visual-editor content in normal Leviathan runs.
 * No editor UI — admin tool stays separate (EDIT_LAYOUT.bat only).
 */
export type EditorBreakpoint = "desktop" | "tablet" | "mobile";

export type EditorContentEntry = {
  text?: string;
  html?: string;
  src?: string;
  alt?: string;
  hide?: boolean;
  locked?: boolean;
  position?: string;
  left?: string;
  top?: string;
  width?: string;
  height?: string;
  zIndex?: string | number;
  styles?: Record<string, string>;
  breakpoints?: Partial<Record<EditorBreakpoint, Record<string, string>>>;
};

export type EditorContentNode = {
  id: string;
  label?: string;
  parent?: string;
  html: string;
  componentId?: string;
  variant?: string;
  styles?: Record<string, string | undefined>;
};

export type EditorComponent = {
  id: string;
  name?: string;
  html: string;
  variant?: string;
  defaultStyles?: Record<string, string | undefined>;
};

export type EditorContentFile = {
  version?: number;
  entries?: Record<string, EditorContentEntry>;
  nodes?: EditorContentNode[];
  components?: EditorComponent[];
};

const CONTENT_URL = "/lv-editor-content.json";
const breakpointProps = new WeakMap<HTMLElement, string[]>();

function activeBreakpoint(): EditorBreakpoint {
  const width = window.innerWidth;
  if (width <= 640) return "mobile";
  if (width <= 1024) return "tablet";
  return "desktop";
}

function hasDirectText(el: Element): boolean {
  return [...el.childNodes].some(
    (n) => n.nodeType === Node.TEXT_NODE && Boolean(n.textContent?.trim()),
  );
}

function applyEntry(el: Element, entry: EditorContentEntry): void {
  if (entry.text != null && el.tagName !== "IMG") {
    if (el.childElementCount === 0 || hasDirectText(el)) {
      el.textContent = entry.text;
    }
  }
  if (entry.src && el.tagName === "IMG") {
    el.setAttribute("src", entry.src);
  }
  if (entry.alt != null && el.tagName === "IMG") {
    el.setAttribute("alt", entry.alt);
  }
  if (entry.styles) {
    for (const [key, value] of Object.entries(entry.styles)) {
      if (value != null && value !== "") {
        (el as HTMLElement).style.setProperty(key, value);
      }
    }
  }
  const htmlEl = el as HTMLElement;
  if (entry.position) htmlEl.style.position = entry.position;
  if (entry.left != null) htmlEl.style.left = entry.left;
  if (entry.top != null) htmlEl.style.top = entry.top;
  if (entry.width != null) htmlEl.style.width = entry.width;
  if (entry.height != null) htmlEl.style.height = entry.height;
  if (entry.zIndex != null) htmlEl.style.zIndex = String(entry.zIndex);
  if (entry.hide) htmlEl.style.display = "none";

  const previous = breakpointProps.get(htmlEl) ?? [];
  for (const prop of previous) {
    const base = entry.styles?.[prop];
    if (base) htmlEl.style.setProperty(prop, base);
    else htmlEl.style.removeProperty(prop);
  }
  breakpointProps.delete(htmlEl);

  const bp = activeBreakpoint();
  const overrides = bp === "desktop" ? undefined : entry.breakpoints?.[bp];
  if (!overrides) return;
  const applied: string[] = [];
  for (const [key, value] of Object.entries(overrides)) {
    if (value == null || value === "") continue;
    htmlEl.style.setProperty(key, value);
    applied.push(key);
  }
  if (applied.length) breakpointProps.set(htmlEl, applied);
}

function applyEntries(content: EditorContentFile): void {
  const entries = content.entries ?? {};
  for (const [selector, entry] of Object.entries(entries)) {
    let nodes: NodeListOf<Element>;
    try {
      nodes = document.querySelectorAll(selector);
    } catch {
      continue;
    }
    nodes.forEach((el) => applyEntry(el, entry));
  }
}

function mountNodes(content: EditorContentFile): void {
  const nodes = content.nodes ?? [];
  const liveIds = new Set(nodes.map((n) => n.id));

  document.querySelectorAll("[data-lvb-id]").forEach((el) => {
    const id = el.getAttribute("data-lvb-id");
    if (id && !liveIds.has(id)) el.remove();
  });

  for (const node of nodes) {
    let el = document.querySelector(`[data-lvb-id="${CSS.escape(node.id)}"]`) as HTMLElement | null;
    if (!el) {
      const wrap = document.createElement("div");
      wrap.innerHTML = node.html.trim();
      el = wrap.firstElementChild as HTMLElement | null;
      if (!el) continue;
      el.dataset.lvbId = node.id;
      if (node.label) el.dataset.lvbLabel = node.label;
      if (node.componentId) el.dataset.lvbComponentId = node.componentId;
      if (node.variant) el.dataset.lvbVariant = node.variant;
      const parent =
        (node.parent ? document.querySelector(node.parent) : null) ||
        document.querySelector(".lv-main") ||
        document.getElementById("root") ||
        document.body;
      parent.appendChild(el);
    }
    if (node.styles) {
      for (const [key, value] of Object.entries(node.styles)) {
        if (value != null && value !== "") el.style.setProperty(key, value);
      }
    }
  }
}

async function fetchContent(): Promise<EditorContentFile | null> {
  try {
    const res = await fetch(`${CONTENT_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as EditorContentFile;
  } catch {
    return null;
  }
}

/**
 * Start applying saved editor content in the live Leviathan app.
 * Skips when the admin visual editor overlay is present.
 */
export function startEditorContentRuntime(): void {
  // Admin editor injects this script tag — let that tool own live DOM while open.
  if (document.querySelector("script[data-lv-editor-api]")) {
    return;
  }

  let applying = false;
  let cached: EditorContentFile | null = null;

  const apply = () => {
    if (!cached || applying) return;
    applying = true;
    try {
      applyEntries(cached);
      mountNodes(cached);
    } finally {
      applying = false;
    }
  };

  const boot = async () => {
    cached = await fetchContent();
    if (!cached) return;
    const hasWork =
      Object.keys(cached.entries ?? {}).length > 0 || (cached.nodes ?? []).length > 0;
    if (!hasWork) return;

    apply();

    const root = document.getElementById("root");
    if (root) {
      let timer = 0;
      const mo = new MutationObserver(() => {
        window.clearTimeout(timer);
        timer = window.setTimeout(apply, 80);
      });
      mo.observe(root, { childList: true, subtree: true, characterData: true });
    }

    window.addEventListener("popstate", () => {
      window.setTimeout(apply, 50);
    });
    window.addEventListener("resize", () => {
      window.setTimeout(apply, 80);
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      void boot();
    });
  } else {
    void boot();
  }
}
