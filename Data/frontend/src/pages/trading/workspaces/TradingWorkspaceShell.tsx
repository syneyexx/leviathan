import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AppShell } from "../../../layouts/AppShell";
import { TradingContextBar } from "./TradingContextBar";
import { useTradingContext } from "./useTradingContext";
import {
  getTradingWorkspace,
  resolveWorkspaceSurface,
  type TradingWorkspaceId,
} from "./workspaceConfig";
import "../../../styles/trading-workspaces.css";

export function TradingWorkspaceShell({
  workspaceId,
  children,
  overview,
}: {
  workspaceId: TradingWorkspaceId;
  children: ReactNode;
  /** Optional PRIMARY overview above the active surface */
  overview?: ReactNode;
}) {
  const workspace = getTradingWorkspace(workspaceId);
  const ctx = useTradingContext();
  const [params, setParams] = useSearchParams();
  const surface = resolveWorkspaceSurface(workspace, params.get("surface"));

  function selectSurface(id: string) {
    const next = new URLSearchParams(params);
    next.set("surface", id);
    setParams(next, { replace: true });
  }

  return (
    <AppShell layout="wide" pageClass="lv-app--trading lv-app--trading-workspace">
      <main className="lv-main lv-tp-main lv-tc-workspace">
        <header className="lv-tc-workspace__header">
          <div>
            <p className="lv-tc-workspace__crumb">
              <Link to="/trading/command-hub">Trading Center</Link>
              <span aria-hidden="true"> / </span>
              <span>{workspace.label}</span>
            </p>
            <h1 className="lv-tc-workspace__title">{workspace.title}</h1>
            <p className="lv-tc-workspace__subtitle">{workspace.subtitle}</p>
          </div>
          <div className="lv-tc-workspace__header-actions">
            <button
              type="button"
              className="lv-tc-btn"
              onClick={() => void ctx.refresh()}
              disabled={ctx.loading}
            >
              Refresh
            </button>
            <span
              className="lv-tc-badge lv-tc-badge--exec"
              title={`LIVE_TRADING_AVAILABLE=${ctx.liveTrading}`}
            >
              {ctx.executionLabel}
            </span>
          </div>
        </header>

        <TradingContextBar ctx={ctx} />

        <section className="lv-tc-status" aria-label="Trading Center Status">
          <h2 className="lv-tc-status__title">Trading Center Status</h2>
          <ul className="lv-tc-status__list">
            <li>
              <span>Trading Engine</span>
              <strong className="is-good">{ctx.loading ? "…" : "Ready"}</strong>
            </li>
            <li>
              <span>Market Data</span>
              <strong className="is-good">{ctx.loading ? "…" : "Online"}</strong>
            </li>
            <li>
              <span>Paper Trading</span>
              <strong className="is-good">Available</strong>
            </li>
            <li>
              <span>Live Trading</span>
              <strong className={ctx.liveTrading === "BLOCKED" ? "is-bad" : "is-warn"}>
                {ctx.liveTrading}
              </strong>
            </li>
            <li>
              <span>Risk Monitor</span>
              <strong className="is-good">Active</strong>
            </li>
          </ul>
        </section>

        {overview}

        <nav className="lv-tc-surfaces" aria-label={`${workspace.label} surfaces`}>
          {workspace.surfaces.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`lv-tc-surfaces__btn${surface.id === s.id ? " is-active" : ""}`}
              onClick={() => selectSurface(s.id)}
              data-level={s.level}
            >
              <span>{s.label}</span>
              <small>{s.level}</small>
            </button>
          ))}
        </nav>

        <div className="lv-tc-surface-body" data-surface={surface.id} data-level={surface.level}>
          {children}
        </div>
      </main>
    </AppShell>
  );
}
