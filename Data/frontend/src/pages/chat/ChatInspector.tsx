import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type {
  AssistantTurnTelemetry,
  KnowledgeSource,
  SystemTelemetryResponse,
} from "../../types/api";
import { formatTokenCount } from "./chatHelpers";

export type ChatInspectorProps = {
  /** Measured context tokens used (or null/undefined → UNMEASURED). */
  tokenUsage?: number | null;
  contextBudget?: number | null;
  memoryCount?: number | null;
  /** Real preferences label from backend when available; never invent "Aangepast". */
  preferencesLabel?: string | null;
  /** Real project/context label when available; never invent a title. */
  projectContext?: string | null;
  knowledgeSources?: KnowledgeSource[];
  /** Raw verification string from last turn — drives badge tone. */
  verification?: string | null;
  systemTelemetry?: SystemTelemetryResponse | null;
  lastTurnTelemetry?: AssistantTurnTelemetry | null;
  /** Mobile drawer open — adds is-drawer-open for CSS. */
  drawerOpen?: boolean;
};

function trustTone(verification: string | null | undefined): {
  label: string;
  className: string;
} {
  const raw = (verification || "").trim();
  if (!raw) {
    return { label: "UNMEASURED", className: "lv-v2-trust-badge lv-v2-trust-badge--unknown" };
  }
  const upper = raw.toUpperCase();
  if (/(CONFLICT|FAIL|FALSE|REJECT)/.test(upper)) {
    return { label: raw, className: "lv-v2-trust-badge lv-v2-trust-badge--conflict" };
  }
  if (/(UNVERIF|UNKNOWN|PENDING|UNMEASURED)/.test(upper)) {
    return { label: raw, className: "lv-v2-trust-badge lv-v2-trust-badge--unverified" };
  }
  if (/(VERIF|TRUST|PASS|TRUE|OK)/.test(upper)) {
    return { label: raw, className: "lv-v2-trust-badge" };
  }
  return { label: raw, className: "lv-v2-trust-badge lv-v2-trust-badge--unknown" };
}

function sourceHost(source: KnowledgeSource): string {
  const blob = source.source || "";
  try {
    if (/^https?:\/\//i.test(blob)) return new URL(blob).hostname;
  } catch {
    /* ignore */
  }
  return blob || source.id;
}

function meterPct(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function formatLatency(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "UNMEASURED";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

/** Extract tokens/s only when usage actually measured it (or compute from measured fields). */
function tokensPerSecond(usage: Record<string, number> | null | undefined, latencyMs: number | null | undefined): string {
  if (!usage) return "UNMEASURED";
  const direct =
    usage.tokens_per_second ??
    usage.tokens_per_sec ??
    usage.tok_s ??
    usage.throughput_tokens_per_s;
  if (typeof direct === "number" && Number.isFinite(direct) && direct > 0) {
    return `${Math.round(direct)} t/s`;
  }
  const out = usage.output_tokens ?? usage.completion_tokens ?? usage.tokens;
  if (
    typeof out === "number" &&
    Number.isFinite(out) &&
    out > 0 &&
    latencyMs != null &&
    Number.isFinite(latencyMs) &&
    latencyMs > 0
  ) {
    return `${Math.round((out / latencyMs) * 1000)} t/s`;
  }
  return "UNMEASURED";
}

function MeterRow({ label, pct }: { label: string; pct: number | null }) {
  return (
    <div className="lv-v2-meter-row">
      <span className="lv-v2-meter-row__label">{label}</span>
      <span className="lv-v2-meter-row__track" aria-hidden="true">
        <span
          className="lv-v2-meter-row__fill"
          style={{ width: pct == null ? "0%" : `${pct}%`, opacity: pct == null ? 0.25 : 1 }}
        />
      </span>
      <span className="lv-v2-meter-row__value">{pct == null ? "—" : `${pct}%`}</span>
    </div>
  );
}

export function ChatInspector({
  tokenUsage = null,
  contextBudget = null,
  memoryCount = null,
  preferencesLabel = null,
  projectContext = null,
  knowledgeSources = [],
  verification = null,
  systemTelemetry = null,
  lastTurnTelemetry = null,
  drawerOpen = false,
}: ChatInspectorProps) {
  const [showSources, setShowSources] = useState(true);

  const contextLabel = useMemo(() => {
    if (tokenUsage == null && contextBudget == null) return "UNMEASURED";
    if (tokenUsage != null && contextBudget != null) {
      return `${formatTokenCount(tokenUsage).replace(/ tokens$/, "")} / ${formatTokenCount(contextBudget)}`;
    }
    return formatTokenCount(tokenUsage ?? contextBudget);
  }, [tokenUsage, contextBudget]);

  const memoryLabel =
    memoryCount == null || !Number.isFinite(memoryCount)
      ? "UNMEASURED"
      : `${Math.round(memoryCount)} item${Math.round(memoryCount) === 1 ? "" : "s"}`;

  const preferencesDisplay = preferencesLabel?.trim() || "Niet beschikbaar";
  const projectDisplay = projectContext?.trim() || "Geen projectcontext";

  const trust = trustTone(verification);
  const dash = systemTelemetry?.dashboard;
  const latency = lastTurnTelemetry?.latency_ms ?? null;
  const throughput = tokensPerSecond(lastTurnTelemetry?.usage ?? null, latency);
  const live = systemTelemetry?.truth?.measured === true;

  const gpuMeters =
    systemTelemetry?.gpu?.devices?.map((d, i) => {
      const shortName = (d.name || "").replace(/^NVIDIA\s+/i, "").trim();
      const idx = d.index ?? i;
      return {
        label: shortName ? `GPU ${idx} - ${shortName}` : `GPU ${idx}`,
        pct: meterPct(d.utilizationPct ?? dash?.gpuPct),
      };
    }) ?? [];

  return (
    <aside
      className={`lv-v2-chat-col lv-v2-chat-col--inspector lv-v2-inspector${
        drawerOpen ? " is-drawer-open" : ""
      }`}
      aria-label="Context inspector"
    >
      <section className="lv-v2-inspector-card" aria-labelledby="inspector-context-title">
        <div className="lv-v2-inspector-card__head">
          <h3 className="lv-v2-inspector-card__title" id="inspector-context-title">
            Context & Geheugen
          </h3>
          <Link className="lv-v2-inspector-card__link" to="/memory">
            Beheren
          </Link>
        </div>
        <div className="lv-v2-inspector-row">
          <span className="lv-v2-inspector-row__label">Actieve gesprek context</span>
          <span className="lv-v2-inspector-row__value">{contextLabel}</span>
        </div>
        <div className="lv-v2-inspector-row">
          <span className="lv-v2-inspector-row__label">Langetermijn geheugen</span>
          <span className="lv-v2-inspector-row__value">{memoryLabel}</span>
        </div>
        <div className="lv-v2-inspector-row">
          <span className="lv-v2-inspector-row__label">Gebruikersvoorkeuren</span>
          <span className="lv-v2-inspector-row__value">{preferencesDisplay}</span>
        </div>
        <div className="lv-v2-inspector-row">
          <span className="lv-v2-inspector-row__label">Project context</span>
          <span className="lv-v2-inspector-row__value">{projectDisplay}</span>
        </div>
      </section>

      <section className="lv-v2-inspector-card" aria-labelledby="inspector-sources-title">
        <div className="lv-v2-inspector-card__head">
          <h3 className="lv-v2-inspector-card__title" id="inspector-sources-title">
            Bronnen & Verificatie
          </h3>
          <label className="lv-v2-toggle">
            <input
              type="checkbox"
              checked={showSources}
              onChange={(e) => setShowSources(e.target.checked)}
              aria-label="Toon bronnen"
            />
            Toon bronnen
          </label>
        </div>
        {showSources ? (
          knowledgeSources.length === 0 ? (
            <p className="lv-v2-muted" style={{ margin: 0, fontSize: 12 }}>
              Geen knowledge sources voor deze beurt.
            </p>
          ) : (
            knowledgeSources.map((source, index) => (
              <div className="lv-v2-source-row" key={source.id || `${source.title}-${index}`}>
                <span className="lv-v2-source-row__num">{index + 1}</span>
                <span>
                  <span className="lv-v2-source-row__title">{source.title || source.id}</span>
                  <span className="lv-v2-source-row__host">{sourceHost(source)}</span>
                </span>
                <span className={trust.className} title={verification || "UNMEASURED"}>
                  {trust.label}
                </span>
              </div>
            ))
          )
        ) : (
          <p className="lv-v2-muted" style={{ margin: 0, fontSize: 12 }}>
            Bronnen verborgen (UI-only toggle).
          </p>
        )}
        {!showSources || knowledgeSources.length === 0 ? (
          <div className="lv-v2-inspector-row" style={{ marginTop: 6 }}>
            <span className="lv-v2-inspector-row__label">Verificatie</span>
            <span className={trust.className}>{trust.label}</span>
          </div>
        ) : null}
      </section>

      <section className="lv-v2-inspector-card" aria-labelledby="inspector-metrics-title">
        <div className="lv-v2-inspector-card__head">
          <h3 className="lv-v2-inspector-card__title" id="inspector-metrics-title">
            Systeem Metrics
          </h3>
          {live ? (
            <span className="lv-v2-live-badge">
              <span className="lv-v2-status-dot lv-v2-status-dot--success lv-v2-status-dot--pulse" aria-hidden="true" />
              Live
            </span>
          ) : (
            <span className="lv-v2-muted" style={{ fontSize: 10 }}>
              {systemTelemetry ? "Sample" : "Geen telemetry"}
            </span>
          )}
        </div>
        {gpuMeters.length > 0
          ? gpuMeters.map((row) => <MeterRow key={row.label} label={row.label} pct={row.pct} />)
          : (
            <MeterRow label="GPU" pct={meterPct(dash?.gpuPct)} />
          )}
        <MeterRow label="CPU" pct={meterPct(dash?.cpuPct ?? systemTelemetry?.cpu?.utilizationPct)} />
        <MeterRow
          label="Systeem RAM"
          pct={meterPct(dash?.ramPct ?? systemTelemetry?.memory?.utilizationPct)}
        />
        <div className="lv-v2-inspector-row">
          <span className="lv-v2-inspector-row__label">Response tijd</span>
          <span className="lv-v2-inspector-row__value">{formatLatency(latency)}</span>
        </div>
        <div className="lv-v2-inspector-row">
          <span className="lv-v2-inspector-row__label">Throughput</span>
          <span className="lv-v2-inspector-row__value">{throughput}</span>
        </div>
      </section>
    </aside>
  );
}
