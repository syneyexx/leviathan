import type { AgentDefinition, MarketSimPaperDeployment, PortfolioStrategyAllocation } from "../../../types/api";
import { fmtMoney, num, toneClass } from "./utils/format";

type FleetRow = {
  id: string;
  name: string;
  strategy: string;
  market: string;
  status: string;
  enabled: boolean;
  pnl: number | null;
  exposure: string;
  isDeployment: boolean;
};

export function PaperTradingAgentFleetPanel({
  agents,
  deployments,
  strategies,
  busyAction,
  onToggle,
}: {
  agents: AgentDefinition[];
  deployments: MarketSimPaperDeployment[];
  strategies: PortfolioStrategyAllocation[];
  busyAction: string | null;
  onToggle: (agentId: string, enable: boolean) => void;
}) {
  const rows: FleetRow[] =
    agents.length > 0
      ? agents.map((a) => {
          const strat =
            strategies.find((s) => s.agent_id === a.agentId) ||
            strategies.find((s) => s.strategy_id === a.name) ||
            null;
          return {
            id: a.agentId,
            name: a.name,
            strategy: strat?.strategy_id || a.role || "—",
            market: "—",
            status: a.enabled ? String(a.status || a.health || "active") : "idle",
            enabled: a.enabled,
            pnl: strat ? num(strat.total_pnl) : null,
            exposure: strat ? `${strat.allocation_pct.toFixed(1)}%` : "—",
            isDeployment: false,
          };
        })
      : deployments.map((d) => ({
          id: d.deployment_id,
          name: d.strategy_asset_id,
          strategy: `v${d.strategy_version}`,
          market: (d.universe || [])[0] || "—",
          status: d.kill_switch ? "killed" : String(d.status),
          enabled: !d.kill_switch && String(d.status).toLowerCase() !== "stopped",
          pnl: null,
          exposure: "—",
          isDeployment: true,
        }));

  return (
    <article className="lv-paper-panel lv-paper-fleet">
      <header className="lv-paper-panel-head">
        <h2>Agent Fleet</h2>
        <span className="lv-paper-muted">{rows.length} agents</span>
      </header>
      {rows.length === 0 ? (
        <p className="lv-paper-state">No paper agents or deployments yet.</p>
      ) : (
        <div className="lv-paper-table-wrap">
          <table className="lv-paper-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Strategy</th>
                <th>Market</th>
                <th>Status</th>
                <th>Position</th>
                <th>PnL</th>
                <th>Exposure</th>
                <th>Win</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 12).map((a) => (
                <tr key={a.id}>
                  <td>{a.name}</td>
                  <td>{a.strategy}</td>
                  <td>{a.market}</td>
                  <td>
                    <span className={`lv-paper-pill${a.enabled ? " is-live" : ""}`}>{a.status}</span>
                  </td>
                  <td>—</td>
                  <td className={toneClass(a.pnl)}>
                    {a.pnl == null ? "—" : `$${fmtMoney(a.pnl)}`}
                  </td>
                  <td>{a.exposure}</td>
                  <td>—</td>
                  <td className="lv-paper-row-actions">
                    {a.isDeployment ? (
                      <span className="lv-paper-muted">dep</span>
                    ) : (
                      <button
                        type="button"
                        disabled={busyAction !== null}
                        onClick={() => onToggle(a.id, !a.enabled)}
                        title={a.enabled ? "Pause" : "Start"}
                      >
                        {a.enabled ? "■" : "▶"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}
