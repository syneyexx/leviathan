import { useMemo, type RefObject } from "react";
import type { CapabilityListItem } from "../../types/api";
import { classifyCapability, isCapabilityActive } from "./chatHelpers";

export type ChatComposerQuickPrompt = {
  label: string;
  text: string;
};

export type ChatComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  busy?: boolean;
  disabled?: boolean;
  reasoningMode: "auto" | "fast" | "deep";
  onReasoningChange: (value: "auto" | "fast" | "deep") => void;
  capabilities?: CapabilityListItem[];
  /** Selected model context window; null/undefined → Auto / UNMEASURED denominator. */
  contextWindow?: number | null;
  selectedModelId?: string | null;
  quickPrompts?: ChatComposerQuickPrompt[];
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  placeholder?: string;
};

type ToolStatus = {
  id: string;
  label: string;
  available: boolean;
  reason: string;
};

function toolStatuses(capabilities: CapabilityListItem[]): ToolStatus[] {
  const defs: Array<{ id: string; label: string; kinds: string[] }> = [
    { id: "web", label: "Web zoeken", kinds: ["web"] },
    { id: "python", label: "Code Interpreter", kinds: ["python"] },
    { id: "data", label: "Data Analyse", kinds: ["data"] },
    { id: "vision", label: "Vision", kinds: ["vision"] },
  ];

  return defs.map((def) => {
    const matches = capabilities.filter((c) => def.kinds.includes(classifyCapability(c)));
    if (matches.length === 0) {
      return {
        id: def.id,
        label: def.label,
        available: false,
        reason: "Geen matching capability in registry",
      };
    }
    const active = matches.some(isCapabilityActive);
    const inactive = matches.find((c) => !isCapabilityActive(c));
    return {
      id: def.id,
      label: def.label,
      available: active,
      reason: active
        ? "Capability beschikbaar (status — geen UI-toggle)"
        : String(
            inactive?.availability_reason ||
              inactive?.unavailable_reason ||
              "Capability niet beschikbaar",
          ),
    };
  });
}

export function ChatComposer({
  value,
  onChange,
  onSend,
  onStop,
  busy = false,
  disabled = false,
  reasoningMode,
  onReasoningChange,
  capabilities = [],
  contextWindow = null,
  selectedModelId = null,
  quickPrompts,
  textareaRef,
  placeholder = "Stel een vraag aan Hades AI...",
}: ChatComposerProps) {
  const tools = useMemo(() => toolStatuses(capabilities), [capabilities]);
  const denom =
    selectedModelId == null
      ? "UNMEASURED"
      : contextWindow != null && Number.isFinite(contextWindow) && contextWindow > 0
        ? String(Math.round(contextWindow))
        : "UNMEASURED";
  const counter = `${value.length}/${denom}`;
  const canSend = !busy && !disabled && value.trim().length > 0;

  return (
    <div className="lv-v2-composer">
      {quickPrompts && quickPrompts.length > 0 ? (
        <div className="lv-v2-quick-prompts" aria-label="Snelle prompts">
          {quickPrompts.map((item) => (
            <button
              key={item.label}
              type="button"
              disabled={busy || disabled}
              onClick={() => onChange(item.text)}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}

      <div className="lv-v2-composer__field">
        <textarea
          ref={textareaRef}
          rows={3}
          placeholder={placeholder}
          aria-label="Bericht aan Hades AI"
          value={value}
          disabled={busy || disabled}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSend) onSend();
            }
          }}
        />
        <span className="lv-v2-composer__counter" aria-live="polite">
          {counter}
        </span>
      </div>

      <div className="lv-v2-composer__toolbar">
        <button
          type="button"
          className="lv-v2-composer__tool"
          disabled
          title="Bestandsbijlagen worden nog niet ondersteund in chat"
          aria-disabled="true"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M21 12.5V18a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V8a3 3 0 0 1 3-3h7.5" />
            <path d="M15 3h6v6M14 10L21 3" />
          </svg>
          Bijlage
        </button>

        {tools.map((tool) => (
          <button
            key={tool.id}
            type="button"
            className={`lv-v2-composer__tool${tool.available ? " is-active" : ""}`}
            aria-pressed={tool.available}
            aria-disabled={!tool.available}
            title={tool.reason}
            disabled={!tool.available || busy}
            onClick={(e) => e.preventDefault()}
          >
            {tool.label}
          </button>
        ))}

        <span className="lv-v2-composer__spacer" />

        <label className="lv-v2-sr-only" htmlFor="hades-composer-reason">
          Reasoning modus
        </label>
        <select
          id="hades-composer-reason"
          className="lv-v2-composer__reason"
          aria-label="Reasoning modus"
          disabled={busy || disabled}
          value={reasoningMode}
          onChange={(e) => onReasoningChange(e.target.value as "auto" | "fast" | "deep")}
        >
          <option value="auto">Auto</option>
          <option value="fast">Snel</option>
          <option value="deep">Diep Redeneren</option>
        </select>

        {busy ? (
          <button
            type="button"
            className="lv-v2-composer__send lv-v2-composer__send--stop"
            onClick={() => onStop?.()}
            disabled={!onStop}
          >
            Stop
          </button>
        ) : (
          <button
            type="button"
            className="lv-v2-composer__send"
            disabled={!canSend}
            onClick={onSend}
          >
            Versturen
          </button>
        )}
      </div>
    </div>
  );
}
