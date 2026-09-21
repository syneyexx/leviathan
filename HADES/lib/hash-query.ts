/** Hash-router query helpers for HADES deeplinks (`#/page?c=…&t=…&id=…`). */

export function readHashQuery(hash = typeof window !== "undefined" ? window.location.hash : ""): URLSearchParams {
  const raw = String(hash || "").replace(/^#/, "");
  const query = raw.includes("?") ? raw.slice(raw.indexOf("?") + 1) : "";
  return new URLSearchParams(query);
}

export function readHashSelection(keys: string[] = ["c", "t", "id"], hash?: string): string | null {
  const params = readHashQuery(hash);
  for (const key of keys) {
    const value = (params.get(key) || "").trim();
    if (value) return value;
  }
  return null;
}

export function hashPageId(hash = typeof window !== "undefined" ? window.location.hash : ""): string {
  const raw = String(hash || "").replace(/^#\/?/, "");
  return raw.split("?")[0] || "";
}
