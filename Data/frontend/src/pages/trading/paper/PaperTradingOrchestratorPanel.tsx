import type { OrchestratorDraft, PaperAgentMode } from "./utils/format";

export function PaperTradingOrchestratorPanel({
  draft,
  portfolioStatus,
  busyAction,
  onPatch,
  onSave,
  onDeploy,
  onPause,
  onFlatten,
}: {
  draft: OrchestratorDraft;
  portfolioStatus: string | null;
  busyAction: string | null;
  onPatch: (p: Partial<OrchestratorDraft>) => void;
  onSave: () => void;
  onDeploy: () => void;
  onPause: () => void;
  onFlatten: () => void;
}) {
  const running = (portfolioStatus || "").toUpperCase() === "RUNNING";
  const modes: PaperAgentMode[] = ["autonomous", "assisted", "manual"];

  return (
    <article className="lv-paper-panel lv-paper-orch">
      <header className="lv-paper-panel-head">
        <h2>Agent Orchestrator</h2>
        <div className={`lv-paper-mode-pill${running ? " is-on" : ""}`}>
          Paper Trading Mode {running ? "SIMULATED" : "IDLE"}
        </div>
      </header>

      <div className="lv-paper-mode-row" role="group" aria-label="Agent mode">
        {modes.map((m) => (
          <button
            key={m}
            type="button"
            className={`lv-paper-mode-btn${draft.agentMode === m ? " is-active" : ""}`}
            onClick={() => onPatch({ agentMode: m })}
          >
            {m[0].toUpperCase() + m.slice(1)}
          </button>
        ))}
      </div>

      <div className="lv-paper-orch-grid">
        <label>
          Capital Allocation (USDT)
          <input
            type="number"
            value={draft.capitalAllocation}
            onChange={(e) => onPatch({ capitalAllocation: Number(e.target.value) || 0 })}
            onBlur={onSave}
          />
        </label>
        <label>
          Position Sizing
          <select
            value={String(draft.positionSizingPct)}
            onChange={(e) => {
              onPatch({ positionSizingPct: Number(e.target.value) });
              onSave();
            }}
          >
            {[0.5, 1, 2, 3, 5].map((v) => (
              <option key={v} value={v}>
                {v}% per trade
              </option>
            ))}
          </select>
        </label>
        <label>
          Max Open Positions
          <input
            type="number"
            value={draft.maxOpenPositions}
            onChange={(e) => onPatch({ maxOpenPositions: Number(e.target.value) || 0 })}
            onBlur={onSave}
          />
        </label>
        <label>
          Max Drawdown %
          <input
            type="number"
            value={draft.maxDrawdownPct}
            onChange={(e) => onPatch({ maxDrawdownPct: Number(e.target.value) || 0 })}
            onBlur={onSave}
          />
        </label>
        <label>
          Daily Loss Limit %
          <input
            type="number"
            value={draft.dailyLossLimitPct}
            onChange={(e) => onPatch({ dailyLossLimitPct: Number(e.target.value) || 0 })}
            onBlur={onSave}
          />
        </label>
        <label>
          Default Stop Loss %
          <input
            type="number"
            step="0.1"
            value={draft.defaultStopLossPct}
            onChange={(e) => onPatch({ defaultStopLossPct: Number(e.target.value) || 0 })}
            onBlur={onSave}
          />
        </label>
        <label>
          Default Take Profit %
          <input
            type="number"
            step="0.1"
            value={draft.defaultTakeProfitPct}
            onChange={(e) => onPatch({ defaultTakeProfitPct: Number(e.target.value) || 0 })}
            onBlur={onSave}
          />
        </label>
      </div>

      <div className="lv-paper-toggles">
        {(
          [
            ["allowNewPositions", "Allow New Positions"],
            ["autoRebalance", "Auto Rebalance"],
            ["newsFilter", "News Filter"],
            ["useTrailingStops", "Use Trailing Stops"],
            ["hedgeMode", "Hedge Mode"],
            ["multiAgentCoordination", "Multi-Agent Coordination"],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="lv-paper-toggle">
            <input
              type="checkbox"
              checked={Boolean(draft[key])}
              onChange={(e) => {
                onPatch({ [key]: e.target.checked });
                onSave();
              }}
            />
            <span>{label}</span>
          </label>
        ))}
      </div>

      <div className="lv-paper-orch-actions">
        <button
          type="button"
          className="lv-paper-btn is-deploy"
          disabled={busyAction !== null}
          onClick={onDeploy}
        >
          {busyAction === "deploy" ? "Deploying…" : "Deploy Agents"}
        </button>
        <button
          type="button"
          className="lv-paper-btn is-pause"
          disabled={busyAction !== null}
          onClick={onPause}
        >
          {busyAction === "pause" ? "Pausing…" : "Pause All"}
        </button>
        <button
          type="button"
          className="lv-paper-btn is-flatten"
          disabled={busyAction !== null}
          onClick={onFlatten}
        >
          {busyAction === "flatten" ? "Flattening…" : "Flatten All"}
        </button>
      </div>
    </article>
  );
}
