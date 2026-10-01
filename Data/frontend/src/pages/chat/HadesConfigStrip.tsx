import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import type { CapabilityListItem, ModelDescriptor } from "../../types/api";
import {
  REASONING_MODE_OPTIONS,
  type ReasoningModeId,
} from "../../lib/chat/reasoningModes";
import { formatModelParams } from "../../lib/chat/formatModelParams";
import { classifyCapability, isCapabilityActive } from "./chatHelpers";

export type HadesConfigStripProps = {
  models: ModelDescriptor[];
  nonChatModels: ModelDescriptor[];
  selectedModelId: string | null;
  onSelectModel: (modelId: string | null) => void;
  collaborationStrategy: "direct" | "team";
  onCollaborationChange: (value: "direct" | "team") => void;
  reasoningMode: ReasoningModeId;
  onReasoningChange: (value: ReasoningModeId) => void;
  capabilities: CapabilityListItem[];
  busy?: boolean;
};

type OpenMenu = "model" | "agent" | "reason" | "tools" | null;

const AGENT_OPTIONS: Array<{
  id: "direct" | "team";
  label: string;
  meta: string;
}> = [
  {
    id: "direct",
    label: "Hades (Standaard)",
    meta: "Universele assistent • Onderzoek, analyse, code, data",
  },
  {
    id: "team",
    label: "TEAM",
    meta: "Samenwerking tot kwaliteitscriteria zijn gehaald",
  },
];

const TOOL_KIND_ORDER = ["web", "rag", "python", "data"] as const;
const TOOL_KIND_LABEL: Record<(typeof TOOL_KIND_ORDER)[number], string> = {
  web: "Web",
  rag: "RAG",
  python: "Python",
  data: "Data",
};

function Chevron() {
  return (
    <svg className="lv-v2-select-card__chevron" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M7 10l5 5 5-5" />
    </svg>
  );
}

function modelMetaLine(model: ModelDescriptor): string {
  const family = model.family || model.providerId || "Model";
  const params = formatModelParams(model.parameterCount);
  const quant = model.quantization?.trim();
  const bits = [family, params].filter(Boolean).join(" / ");
  if (quant) return `${bits} • ${quant}`;
  return bits || model.id;
}

/**
 * Combobox-style select card — trigger is a button; menu is a sibling panel
 * (never nested interactive controls inside the trigger).
 */
function SelectCardShell({
  menuId,
  label,
  value,
  meta,
  icon,
  iconClass,
  badge,
  statusDot,
  open,
  busy,
  haspopup,
  onToggle,
  children,
}: {
  menuId: string;
  label: string;
  value: string;
  meta: string;
  icon: ReactNode;
  iconClass: string;
  badge?: string | null;
  statusDot?: boolean;
  open: boolean;
  busy: boolean;
  haspopup: "listbox" | "dialog";
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className={`lv-v2-select-card${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="lv-v2-select-card__trigger"
        aria-expanded={open}
        aria-haspopup={haspopup}
        aria-controls={menuId}
        disabled={busy}
        onClick={onToggle}
      >
        <span className={`lv-v2-select-card__icon ${iconClass}`} aria-hidden="true">
          {icon}
        </span>
        <span className="lv-v2-select-card__body">
          <span className="lv-v2-select-card__label">{label}</span>
          <span className="lv-v2-select-card__value">{value}</span>
          <span className="lv-v2-select-card__meta">{meta}</span>
        </span>
        {badge ? <span className="lv-v2-select-card__badge">{badge}</span> : null}
        {statusDot ? (
          <span className="lv-v2-status-dot lv-v2-status-dot--success" aria-hidden="true" />
        ) : null}
        <Chevron />
      </button>
      {open ? (
        <div
          id={menuId}
          className="lv-v2-select-card__menu"
          role={haspopup === "listbox" ? "listbox" : "dialog"}
          aria-label={label}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

export function HadesConfigStrip({
  models,
  nonChatModels,
  selectedModelId,
  onSelectModel,
  collaborationStrategy,
  onCollaborationChange,
  reasoningMode,
  onReasoningChange,
  capabilities,
  busy = false,
}: HadesConfigStripProps) {
  const [open, setOpen] = useState<OpenMenu>(null);
  const stripRef = useRef<HTMLDivElement | null>(null);
  const baseId = useId();

  const selectedModel = useMemo(
    () => models.find((m) => m.id === selectedModelId) ?? null,
    [models, selectedModelId],
  );

  const modelValue = selectedModel?.displayName || selectedModel?.id || "Auto";
  const modelMeta = selectedModel
    ? modelMetaLine(selectedModel)
    : "Router kiest het beste chat-model";
  const formatBadge = selectedModel?.format?.trim() || null;

  const agent = AGENT_OPTIONS.find((o) => o.id === collaborationStrategy) ?? AGENT_OPTIONS[0];
  const reasoning =
    REASONING_MODE_OPTIONS.find((o) => o.id === reasoningMode) ?? REASONING_MODE_OPTIONS[0];

  const activeCount = capabilities.filter(isCapabilityActive).length;
  const totalCount = capabilities.length;
  const kindLabels = useMemo(() => {
    const present = new Set(
      capabilities.map((c) => classifyCapability(c)).filter((k) => k !== "other" && k !== "vision"),
    );
    return TOOL_KIND_ORDER.filter((k) => present.has(k)).map((k) => TOOL_KIND_LABEL[k]);
  }, [capabilities]);
  const toolsMeta =
    kindLabels.length > 0
      ? `${kindLabels.join(", ")}${kindLabels.length < 4 && totalCount > kindLabels.length ? "…" : ""}`
      : totalCount === 0
        ? "Geen capabilities geladen"
        : "Beschikbare tools zie Tools-pagina";

  useEffect(() => {
    if (!open) return;
    const onDoc = (event: MouseEvent) => {
      const root = stripRef.current;
      if (!root || root.contains(event.target as Node)) return;
      setOpen(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(null);
        return;
      }
      if (!stripRef.current?.contains(event.target as Node)) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        const menu = stripRef.current.querySelector<HTMLElement>(
          ".lv-v2-select-card.is-open .lv-v2-select-card__menu",
        );
        if (!menu) return;
        const options = Array.from(
          menu.querySelectorAll<HTMLElement>('[role="option"]:not([disabled])'),
        );
        if (!options.length) return;
        event.preventDefault();
        const current = document.activeElement as HTMLElement | null;
        const idx = options.indexOf(current as HTMLElement);
        let next = 0;
        if (event.key === "ArrowDown") {
          next = idx < 0 ? 0 : (idx + 1) % options.length;
        } else {
          next = idx <= 0 ? options.length - 1 : idx - 1;
        }
        options[next]?.focus();
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function toggle(menu: OpenMenu) {
    if (busy) return;
    setOpen((prev) => (prev === menu ? null : menu));
  }

  return (
    <div className="lv-v2-config-strip" ref={stripRef} aria-label="Hades configuratie">
      <SelectCardShell
        menuId={`${baseId}-model`}
        label="Geselecteerd Model"
        value={modelValue}
        meta={modelMeta}
        badge={formatBadge}
        open={open === "model"}
        busy={busy}
        haspopup="listbox"
        onToggle={() => toggle("model")}
        iconClass="lv-v2-select-card__icon--model"
        icon={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <rect x="4" y="4" width="16" height="16" rx="3" />
            <path d="M8 9h8M8 12h8M8 15h5" />
          </svg>
        }
      >
        <button
          type="button"
          role="option"
          aria-selected={selectedModelId === null}
          onClick={() => {
            onSelectModel(null);
            setOpen(null);
          }}
        >
          Auto
          <small>Router kiest chat-capable model</small>
        </button>
        {models.map((model) => (
          <button
            key={model.id}
            type="button"
            role="option"
            aria-selected={selectedModelId === model.id}
            onClick={() => {
              onSelectModel(model.id);
              setOpen(null);
            }}
          >
            {model.displayName || model.id}
            <small>{modelMetaLine(model)}</small>
          </button>
        ))}
        {models.length === 0 ? (
          <div className="lv-v2-muted" style={{ padding: "8px 10px", fontSize: 12 }}>
            Geen chat-capable models. Configureer er een onder Models.
          </div>
        ) : null}
        {nonChatModels.length > 0 ? (
          <div className="lv-v2-muted" style={{ padding: "8px 10px", fontSize: 11 }}>
            {nonChatModels.length} niet-chat model
            {nonChatModels.length === 1 ? "" : "len"} verborgen
          </div>
        ) : null}
      </SelectCardShell>

      <SelectCardShell
        menuId={`${baseId}-agent`}
        label="AI Agent"
        value={agent.label}
        meta={agent.meta}
        open={open === "agent"}
        busy={busy}
        haspopup="listbox"
        onToggle={() => toggle("agent")}
        iconClass="lv-v2-select-card__icon--agent"
        icon={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="12" cy="8" r="3.5" />
            <path d="M5 19c1.5-3.5 4-5 7-5s5.5 1.5 7 5" />
          </svg>
        }
      >
        {AGENT_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            role="option"
            aria-selected={collaborationStrategy === option.id}
            onClick={() => {
              onCollaborationChange(option.id);
              setOpen(null);
            }}
          >
            {option.label}
            <small>{option.meta}</small>
          </button>
        ))}
      </SelectCardShell>

      <SelectCardShell
        menuId={`${baseId}-reason`}
        label="Reasoning Modus"
        value={reasoning.label}
        meta={reasoning.meta}
        open={open === "reason"}
        busy={busy}
        haspopup="listbox"
        onToggle={() => toggle("reason")}
        iconClass="lv-v2-select-card__icon--reason"
        icon={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M12 3a6 6 0 0 1 4.5 9.8V16a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-3.2A6 6 0 0 1 12 3z" />
            <path d="M9 19h6M10 21.5h4" />
          </svg>
        }
      >
        {REASONING_MODE_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            role="option"
            aria-selected={reasoningMode === option.id}
            onClick={() => {
              onReasoningChange(option.id);
              setOpen(null);
            }}
          >
            {option.label}
            <small>{option.meta}</small>
          </button>
        ))}
      </SelectCardShell>

      <SelectCardShell
        menuId={`${baseId}-tools`}
        label="Tools & Integraties"
        value={totalCount === 0 ? "UNMEASURED" : `${activeCount}/${totalCount} beschikbaar`}
        meta={toolsMeta || "beschikbaar ≠ actief deze beurt"}
        statusDot={totalCount > 0 && activeCount === totalCount}
        open={open === "tools"}
        busy={busy}
        haspopup="dialog"
        onToggle={() => toggle("tools")}
        iconClass="lv-v2-select-card__icon--tools"
        icon={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M14 7l3 3-8 8H6v-3l8-8z" />
            <path d="M12 5l2-2 5 5-2 2" />
          </svg>
        }
      >
        {capabilities.length === 0 ? (
          <div className="lv-v2-muted" style={{ padding: "8px 10px", fontSize: 12 }}>
            Geen capability-lijst geladen.
          </div>
        ) : (
          <ul className="lv-v2-select-card__status-list" role="list" aria-label="Tools status (read-only)">
            {capabilities.slice(0, 24).map((cap) => {
              const active = isCapabilityActive(cap);
              const kind = classifyCapability(cap);
              const reason =
                cap.availability_reason ||
                cap.unavailable_reason ||
                (active ? "Beschikbaar" : "Niet beschikbaar");
              return (
                <li
                  key={cap.id}
                  className="lv-v2-select-card__status-row"
                  title={`${reason} — status only, not a policy toggle`}
                >
                  <span className="lv-v2-select-card__status-name">{cap.name || cap.id}</span>
                  <small>
                    {TOOL_KIND_LABEL[kind as keyof typeof TOOL_KIND_LABEL] || kind} ·{" "}
                    {active ? "beschikbaar" : "niet beschikbaar"}
                  </small>
                </li>
              );
            })}
          </ul>
        )}
        <div className="lv-v2-muted" style={{ padding: "8px 10px", fontSize: 11 }}>
          Status indicators only — policy changes live on the Tools page.
        </div>
      </SelectCardShell>
    </div>
  );
}
