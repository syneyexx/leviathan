import { useMemo, useRef, type RefObject } from "react";
import type { CapabilityListItem } from "../../types/api";
import type { ChatAttachment } from "../../lib/chat/attachments";
import {
  REASONING_MODE_OPTIONS,
  type ReasoningModeId,
} from "../../lib/chat/reasoningModes";
import type { ChatPromptPreset } from "../../lib/chat/promptPresets";
import { classifyCapability, isCapabilityActive } from "./chatHelpers";

export type ChatComposerQuickPrompt = ChatPromptPreset;

export type ChatComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  busy?: boolean;
  disabled?: boolean;
  reasoningMode: ReasoningModeId;
  onReasoningChange: (value: ReasoningModeId) => void;
  capabilities?: CapabilityListItem[];
  contextWindow?: number | null;
  selectedModelId?: string | null;
  quickPrompts?: ChatComposerQuickPrompt[];
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  placeholder?: string;
  attachmentsEnabled?: boolean | null;
  attachmentsUnavailableReason?: string | null;
  attachments?: ChatAttachment[];
  onAttachFiles?: (files: FileList) => void;
  onRemoveAttachment?: (localId: string) => void;
  visionHonestyReason?: string | null;
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
  attachmentsEnabled = null,
  attachmentsUnavailableReason = null,
  attachments = [],
  onAttachFiles,
  onRemoveAttachment,
  visionHonestyReason = null,
}: ChatComposerProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const tools = useMemo(() => toolStatuses(capabilities), [capabilities]);
  const counter =
    selectedModelId != null &&
    contextWindow != null &&
    Number.isFinite(contextWindow) &&
    contextWindow > 0
      ? `${value.length} characters · ~${Math.max(1, Math.ceil(value.length / 4))} estimated tokens / ${Math.round(contextWindow / 1000)}K context`
      : `${value.length} characters`;
  const attachOk = attachmentsEnabled === true && typeof onAttachFiles === "function";
  const attachTitle = attachOk
    ? "Bijlage toevoegen (ArtifactStore)"
    : attachmentsUnavailableReason ||
      (attachmentsEnabled === false
        ? "Bijlagen uitgeschakeld in deze runtime"
        : "Bijlage-capability UNKNOWN");
  const canSend =
    !busy &&
    !disabled &&
    (value.trim().length > 0 || attachments.some((a) => a.state === "ready")) &&
    !attachments.some((a) => a.state === "uploading");

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

      {attachments.length > 0 ? (
        <ul className="lv-v2-composer__attachments" aria-label="Bijlagen">
          {attachments.map((att) => (
            <li key={att.localId} className={`lv-v2-composer__attachment is-${att.state}`}>
              <span>
                {att.fileName} · {(att.sizeBytes / 1024).toFixed(1)} KiB · {att.mimeType || "unknown"} ·{" "}
                {att.state}
                {att.error ? ` — ${att.error}` : null}
              </span>
              {att.state !== "uploading" && onRemoveAttachment ? (
                <button type="button" onClick={() => onRemoveAttachment(att.localId)}>
                  Verwijder
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {visionHonestyReason ? (
        <p className="lv-v2-muted" style={{ fontSize: 11, margin: "0 0 6px" }}>
          {visionHonestyReason}
        </p>
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
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files && e.target.files.length && onAttachFiles) {
              onAttachFiles(e.target.files);
            }
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className="lv-v2-composer__tool"
          disabled={!attachOk || busy || disabled}
          title={attachTitle}
          aria-disabled={!attachOk}
          onClick={() => {
            if (attachOk) fileInputRef.current?.click();
          }}
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
            className={`lv-v2-composer__tool${tool.available ? " is-available" : ""}`}
            aria-disabled="true"
            title={`${tool.reason} — status indicator, not a toggle`}
            disabled
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
          onChange={(e) => onReasoningChange(e.target.value as ReasoningModeId)}
        >
          {REASONING_MODE_OPTIONS.map((opt) => (
            <option key={opt.id} value={opt.id}>
              {opt.shortLabel}
            </option>
          ))}
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
