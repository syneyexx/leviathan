"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  HadesApiError,
  hadesApi,
  type NeuralProductSettings,
  type NeuralProductStatus,
} from "@/lib/hades-api";

type Mode = NeuralProductSettings["neural_mode"];

/**
 * FINALBETA Neural control surface.
 * Displays truthful backend Neural state; owns no Neural business logic.
 */
export function NeuralControlPanel({ compact = false }: { compact?: boolean }) {
  const [status, setStatus] = useState<NeuralProductStatus | null>(null);
  const [settings, setSettings] = useState<NeuralProductSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextSettings] = await Promise.all([hadesApi.neuralStatus(), hadesApi.neuralSettings()]);
      setStatus(nextStatus);
      setSettings(nextSettings);
      setError(null);
    } catch (reason) {
      setStatus(null);
      setSettings(null);
      setError(reason instanceof HadesApiError ? reason.message : "Neural status unavailable");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const patch = async (values: Partial<NeuralProductSettings>) => {
    if (busy) return;
    setBusy(true);
    try {
      await hadesApi.patchNeuralSettings(values);
      await refresh();
      toast.success("Neural-instellingen opgeslagen.");
    } catch (reason) {
      toast.error(reason instanceof HadesApiError ? reason.message : "Opslaan mislukt");
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="card compact-panel">
        <div className="panel-title">Neural Brain</div>
        <div className="status-check">
          <span className="dot" />
          <div>
            <b>Backend niet bereikbaar</b>
            <small>{error}</small>
          </div>
        </div>
      </div>
    );
  }

  if (!status || !settings) {
    return (
      <div className="card compact-panel">
        <div className="panel-title">Neural Brain</div>
        <p className="muted">Neural status laden…</p>
      </div>
    );
  }

  const mode = settings.neural_mode;
  const readyLabel = status.ready ? "inference-ready" : status.product_state || "not ready";
  const slow = status.artifacts?.slow_memory || status.persistence?.known_good_checkpoint_id || "—";
  const persistence = status.persistence || {};

  return (
    <div className="card compact-panel">
      <div className="panel-title between">
        <span>Neural Brain</span>
        <span className="pill">
          <span className={`dot ${status.ready ? "green" : mode === "off" ? "" : "yellow"}`} />
          {readyLabel}
        </span>
      </div>
      <p className="muted">
        Exact Brain blijft bron van waarheid. Neural Memory is associatief en niet-autoritief.
      </p>
      <div className="settings-form-grid">
        <label>
          Neural modus
          <select
            className="select"
            value={mode}
            disabled={busy}
            onChange={(event) => void patch({ neural_mode: event.target.value as Mode })}
          >
            <option value="off">OFF — conventionele HADES</option>
            <option value="shadow">SHADOW — meten zonder antwoordwijziging</option>
            <option value="read">READ — Neural Memory meelezen</option>
            <option value="learn">LEARN — verandert geheugen (gevaarlijker)</option>
          </select>
        </label>
        <label>
          Neural toestaan
          <select
            className="select"
            value={settings.neural_allow ? "true" : "false"}
            disabled={busy}
            onChange={(event) => void patch({ neural_allow: event.target.value === "true" })}
          >
            <option value="false">Uit (standaard)</option>
            <option value="true">Aan</option>
          </select>
        </label>
        <label>
          Neural requirement
          <select
            className="select"
            value={settings.neural_requirement}
            disabled={busy}
            onChange={(event) => void patch({ neural_requirement: event.target.value as NeuralProductSettings["neural_requirement"] })}
          >
            <option value="off">OFF — nooit vereist</option>
            <option value="preferred">Preferred — gebruik wanneer beschikbaar</option>
            <option value="required">Required — faal zonder Neural</option>
          </select>
        </label>
        <label>
          Shadow sample rate
          <input
            className="input"
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={settings.neural_shadow_sample_rate}
            disabled={busy}
            onChange={(event) => void patch({ neural_shadow_sample_rate: Number(event.target.value) })}
          />
        </label>
        <label>
          Max. concurrent infer
          <input
            className="input"
            type="number"
            min={1}
            step={1}
            value={settings.neural_max_concurrent_infer}
            disabled={busy}
            onChange={(event) => void patch({ neural_max_concurrent_infer: Number(event.target.value) })}
          />
        </label>
      </div>
      {!compact ? (
        <>
          <div className="sep" />
          <div className="detail-row">
            <div className="keylabel">Base model</div>
            <div>{status.artifacts?.base_model || "—"}</div>
          </div>
          <div className="detail-row">
            <div className="keylabel">HADES adapter</div>
            <div>{status.artifacts?.hades_adapter || "niet geladen"}</div>
          </div>
          <div className="detail-row">
            <div className="keylabel">Fast Memory</div>
            <div>{status.artifacts?.fast_memory || "ephemeral"}</div>
          </div>
          <div className="detail-row">
            <div className="keylabel">Slow Memory</div>
            <div>{String(slow)}</div>
          </div>
          <div className="detail-row">
            <div className="keylabel">Last promotion</div>
            <div>{String(persistence.last_promotion || "—")}</div>
          </div>
          <div className="detail-row">
            <div className="keylabel">Last rollback</div>
            <div>{String(persistence.last_rollback || "—")}</div>
          </div>
          <div className="detail-row">
            <div className="keylabel">Capacity inflight</div>
            <div>{String((status.capacity || {}).inflight ?? 0)} / {String((status.capacity || {}).max_concurrent_infer ?? 1)}</div>
          </div>
          <div className="sep" />
          <div className="setting-toggle">
            <div>
              <b>Dual Exact + Neural</b>
              <span>Opt-in contextinjectie; Neural blijft untrusted association.</span>
            </div>
            <button
              type="button"
              className={`switch ${settings.neural_dual_memory_enabled ? "on" : ""}`}
              aria-pressed={settings.neural_dual_memory_enabled}
              disabled={busy}
              onClick={() => void patch({ neural_dual_memory_enabled: !settings.neural_dual_memory_enabled })}
            />
          </div>
          <div className="setting-toggle">
            <div>
              <b>Domain: Coding</b>
              <span>Associatief geheugen voor coding-taken.</span>
            </div>
            <button
              type="button"
              className={`switch ${settings.neural_domain_coding_enabled ? "on" : ""}`}
              aria-pressed={settings.neural_domain_coding_enabled}
              disabled={busy}
              onClick={() => void patch({ neural_domain_coding_enabled: !settings.neural_domain_coding_enabled })}
            />
          </div>
          <div className="setting-toggle">
            <div>
              <b>Domain: Research</b>
              <span>Associatief geheugen voor research-taken.</span>
            </div>
            <button
              type="button"
              className={`switch ${settings.neural_domain_research_enabled ? "on" : ""}`}
              aria-pressed={settings.neural_domain_research_enabled}
              disabled={busy}
              onClick={() => void patch({ neural_domain_research_enabled: !settings.neural_domain_research_enabled })}
            />
          </div>
          <div className="setting-toggle">
            <div>
              <b>Domain: Trading</b>
              <span>Standaard uit; alleen voor paper/lab trading-associaties.</span>
            </div>
            <button
              type="button"
              className={`switch ${settings.neural_domain_trading_enabled ? "on" : ""}`}
              aria-pressed={settings.neural_domain_trading_enabled}
              disabled={busy}
              onClick={() => void patch({ neural_domain_trading_enabled: !settings.neural_domain_trading_enabled })}
            />
          </div>
          {mode === "learn" ? (
            <p className="muted" style={{ marginTop: 10 }}>
              LEARN is duidelijk riskanter dan READ: alleen geverifieerde experiences mogen consolideren.
            </p>
          ) : null}
        </>
      ) : null}
      <div className="row" style={{ marginTop: 12 }}>
        <button type="button" className="btn small" disabled={busy} onClick={() => void refresh()}>
          Vernieuwen
        </button>
      </div>
    </div>
  );
}
