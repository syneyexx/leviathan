import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { MarketStrategy, MarketStrategyVersion } from "../../types/api";
import { useAppToast } from "../../state/useAppToast";
import { TradingShell, hashShort } from "./shared";

export function StrategieenPage() {
  const toast = useAppToast();
  const [strategies, setStrategies] = useState<MarketStrategy[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [versions, setVersions] = useState<MarketStrategyVersion[]>([]);
  const [name, setName] = useState("MA Cross");
  const [description, setDescription] = useState("Causal moving-average crossover");
  const [fastMa, setFastMa] = useState("10");
  const [slowMa, setSlowMa] = useState("30");
  const [kind, setKind] = useState<"ma_cross" | "mean_reversion">("ma_cross");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const { strategies: list } = await api.listMarketStrategies();
      setStrategies(list);
      setError(null);
      if (!selected && list[0]) setSelected(list[0].strategy_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load strategies");
    }
  }, [selected]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setVersions([]);
      return;
    }
    void api
      .getMarketStrategy(selected)
      .then((detail) => setVersions(detail.versions))
      .catch(() => setVersions([]));
  }, [selected]);

  async function createStrategy() {
    setBusy(true);
    try {
      const created = await api.createMarketStrategy({
        name,
        description,
        tags: [kind, "paper"],
        parameters: {
          fast_ma: Number(fastMa),
          slow_ma: Number(slowMa),
          lookback: Math.max(Number(slowMa), 20),
        },
        entryRules: { kind },
        exitRules: { kind },
        brainDependencies: ["knowledge", "memory", "neuro"],
        requiredTimeframes: ["1h"],
      });
      setSelected(created.strategy.strategy_id);
      toast("Strategy saved");
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <TradingShell title="Strategieen">
      {error ? (
        <article className="lv-panel lv-tr-card">
          <p>{error}</p>
        </article>
      ) : null}

      <section className="lv-tr-mid">
        <article className="lv-panel lv-tr-card">
          <div className="lv-section-label">Create strategy</div>
          <label className="lv-tr-field">
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="lv-tr-field">
            <span>Description</span>
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label className="lv-tr-field">
            <span>Rule kind</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              <option value="ma_cross">MA cross (trend)</option>
              <option value="mean_reversion">Mean reversion</option>
            </select>
          </label>
          <div className="lv-tr-sltp">
            <label className="lv-tr-field">
              <span>Fast MA</span>
              <input value={fastMa} onChange={(e) => setFastMa(e.target.value)} />
            </label>
            <label className="lv-tr-field">
              <span>Slow MA</span>
              <input value={slowMa} onChange={(e) => setSlowMa(e.target.value)} />
            </label>
          </div>
          <button type="button" className="lv-tr-submit buy" disabled={busy} onClick={() => void createStrategy()}>
            Save strategy
          </button>
          <p className="lv-muted">Sandboxed DSL only — no arbitrary code execution.</p>
        </article>

        <article className="lv-panel lv-tr-card">
          <div className="lv-section-label">Library</div>
          <ul className="lv-tr-agents">
            {strategies.map((s) => (
              <li key={s.strategy_id}>
                <button
                  type="button"
                  className="lv-tr-mini"
                  style={{ width: "100%", textAlign: "left", background: "transparent", border: 0, color: "inherit" }}
                  onClick={() => setSelected(s.strategy_id)}
                >
                  <div>
                    <strong>{s.name}</strong>
                    <small>
                      v{s.current_version} · {s.status} · {hashShort(s.content_hash)}
                    </small>
                  </div>
                </button>
                <span>{s.tags.join(", ") || "—"}</span>
              </li>
            ))}
            {!strategies.length ? (
              <li>
                <div>
                  <strong>No strategies yet</strong>
                  <small>Create one to attach to a simulation</small>
                </div>
              </li>
            ) : null}
          </ul>
        </article>

        <article className="lv-panel lv-tr-card">
          <div className="lv-section-label">Versions</div>
          <ul className="lv-tr-activity">
            {versions.map((v) => (
              <li key={v.version_id}>
                <span className="lv-tr-dot ok" />
                <div>
                  <strong>
                    v{v.version} · {v.changelog || "no changelog"}
                  </strong>
                  <small>
                    {hashShort(v.content_hash)} · brain {(v.brain_dependencies || []).join(", ")}
                  </small>
                </div>
              </li>
            ))}
            {!versions.length ? (
              <li>
                <span className="lv-tr-dot info" />
                <div>
                  <strong>Select a strategy</strong>
                </div>
              </li>
            ) : null}
          </ul>
        </article>
      </section>
    </TradingShell>
  );
}
