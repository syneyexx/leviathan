import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type {
  ModelDescriptor,
  ModelProfile,
  ModelProvider,
  VerifiedCapability,
} from "../../types/api";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

type Tab =
  | "overview"
  | "capabilities"
  | "profile"
  | "runtime"
  | "resources"
  | "benchmarks"
  | "diagnostics";

export function ModelInspector({
  model,
  profile,
  capabilities,
  provider,
  preflight,
  tab,
  onTab,
  onSaveProfile,
  onActivate,
  onLoad,
  onUnload,
  onDelete,
  onProbe,
  onBenchmark,
  busy,
}: {
  model: ModelDescriptor;
  profile: ModelProfile;
  capabilities: VerifiedCapability[];
  provider: ModelProvider | null;
  preflight: Record<string, unknown> | null;
  tab: Tab;
  onTab: (t: Tab) => void;
  onSaveProfile: (p: ModelProfile, activate: boolean) => Promise<void>;
  onActivate: () => void;
  onLoad: () => void;
  onUnload: () => void;
  onDelete: () => void;
  onProbe: () => void;
  onBenchmark: () => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState(profile);
  const [profileKey, setProfileKey] = useState(`${profile.modelId}:${profile.updatedAt ?? ""}`);
  const incomingKey = `${profile.modelId}:${profile.updatedAt ?? ""}`;
  if (incomingKey !== profileKey) {
    setProfileKey(incomingKey);
    setDraft(profile);
  }

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(profile), [draft, profile]);

  const caps = provider?.capabilities;
  const loadSupported = Boolean(caps?.loadModel);
  const unloadSupported = Boolean(caps?.unloadModel);

  return (
    <section className="lv-models-inspector" aria-label="Model inspector">
      <div className="lv-card-head">
        <div>
          <div className="lv-section-label">Inspector</div>
          <h2>{model.displayName}</h2>
          <p className="lv-muted">
            {model.active ? "ACTIVE" : "SELECTED"} · {model.lifecycleState} · {model.health}
          </p>
        </div>
        <div className="lv-row-actions">
          {!model.active ? (
            <button className="lv-btn lv-btn-gold" type="button" disabled={busy} onClick={onActivate}>
              Activate
            </button>
          ) : null}
          {loadSupported ? (
            <button className="lv-btn" type="button" disabled={busy} onClick={onLoad}>
              Load
            </button>
          ) : (
            <span className="lv-muted">Managed externally by runtime</span>
          )}
          {unloadSupported ? (
            <button className="lv-btn" type="button" disabled={busy} onClick={onUnload}>
              Unload
            </button>
          ) : null}
          <button className="lv-btn lv-btn-danger" type="button" disabled={busy} onClick={onDelete}>
            Remove
          </button>
        </div>
      </div>

      <div className="lv-tabs" role="tablist">
        {(
          [
            ["overview", "Overview"],
            ["capabilities", "Capabilities"],
            ["profile", "Profile"],
            ["runtime", "Runtime"],
            ["resources", "Resources"],
            ["benchmarks", "Benchmarks"],
            ["diagnostics", "Diagnostics"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            className={`lv-tab${tab === id ? " is-active" : ""}`}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => onTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <div className="lv-meta-grid">
          {(
            [
              ["ID", model.id],
              ["Display Name", model.displayName],
              ["Provider", model.providerId],
              ["Runtime", model.runtimeId],
              ["Family", model.family],
              ["Architecture", model.architecture],
              ["Parameters", model.parameterCount],
              ["Quantization", model.quantization],
              ["Format", model.format],
              ["Disk Size", formatBytes(model.diskSizeBytes)],
              ["Context Length", model.contextWindow],
              ["Max Output", model.maxOutputTokens],
              ["Source", model.source],
              ["Local Path", model.localPath],
              ["Endpoint", model.endpoint],
              ["Last Discovered", model.lastDiscoveredAt],
              ["Last Used", model.lastUsedAt],
            ] as const
          ).map(([label, value]) => (
            <div className="lv-meta-item" key={label}>
              <span>{label}</span>
              <strong title={dash(value)}>{dash(value)}</strong>
            </div>
          ))}
        </div>
      ) : null}

      {tab === "capabilities" ? (
        <div className="lv-models-cap-list">
          <button className="lv-btn" type="button" disabled={busy} onClick={onProbe}>
            Probe capabilities
          </button>
          <table className="lv-models-table">
            <thead>
              <tr>
                <th>Capability</th>
                <th>Declared</th>
                <th>Verified</th>
                <th>Last tested</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {capabilities.map((cap) => (
                <tr key={cap.capability}>
                  <td>{cap.capability}</td>
                  <td>{cap.declared}</td>
                  <td>{cap.verified}</td>
                  <td>{dash(cap.lastTestedAt)}</td>
                  <td>{dash(cap.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {tab === "profile" ? (
        <form
          className="lv-models-profile"
          onSubmit={(e) => {
            e.preventDefault();
            void onSaveProfile(draft, true);
          }}
        >
          {dirty ? <p className="lv-models-dirty">Unsaved changes</p> : null}
          <label>
            Temperature ({draft.temperature.toFixed(2)})
            <input
              type="range"
              min={0}
              max={2}
              step={0.01}
              value={draft.temperature}
              onChange={(e) => setDraft({ ...draft, temperature: Number(e.target.value) })}
            />
          </label>
          <label>
            Top-P ({draft.topP.toFixed(2)})
            <input
              type="range"
              min={0.01}
              max={1}
              step={0.01}
              value={draft.topP}
              onChange={(e) => setDraft({ ...draft, topP: Number(e.target.value) })}
            />
          </label>
          <label>
            Top-K ({draft.topK})
            <input
              type="range"
              min={0}
              max={500}
              step={1}
              value={draft.topK}
              onChange={(e) => setDraft({ ...draft, topK: Number(e.target.value) })}
            />
          </label>
          <label>
            Repeat penalty ({draft.repeatPenalty.toFixed(2)})
            <input
              type="range"
              min={0.5}
              max={2}
              step={0.01}
              value={draft.repeatPenalty}
              onChange={(e) => setDraft({ ...draft, repeatPenalty: Number(e.target.value) })}
            />
          </label>
          <label>
            Max tokens
            <input
              className="lv-input"
              type="number"
              min={1}
              max={131072}
              value={draft.maxTokens}
              onChange={(e) => setDraft({ ...draft, maxTokens: Number(e.target.value) })}
            />
          </label>
          <label>
            Seed (-1 = random)
            <input
              className="lv-input"
              type="number"
              min={-1}
              max={2147483647}
              value={draft.seed}
              onChange={(e) => setDraft({ ...draft, seed: Number(e.target.value) })}
            />
          </label>
          <label>
            System prompt
            <textarea
              className="lv-input lv-models-prompt"
              rows={6}
              value={draft.systemPrompt}
              onChange={(e) => setDraft({ ...draft, systemPrompt: e.target.value })}
            />
          </label>
          <div className="lv-row-actions">
            <button className="lv-btn lv-btn-gold" type="submit" disabled={busy || !dirty}>
              Save &amp; Activate
            </button>
            <button
              className="lv-btn"
              type="button"
              disabled={!dirty}
              onClick={() => setDraft(profile)}
            >
              Revert unsaved changes
            </button>
            <button
              className="lv-btn"
              type="button"
              disabled={busy || !dirty}
              onClick={() => void onSaveProfile(draft, false)}
            >
              Save only
            </button>
          </div>
        </form>
      ) : null}

      {tab === "runtime" ? (
        <div className="lv-meta-grid">
          <div className="lv-meta-item">
            <span>Provider</span>
            <strong>{dash(provider?.name)}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Type</span>
            <strong>{dash(provider?.type)}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Endpoint</span>
            <strong>{dash(provider?.endpoint ?? model.endpoint)}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Health</span>
            <strong>{dash(provider?.health)}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Load</span>
            <strong>{loadSupported ? "Supported" : "Unsupported"}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Unload</span>
            <strong>{unloadSupported ? "Supported" : "Unsupported"}</strong>
          </div>
          {!loadSupported ? (
            <p className="lv-muted">Managed externally by {provider?.name ?? "runtime"}</p>
          ) : null}
        </div>
      ) : null}

      {tab === "resources" ? (
        <div>
          <div className="lv-meta-grid">
            <div className="lv-meta-item">
              <span>Preflight</span>
              <strong>{dash(preflight?.verdict as string)}</strong>
            </div>
            <div className="lv-meta-item">
              <span>Estimated</span>
              <strong>{preflight?.estimated ? "Yes" : "—"}</strong>
            </div>
          </div>
          <p className="lv-muted">
            {(Array.isArray(preflight?.reasons) ? (preflight.reasons as string[]) : []).join(" · ") ||
              "No resource attribution available for this model"}
          </p>
          <p className="lv-muted">
            Model-specific VRAM is only shown when the runtime can attribute memory to this model.
          </p>
        </div>
      ) : null}

      {tab === "benchmarks" ? (
        <div className="lv-row-actions">
          <button className="lv-btn lv-btn-gold" type="button" disabled={busy} onClick={onBenchmark}>
            Run Quick Benchmark
          </button>
          <Link className="lv-btn" to="/training">
            Open Benchmarks / Training
          </Link>
          <p className="lv-muted">Raw metrics only — no automatic “best model” ranking.</p>
        </div>
      ) : null}

      {tab === "diagnostics" ? (
        <div className="lv-meta-grid">
          <div className="lv-meta-item">
            <span>Lifecycle</span>
            <strong>{model.lifecycleState}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Health</span>
            <strong>{model.health}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Loaded</span>
            <strong>{model.loaded == null ? "—" : model.loaded ? "yes" : "no"}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Last error</span>
            <strong>{dash((model.metadata?.lastError as string) ?? null)}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Provider last error</span>
            <strong>{dash(provider?.lastError)}</strong>
          </div>
          <div className="lv-meta-item">
            <span>Provider latency</span>
            <strong>
              {provider?.lastLatencyMs == null ? "—" : `${Math.round(provider.lastLatencyMs)} ms`}
            </strong>
          </div>
        </div>
      ) : null}
    </section>
  );
}
