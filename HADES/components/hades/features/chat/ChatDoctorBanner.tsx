"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCcw, Settings2, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { hadesApi, type AppSettings, type SystemHealth } from "@/lib/hades-api";

export type ChatDoctorState =
  | { kind: "ok"; model: string }
  | { kind: "backend" }
  | { kind: "lm_unavailable" }
  | { kind: "lm_no_model" }
  | { kind: "embeddings_misconfig"; model: string; detail: string }
  | { kind: "lexical_only"; model: string; detail: string };

export function diagnoseChatDoctor(health: SystemHealth | null, settings: AppSettings | null): ChatDoctorState {
  if (!health) return { kind: "backend" };
  if (health.backend && health.backend !== "ok") return { kind: "backend" };
  if (health.lm_studio !== "connected") return { kind: "lm_unavailable" };
  if (!health.active_model) return { kind: "lm_no_model" };
  const semantic = Boolean(settings?.enable_semantic_retrieval);
  const embeddingId = String(settings?.embedding_model_id || "").trim();
  if (semantic && !embeddingId) {
    return {
      kind: "embeddings_misconfig",
      model: health.active_model,
      detail: "Semantische retrieval staat aan zonder embedding-model. Chat werkt lexical-only tot je een embedding-model kiest onder Instellingen → Geavanceerd.",
    };
  }
  if (!embeddingId) {
    return {
      kind: "lexical_only",
      model: health.active_model,
      detail: "Chat werkt. Semantische retrieval is lexical-only (geen embedding-model geselecteerd).",
    };
  }
  return { kind: "ok", model: health.active_model };
}

/** Honest Chat-surface doctor — reuses /api/health + settings; no second health subsystem. */
export function ChatDoctorBanner({
  health,
  settings,
  onRetry,
  showLexicalHint = false,
}: {
  health: SystemHealth | null;
  settings: AppSettings | null;
  onRetry?: () => void;
  /** Soft lexical-only guidance (not an error). */
  showLexicalHint?: boolean;
}) {
  const state = diagnoseChatDoctor(health, settings);
  if (state.kind === "ok") return null;
  if (state.kind === "lexical_only" && !showLexicalHint) return null;

  const copy = (() => {
    switch (state.kind) {
      case "backend":
        return {
          title: "HADES-backend niet bereikbaar",
          body: "De interface kan de lokale API niet bereiken. Controleer of HADES is gestart en of de API-poort vrij is (geen vreemd proces).",
          tone: "danger" as const,
        };
      case "lm_unavailable":
        return {
          title: "LM Studio niet bereikbaar",
          body: "Start LM Studio lokaal en controleer de URL onder Instellingen. Chat kan pas antwoorden als de lokale server bereikbaar is.",
          tone: "warning" as const,
        };
      case "lm_no_model":
        return {
          title: "LM Studio werkt, maar er is geen model geladen",
          body: "Laad een model in LM Studio of kies een actief model onder Modellen. Dit is géén gezonde groene staat.",
          tone: "warning" as const,
        };
      case "embeddings_misconfig":
      case "lexical_only":
        return {
          title: state.kind === "lexical_only" ? "Retrieval: lexical-only" : "Embeddings niet geconfigureerd",
          body: state.detail,
          tone: "info" as const,
        };
      default:
        return { title: "Status", body: "", tone: "info" as const };
    }
  })();

  return (
    <div className={`chat-doctor chat-doctor-${copy.tone}`} role="status" aria-live="polite" data-doctor-kind={state.kind}>
      <div className="chat-doctor-icon" aria-hidden="true">
        {state.kind === "backend" ? <WifiOff size={18} /> : <AlertTriangle size={18} />}
      </div>
      <div className="chat-doctor-body">
        <strong>{copy.title}</strong>
        <p>{copy.body}</p>
        <div className="chat-doctor-actions">
          {onRetry ? (
            <Button type="button" size="sm" variant="outline" onClick={onRetry}>
              <RefreshCcw /> Opnieuw verbinden
            </Button>
          ) : null}
          {state.kind === "lm_unavailable" || state.kind === "lm_no_model" || state.kind === "embeddings_misconfig" || state.kind === "lexical_only" ? (
            <Button type="button" size="sm" variant="outline" onClick={() => { window.location.hash = "/settings"; }}>
              <Settings2 /> Instellingen
            </Button>
          ) : null}
          {state.kind === "lm_no_model" ? (
            <Button type="button" size="sm" variant="outline" onClick={() => { window.location.hash = "/models"; }}>
              Modellen
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function useChatDoctor(): {
  health: SystemHealth | null;
  settings: AppSettings | null;
  state: ChatDoctorState;
  refresh: () => void;
} {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([hadesApi.health().catch(() => null), hadesApi.settings().catch(() => null)]).then(([h, s]) => {
      if (cancelled) return;
      setHealth(h);
      setSettings(s?.values ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return {
    health,
    settings,
    state: diagnoseChatDoctor(health, settings),
    refresh: () => setTick((value) => value + 1),
  };
}
