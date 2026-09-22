import { useCallback, useEffect, useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { ApiError, api } from "../../api/client";
import { SubMenu } from "../../components/SubMenu";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import type { MarketStrategy, MarketStrategyVersion } from "../../types/api";
import { Panel, TradingHero, hashShort } from "./shared";

const BUILDER_TABS = ["Visual Builder", "Code View", "Parameters"] as const;
const RULE_KINDS = ["ma_cross", "mean_reversion"] as const;

export function StrategieenPage() {
  const toast = useAppToast();
  const [strategies, setStrategies] = useState<MarketStrategy[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [versions, setVersions] = useState<MarketStrategyVersion[]>([]);
  const [builderTab, setBuilderTab] = useState<(typeof BUILDER_TABS)[number]>("Parameters");
  const [name, setName] = useState("MA Cross");
  const [description, setDescription] = useState("Causal moving-average crossover");
  const [kind, setKind] = useState<(typeof RULE_KINDS)[number]>("ma_cross");
  const [fastMa, setFastMa] = useState(10);
  const [slowMa, setSlowMa] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      .then((detail) => {
        setVersions(detail.versions);
        const head = detail.versions[0];
        if (head) {
          const params = head.parameters as { fast_ma?: number; slow_ma?: number };
          if (typeof params.fast_ma === "number") setFastMa(params.fast_ma);
          if (typeof params.slow_ma === "number") setSlowMa(params.slow_ma);
          const entryKind = String(head.entry_rules.kind ?? "ma_cross");
          if (entryKind === "ma_cross" || entryKind === "mean_reversion") {
            setKind(entryKind);
          }
          setName(detail.strategy.name);
          setDescription(detail.strategy.description);
        }
      })
      .catch(() => setVersions([]));
  }, [selected]);

  async function saveStrategy() {
    setBusy(true);
    try {
      const created = await api.createMarketStrategy({
        name,
        description,
        tags: [kind, "paper"],
        parameters: {
          fast_ma: fastMa,
          slow_ma: slowMa,
          lookback: Math.max(slowMa, 20),
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

  const activeCount = strategies.filter((s) => s.status === "ACTIVE").length;

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Strategies Mode"
      searchPlaceholder="Search strategies, assets, indicators, models..."
      systemItems={["PAPER STRATEGIES", "SANDBOXED DSL"]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="TRADING STRATEGIEËN"
          kicker="DESIGN. TEST. DEPLOY."
          quote="“Systematic discipline turns ideas into an edge.” — LEVIATHAN"
          image={tradingHeroes.strategieen}
          rails={["IDEAS", "MODELS", "BACKTESTS", "OPTIMIZATION", "DEPLOYMENT", "ALPHA"]}
          objectPosition="center 30%"
        />

        <SubMenu />

        {error ? (
          <Panel title="Strategies">
            <p>{error}</p>
          </Panel>
        ) : null}

        <section className="lv-st-kpi-row">
          {[
            { label: "Total Strategies", value: String(strategies.length), foot: "from market-sim store" },
            { label: "Active Strategies", value: String(activeCount), foot: "ACTIVE status" },
            { label: "Selected Version", value: selected ? `v${versions[0]?.version ?? "—"}` : "—", foot: hashShort(versions[0]?.content_hash) },
            { label: "Rule Kind", value: kind, foot: "sandboxed DSL only" },
            { label: "Brain Deps", value: "knowledge · memory · neuro", foot: "advisory retrieval" },
            { label: "Execution", value: "Paper sim", foot: "no live broker" },
          ].map((k) => (
            <article key={k.label} className="lv-st-kpi">
              <div className="lbl">{k.label}</div>
              <div className="val" style={{ fontSize: k.label === "Brain Deps" ? "0.95rem" : undefined }}>
                {k.value}
              </div>
              <div className="foot">
                <span>{k.foot}</span>
              </div>
            </article>
          ))}
        </section>

        <section className="lv-st-mid">
          <Panel title="Strategy Library">
            <div className="lv-st-lib-tools">
              <input className="lv-tp-input" type="search" placeholder="Filter by name..." readOnly value="" />
            </div>
            <table className="lv-tp-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Version</th>
                  <th>Hash</th>
                  <th>Tags</th>
                </tr>
              </thead>
              <tbody>
                {strategies.map((s) => (
                  <tr
                    key={s.strategy_id}
                    style={{ cursor: "pointer", outline: selected === s.strategy_id ? "1px solid var(--lv-gold)" : undefined }}
                    onClick={() => setSelected(s.strategy_id)}
                  >
                    <td>{s.name}</td>
                    <td>
                      <span className={`lv-tp-pill${s.status === "ACTIVE" ? " is-live" : ""}`}>{s.status}</span>
                    </td>
                    <td>v{s.current_version}</td>
                    <td>{hashShort(s.content_hash)}</td>
                    <td>{s.tags.join(", ") || "—"}</td>
                  </tr>
                ))}
                {!strategies.length ? (
                  <tr>
                    <td colSpan={5}>No strategies yet — create one in the builder</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </Panel>

          <Panel
            title="Strategy Builder"
            action={
              <button
                type="button"
                className="lv-tp-btn lv-tp-btn--accent"
                disabled={busy}
                onClick={() => void saveStrategy()}
              >
                Save Strategy
              </button>
            }
          >
            <div className="lv-tp-tabs" style={{ marginBottom: 8 }}>
              {BUILDER_TABS.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`lv-tp-chip${builderTab === t ? " is-active" : ""}`}
                  onClick={() => setBuilderTab(t)}
                >
                  {t}
                </button>
              ))}
            </div>
            {builderTab === "Visual Builder" ? (
              <div className="lv-st-builder-canvas">
                <div className="lv-st-nodes">
                  <div className="lv-st-node">
                    Market Data
                    <small>Causal OHLCV ≤ clock</small>
                  </div>
                  <div className="lv-st-edge" />
                  <div className="lv-st-node">
                    Rules
                    <small>{kind}</small>
                  </div>
                  <div className="lv-st-edge" />
                  <div className="lv-st-node">
                    Brain
                    <small>Knowledge · Memory · Neuro</small>
                  </div>
                  <div className="lv-st-edge" />
                  <div className="lv-st-node is-exec">
                    Paper Fill
                    <small>Fee + slippage</small>
                  </div>
                </div>
                <p className="lv-tp-muted" style={{ marginTop: 12 }}>
                  Visual graph is illustrative — execution uses the sandboxed DSL parameters below.
                </p>
              </div>
            ) : null}
            {builderTab === "Code View" ? (
              <pre className="lv-tp-muted" style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                {JSON.stringify(
                  {
                    kind,
                    parameters: { fast_ma: fastMa, slow_ma: slowMa },
                    brain_dependencies: ["knowledge", "memory", "neuro"],
                  },
                  null,
                  2,
                )}
              </pre>
            ) : null}
            {builderTab === "Parameters" ? (
              <div className="lv-st-params">
                <div className="lv-st-param">
                  <label htmlFor="strat-name">Name</label>
                  <input id="strat-name" className="lv-tp-input" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="lv-st-param">
                  <label htmlFor="strat-desc">Description</label>
                  <input
                    id="strat-desc"
                    className="lv-tp-input"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
                <div className="lv-st-param">
                  <label htmlFor="strat-kind">Rule kind</label>
                  <select
                    id="strat-kind"
                    className="lv-tp-select"
                    value={kind}
                    onChange={(e) => setKind(e.target.value as (typeof RULE_KINDS)[number])}
                  >
                    <option value="ma_cross">MA cross (trend)</option>
                    <option value="mean_reversion">Mean reversion</option>
                  </select>
                </div>
                <div className="lv-st-param">
                  <label htmlFor="fast-ma">Fast MA Period</label>
                  <strong>{fastMa}</strong>
                  <input
                    id="fast-ma"
                    className="lv-tp-slider"
                    type="range"
                    min={3}
                    max={50}
                    value={fastMa}
                    onChange={(e) => setFastMa(Number(e.target.value))}
                  />
                </div>
                <div className="lv-st-param">
                  <label htmlFor="slow-ma">Slow MA Period</label>
                  <strong>{slowMa}</strong>
                  <input
                    id="slow-ma"
                    className="lv-tp-slider"
                    type="range"
                    min={10}
                    max={200}
                    value={slowMa}
                    onChange={(e) => setSlowMa(Number(e.target.value))}
                  />
                </div>
              </div>
            ) : null}
          </Panel>

          <Panel title="Versions">
            <table className="lv-tp-table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Changelog</th>
                  <th>Hash</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.version_id}>
                    <td>v{v.version}</td>
                    <td>{v.changelog || "—"}</td>
                    <td>{hashShort(v.content_hash)}</td>
                    <td>{v.created_at}</td>
                  </tr>
                ))}
                {!versions.length ? (
                  <tr>
                    <td colSpan={4}>Select a strategy</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </Panel>
        </section>
      </main>
    </AppShell>
  );
}
