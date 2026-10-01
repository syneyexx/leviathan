/**
 * Agent Overzicht drawers — Control Room advanced + thin wrappers.
 */
import { useEffect, useState, type ReactNode } from "react";
import { marketSimLabApi } from "../../../api/domains/marketSimLab";
import { UNMEASURED } from "../workspaces/commandHub/hubFormat";
import {
  AdvancedDrawer,
  CreatePortfolioDrawer,
} from "../workspaces/tradingDesk/TradingDeskDrawers";
import type { TradingDeskData } from "../workspaces/tradingDesk/useTradingDeskData";

export { AdvancedDrawer, CreatePortfolioDrawer };

export function ControlRoomDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    marketSimLabApi
      .marketSimInstitutionalControlRoom()
      .then((res) => {
        if (!cancelled) setSnapshot(res as Record<string, unknown>);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load control room");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;
  const overallStatus = String((snapshot as { overallStatus?: string } | null)?.overallStatus ?? UNMEASURED);
  const liveTrading = (snapshot as { liveTrading?: Record<string, unknown> } | null)?.liveTrading;
  const notes = ((snapshot as { notes?: unknown[] } | null)?.notes || []) as string[];

  return (
    <div className="lv-hub-drawer" role="dialog" aria-label="Control room snapshot">
      <div className="lv-hub-drawer__panel">
        <header>
          <div>
            <p className="lv-hub-drawer__kicker">Institutional</p>
            <h3>Control Room snapshot</h3>
          </div>
          <button type="button" className="lv-hub-btn" onClick={onClose}>
            Sluiten
          </button>
        </header>
        {loading ? <p className="lv-hub-empty">Laden…</p> : null}
        {error ? <p className="lv-hub-drawer__error">{error}</p> : null}
        {!loading && !error ? (
          <>
            <dl className="lv-hub-drawer__list">
              <div>
                <dt>Overall status</dt>
                <dd>{overallStatus}</dd>
              </div>
              <div>
                <dt>Live trading</dt>
                <dd>{JSON.stringify(liveTrading ?? UNMEASURED)}</dd>
              </div>
            </dl>
            {notes.length ? (
              <ul className="lv-hub-drawer__notes">
                {notes.slice(0, 8).map((n, i) => (
                  <li key={i}>{String(n)}</li>
                ))}
              </ul>
            ) : null}
            <pre className="lv-hub-drawer__raw">{JSON.stringify(snapshot, null, 2).slice(0, 4000)}</pre>
          </>
        ) : null}
      </div>
    </div>
  );
}

export function OrchestraDrawer({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="lv-hub-drawer" role="dialog" aria-label="Orchestra management">
      <div className="lv-hub-drawer__panel">
        <header>
          <div>
            <p className="lv-hub-drawer__kicker">Advanced</p>
            <h3>Orchestra management</h3>
          </div>
          <button type="button" className="lv-hub-btn" onClick={onClose}>
            Sluiten
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

export type { TradingDeskData };
