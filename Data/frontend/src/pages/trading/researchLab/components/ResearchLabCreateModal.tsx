import type { CreateRunDraft } from "../hooks/useResearchLab";
import type { MarketDataSource, MarketStrategy } from "../../../../types/api";

export function ResearchLabCreateModal({
  draft,
  strategies,
  sources,
  catalogError,
  busy,
  onPatch,
  onClose,
  onSubmit,
}: {
  draft: CreateRunDraft;
  strategies: MarketStrategy[];
  sources: MarketDataSource[];
  catalogError: string | null;
  busy: boolean;
  onPatch: (p: Partial<CreateRunDraft>) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="lv-rl-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="lv-rl-create-title">
      <div className="lv-rl-modal">
        <h2 id="lv-rl-create-title">Create research run</h2>
        <p className="hint">
          Binds a strategy + READY market-data source to an agent lab. With learning enabled, adaptive DSL search
          evaluates candidates on market simulation (train / validation / sealed).
        </p>
        {catalogError ? <p className="lv-rl-banner">{catalogError}</p> : null}
        <div className="lv-rl-form">
          <label>
            Name
            <input
              value={draft.name}
              onChange={(e) => onPatch({ name: e.target.value })}
              placeholder="Optional lab name"
            />
          </label>
          <label>
            Strategy
            <select
              value={draft.strategyId}
              onChange={(e) => onPatch({ strategyId: e.target.value })}
              required
            >
              <option value="">Select strategy…</option>
              {strategies.map((s) => (
                <option key={s.strategy_id} value={s.strategy_id}>
                  {s.name} · {s.strategy_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Source / dataset (READY only)
            <select value={draft.sourceId} onChange={(e) => onPatch({ sourceId: e.target.value })} required>
              <option value="">Select source…</option>
              {sources.map((s) => (
                <option key={s.source_id} value={s.source_id}>
                  {s.symbol} {s.timeframe} · {s.source_id.slice(0, 8)} · {s.bar_count} bars
                </option>
              ))}
            </select>
          </label>
          <label>
            Hypothesis
            <textarea
              value={draft.hypothesis}
              onChange={(e) => onPatch({ hypothesis: e.target.value })}
              placeholder="What edge are you searching for?"
            />
          </label>
          <div className="lv-rl-form-row">
            <label>
              Autonomy ceiling
              <select
                value={draft.autonomyCeiling}
                onChange={(e) => onPatch({ autonomyCeiling: e.target.value })}
              >
                {["A0", "A1", "A2", "A3", "A4"].map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Max candidates
              <input
                type="number"
                min={1}
                max={200}
                value={draft.maxCandidates}
                onChange={(e) => onPatch({ maxCandidates: Number(e.target.value) || 1 })}
              />
            </label>
          </div>
          <div className="lv-rl-form-row">
            <label>
              Max iterations
              <input
                type="number"
                min={1}
                max={100}
                value={draft.maxIterations}
                onChange={(e) => onPatch({ maxIterations: Number(e.target.value) || 1 })}
              />
            </label>
            <label>
              Population size
              <input
                type="number"
                min={1}
                max={64}
                value={draft.populationSize}
                onChange={(e) => onPatch({ populationSize: Number(e.target.value) || 1 })}
              />
            </label>
          </div>
          <div className="lv-rl-form-row">
            <label>
              Generation budget
              <input
                type="number"
                min={1}
                max={200}
                value={draft.generationBudget}
                onChange={(e) => onPatch({ generationBudget: Number(e.target.value) || 1 })}
              />
            </label>
            <label>
              Trial budget
              <input
                type="number"
                min={1}
                max={2000}
                value={draft.trialBudget}
                onChange={(e) => onPatch({ trialBudget: Number(e.target.value) || 1 })}
              />
            </label>
          </div>
          <label className="lv-rl-check">
            <input
              type="checkbox"
              checked={draft.enableLearning}
              onChange={(e) => onPatch({ enableLearning: e.target.checked })}
            />
            Enable adaptive learning (Strategy Learning Run)
          </label>
          <label>
            Notes
            <textarea
              value={draft.notes}
              onChange={(e) => onPatch({ notes: e.target.value })}
              placeholder="Optional operator notes"
            />
          </label>
          <div className="lv-rl-form-actions">
            <button type="button" className="lv-rl-btn is-ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button
              type="button"
              className="lv-rl-btn is-primary"
              onClick={onSubmit}
              disabled={busy || !draft.strategyId || !draft.sourceId}
            >
              {busy ? "Creating…" : "Create run"}
            </button>
          </div>
          {strategies.length === 0 || sources.length === 0 ? (
            <p className="hint">
              {strategies.length === 0 ? "No strategies found — create one under Strategies. " : ""}
              {sources.length === 0 ? "No READY sources — register market data under Marktdata." : ""}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
