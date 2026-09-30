import { useState } from "react";
import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { Button, Panel, StatusDot } from "../ui";

type Props = {
  ws: ModelsWorkspace;
  onOpenProviders: () => void;
};

function ProviderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 9h8M8 12h8M8 15h5" />
    </svg>
  );
}

function Chevron() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M7 10l5 5 5-5" />
    </svg>
  );
}

const HEALTH_TONE: Record<string, "success" | "danger" | "muted" | "warning"> = {
  healthy: "success",
  offline: "danger",
  degraded: "warning",
};

function runtimeTone(state: string | undefined): "success" | "danger" | "muted" | "warning" {
  const s = (state || "").toUpperCase();
  if (s === "READY") return "success";
  if (s === "COLD" || s === "STARTING") return "warning";
  if (s === "DISABLED" || s === "SUPERVISOR_UNAVAILABLE" || s === "UNAVAILABLE") return "danger";
  return "muted";
}

export function ModelsRuntimeProviderCard({ ws, onOpenProviders }: Props) {
  const [open, setOpen] = useState(false);
  const provider = ws.activeProvider;
  const tone = provider ? HEALTH_TONE[provider.health] ?? "muted" : "muted";
  const caps = ws.capabilities?.capabilities;
  const version = caps?.providerVersion;
  const rt = ws.modelRuntime;
  const rtState = String(rt?.poolState || rt?.state || "UNMEASURED");
  const rtLabel =
    rtState === "READY"
      ? "Worker warm"
      : rtState === "COLD"
        ? "Worker koud (cold-start mogelijk)"
        : rtState === "STARTING"
          ? "Worker start"
          : rt?.acceptJobs
            ? rtState
            : `Worker ${rtState}`;

  return (
    <Panel title="Runtime Provider" icon={<ProviderIcon />} className="lv-v2-models-provider">
      <p className="lv-v2-muted lv-v2-models-provider__desc">
        Kies en beheer de inference engine. Provider-gezondheid en Worker Fabric
        model_runtime zijn aparte waarheden.
      </p>

      <div className="lv-v2-models-provider__select-wrap">
        <button
          type="button"
          className={`lv-v2-select-card${open ? " is-open" : ""}`}
          aria-expanded={open}
          aria-haspopup="listbox"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="lv-v2-select-card__icon lv-v2-select-card__icon--model" aria-hidden="true">
            <ProviderIcon />
          </span>
          <span className="lv-v2-select-card__body">
            <span className="lv-v2-select-card__value">
              {provider ? `${provider.name}${provider.type === "lm_studio" ? " (Lokaal)" : ""}` : "Geen provider"}
            </span>
            <span className="lv-v2-select-card__meta">{provider?.endpoint || "Geen endpoint geconfigureerd"}</span>
          </span>
          <Chevron />
          {open ? (
            <div className="lv-v2-select-card__menu" role="listbox" aria-label="Runtime provider">
              {ws.providers.length === 0 ? (
                <div className="lv-v2-muted" style={{ padding: "8px 10px", fontSize: 12 }}>
                  Geen providers geconfigureerd.
                </div>
              ) : (
                ws.providers.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    role="option"
                    aria-selected={p.id === provider?.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      ws.setActiveProviderId(p.id);
                      setOpen(false);
                    }}
                  >
                    {p.name}
                    <small>{p.endpoint}</small>
                  </button>
                ))
              )}
            </div>
          ) : null}
        </button>
      </div>

      <div className="lv-v2-models-provider__status">
        <StatusDot tone={tone} pulse={tone === "success"} />
        <span>{provider ? (provider.health === "healthy" ? "Provider verbonden" : provider.health) : "Onbekend"}</span>
        {version ? <span className="lv-v2-muted">v{String(version)}</span> : null}
      </div>

      <div className="lv-v2-models-provider__status" title={rt?.reason || undefined}>
        <StatusDot tone={runtimeTone(rtState)} />
        <span>{rtLabel}</span>
        {caps?.cliAvailable != null ? (
          <span className="lv-v2-muted">CLI {caps.cliAvailable ? "aan" : "uit"}</span>
        ) : null}
        {caps?.sdkAvailable != null ? (
          <span className="lv-v2-muted">
            SDK {caps.sdkReachable ? "bereikbaar" : caps.sdkAvailable ? "niet bereikbaar" : "niet geïnstalleerd"}
          </span>
        ) : null}
      </div>

      <div className="lv-v2-models-provider__actions">
        <Button
          variant="secondary"
          size="sm"
          loading={ws.providerConnecting}
          disabled={!provider}
          onClick={() => void ws.testProviderConnection()}
        >
          Test Connectie
        </Button>
        <Button variant="ghost" size="sm" onClick={onOpenProviders}>
          Instellingen
        </Button>
      </div>
    </Panel>
  );
}
