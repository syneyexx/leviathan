import { useNavigate } from "react-router-dom";
import type { SettingsWorkspace } from "../../hooks/useSettingsWorkspace";
import type { ModelProvider } from "../../types/api";
import { Button, StatusDot } from "../ui";

type Props = {
  ws: SettingsWorkspace;
};

function providerTone(health: string): "success" | "warning" | "danger" | "muted" {
  const h = health.toLowerCase();
  if (h === "healthy" || h === "connected") return "success";
  if (h === "degraded" || h === "rate_limited" || h === "connecting") return "warning";
  if (h === "offline" || h === "auth_failed" || h === "timeout" || h === "error") return "danger";
  return "muted";
}

function providerStatusLabel(p: ModelProvider): string {
  const h = (p.health || "unknown").toLowerCase();
  if (!p.apiKeyConfigured && !p.endpoint && h === "unknown") return "Niet geconfigureerd";
  if (!p.enabled) return "Uitgeschakeld";
  if (h === "healthy") return "Verbonden";
  if (h === "offline") return "Offline";
  if (h === "timeout") return "Timeout";
  if (h === "auth_failed") return "Auth mislukt";
  if (h === "degraded") return "Degraded";
  if (h === "unknown") {
    return p.apiKeyConfigured || p.endpoint ? "Geconfigureerd" : "Niet geconfigureerd";
  }
  return p.health;
}

function providerKindLabel(type: string): string {
  const t = type.toLowerCase();
  if (t.includes("lm_studio") || t.includes("lmstudio")) return "Local LLM runtime";
  if (t.includes("ollama")) return "Lokale model provider";
  if (t.includes("vllm")) return "Lokale serving runtime";
  if (t.includes("openai")) return "Cloud API provider";
  if (t.includes("anthropic")) return "Cloud API provider";
  if (t.includes("gemini") || t.includes("google")) return "Cloud API provider";
  if (t.includes("mistral")) return "Cloud API provider";
  if (t.includes("groq")) return "Cloud API provider";
  return type || "Provider";
}

export function SettingsProvidersPanel({ ws }: Props) {
  const navigate = useNavigate();

  return (
    <section className="lv-v2-settings-providers" aria-label="Model Providers">
      <div className="lv-v2-settings-panel-head">
        <div>
          <h3>Model Providers</h3>
          <p>Configureer lokale en cloud AI model providers</p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            ws.setProviderDrawerOpen(true);
            navigate("/models");
          }}
        >
          Providers beheren
        </Button>
      </div>

      <ul className="lv-v2-settings-provider-list">
        {ws.providers.length === 0 && !ws.loading ? (
          <li className="lv-v2-settings-provider-row is-empty">
            <span>Geen providers in Model Control Plane</span>
          </li>
        ) : null}
        {ws.providers.map((p) => (
          <li key={p.id} className="lv-v2-settings-provider-row">
            <div className="lv-v2-settings-provider-row__main">
              <StatusDot tone={providerTone(p.health)} />
              <div>
                <strong>{p.name}</strong>
                <small>{providerKindLabel(p.type)}</small>
              </div>
            </div>
            <div className="lv-v2-settings-provider-row__meta">
              <span className={`lv-v2-settings-provider-status is-${providerTone(p.health)}`}>
                {providerStatusLabel(p)}
              </span>
              <button
                type="button"
                className="lv-v2-settings-provider-config"
                onClick={() => navigate("/models")}
              >
                Configureren →
              </button>
            </div>
          </li>
        ))}
      </ul>
      <p className="lv-v2-settings-provider-note">
        Credentials worden nooit naar de browser teruggelezen. Status komt uit Model Control Plane health.
      </p>
    </section>
  );
}
