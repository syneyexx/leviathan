import { Navigate, useLocation } from "react-router-dom";
import { TRADING_LEGACY_REDIRECTS } from "./workspaces/workspaceConfig";

/**
 * Redirect legacy / former four-workspace Trading Center paths.
 * Merges destination query with any inbound query (presentation state only).
 * Never imports obsolete page implementations.
 */
export function TradingLegacyRedirect({ from }: { from: string }) {
  const location = useLocation();
  const target = TRADING_LEGACY_REDIRECTS[from];
  if (!target) {
    return <Navigate to="/trading/agents" replace />;
  }
  const [path, destQuery = ""] = target.split("?");
  const inbound = new URLSearchParams(location.search);
  const merged = new URLSearchParams(destQuery);
  inbound.forEach((value, key) => {
    if (!merged.has(key)) merged.set(key, value);
  });
  const qs = merged.toString();
  return <Navigate to={qs ? `${path}?${qs}` : path} replace />;
}
