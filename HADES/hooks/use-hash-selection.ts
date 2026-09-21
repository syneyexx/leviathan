/** Chat deeplink selection helpers (work package L / G). */

import { useEffect, useRef } from "react";

import { readHashSelection } from "@/lib/hash-query";

/**
 * Keep page selection aligned with `#/…?c=` / `id=` hash query across hashchange/popstate.
 */
export function useHashSelectionSync(
  keys: readonly string[],
  apply: (id: string) => void,
  enabled = true,
): void {
  const applyRef = useRef(apply);
  applyRef.current = apply;
  const keysKey = keys.join("\0");

  useEffect(() => {
    if (!enabled) return;
    const keyList = keysKey.split("\0").filter(Boolean);
    const onChange = () => {
      const deeplinkId = readHashSelection(keyList);
      if (!deeplinkId) return;
      applyRef.current(deeplinkId);
    };
    onChange();
    window.addEventListener("hashchange", onChange);
    window.addEventListener("popstate", onChange);
    return () => {
      window.removeEventListener("hashchange", onChange);
      window.removeEventListener("popstate", onChange);
    };
  }, [keysKey, enabled]);
}
