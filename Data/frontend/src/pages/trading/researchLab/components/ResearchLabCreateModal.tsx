import { useState } from "react";
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
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const autonomous = draft.runMode === "AUTONOMOUS_DISCOVERY";
  const canSubmit =
    Boolean(draft.sourceId) && (autonomous || Boolean(draft.strategyId));

  return (
    <div className="lv-rl-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="lv-rl-create-title">
      <div className="lv-rl-modal">
        <h2 id="lv-rl-create-title">Create research run</h2>
        <p className="hint">
          Autonomous discovery lets Leviathan form hypotheses from a research objective and READY
          market data. Seed mode binds an existing strategy into the learning curriculum.
        </p>
        {catalogError ? <p className="lv-rl-banner">{catalogError}</p> : null}

        <div className="lv-rl-mode-toggle" role="group" aria-label="Run mode">
          <button
            type="button"
            className={`lv-rl-mode-btn${autonomous ? " is-active" : ""}`}
            onClick={() => onPatch({ runMode: "AUTONOMOUS_DISCOVERY" })}
            disabled={busy}
          >
            Autonomous Discovery
          </button>
          <button
            type="button"
            className={`lv-rl-mode-btn${!autonomous ? " is-active" : ""}`}
            onClick={() => onPatch({ runMode: "SEED_EXISTING_STRATEGY" })}
            disabled={busy}
          >
            Seed Existing Strategy
          </button>
        </div>

        <div className="lv-rl-form">
          <label>
            Name
            <input
              value={draft.name}
              onChange={(e) => onPatch({ name: e.target.value })}
              placeholder="Optional lab name"
            />
          </label>

          {!autonomous ? (
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
          ) : (
            <p className="lv-rl-mode-note">
              Strategy selector hidden — Leviathan will form hypotheses and propose strategy-family
              candidates from the research objective. A research lineage root is created server-side.
            </p>
          )}

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

          {autonomous ? (
            <label>
              Research objective
              <textarea
                value={draft.researchObjective}
                onChange={(e) => onPatch({ researchObjective: e.target.value })}
                placeholder="What should Leviathan discover? e.g. mean-reversion edges on liquid equities after volatility expansions"
              />
            </label>
          ) : (
            <label>
              Hypothesis
              <textarea
                value={draft.hypothesis}
                onChange={(e) => onPatch({ hypothesis: e.target.value })}
                placeholder="What edge are you searching for?"
              />
            </label>
          )}

          <label>
            Universe (optional, comma-separated)
            <input
              value={draft.universe}
              onChange={(e) => onPatch({ universe: e.target.value })}
              placeholder="e.g. AAPL, MSFT, SPY"
            />
          </label>
          <label>
            Timeframes (optional, comma-separated)
            <input
              value={draft.timeframes}
              onChange={(e) => onPatch({ timeframes: e.target.value })}
              placeholder="e.g. 1h, 4h, 1d"
            />
          </label>

          <button
            type="button"
            className="lv-rl-advanced-toggle"
            aria-expanded={advancedOpen}
            onClick={() => setAdvancedOpen((v) => !v)}
          >
            {advancedOpen ? "▾" : "▸"} Advanced research settings
          </button>

          {advancedOpen ? (
            <div className="lv-rl-advanced">
              <label className="lv-rl-check">
                <input
                  type="checkbox"
                  checked={draft.enableChartVision}
                  onChange={(e) => onPatch({ enableChartVision: e.target.checked })}
                />
                Enable chart vision (off by default)
              </label>
              <div className="lv-rl-form-row">
                <label>
                  Model budget
                  <input
                    type="number"
                    min={1}
                    max={64}
                    value={draft.modelBudget}
                    onChange={(e) => onPatch({ modelBudget: Number(e.target.value) || 1 })}
                  />
                </label>
                <label>
                  Agent proposal rate
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={draft.agentProposalRate}
                    onChange={(e) => onPatch({ agentProposalRate: Number(e.target.value) || 0 })}
                  />
                </label>
              </div>
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
              <p className="hint" style={{ margin: 0 }}>
                Research Lab create does not expose brokerage or execution controls.
              </p>
            </div>
          ) : null}

          <div className="lv-rl-form-actions">
            <button type="button" className="lv-rl-btn is-ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button
              type="button"
              className="lv-rl-btn is-primary"
              onClick={onSubmit}
              disabled={busy || !canSubmit}
            >
              {busy ? "Creating…" : "Create run"}
            </button>
          </div>
          {sources.length === 0 ? (
            <p className="hint">No READY sources — register market data under Marktdata.</p>
          ) : null}
          {!autonomous && strategies.length === 0 ? (
            <p className="hint">No strategies found — create one under Strategies.</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
