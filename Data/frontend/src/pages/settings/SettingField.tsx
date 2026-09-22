import type { SettingState } from "../../types/api";
import { RestartRequiredBadge } from "./RestartRequiredBadge";

type Props = {
  setting: SettingState;
  draft: unknown;
  disabled?: boolean;
  onChange: (value: unknown) => void;
  onSave: () => void;
  onReset: () => void;
  onClearSecret?: () => void;
  busy?: boolean;
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

export function SettingField({
  setting,
  draft,
  disabled,
  onChange,
  onSave,
  onReset,
  onClearSecret,
  busy,
}: Props) {
  const readOnly = disabled || !setting.editable;
  const inputId = `setting-${setting.key}`;

  return (
    <div className={`lv-settings-field${setting.dangerous ? " is-dangerous" : ""}`}>
      <div className="lv-settings-field-head">
        <label htmlFor={inputId}>
          {setting.label}
          {setting.dangerous ? <span className="lv-settings-danger-mark">!</span> : null}
        </label>
        <RestartRequiredBadge setting={setting} />
      </div>
      <p className="lv-settings-field-desc">{setting.description}</p>

      {setting.secret ? (
        <div className="lv-settings-secret-row">
          <input
            id={inputId}
            className="lv-input"
            type="password"
            autoComplete="new-password"
            placeholder={setting.configured ? "•••••••• (configured)" : "Not configured"}
            disabled={readOnly || busy}
            value={typeof draft === "string" ? draft : ""}
            onChange={(event) => onChange(event.target.value)}
          />
          <button className="lv-btn" type="button" disabled={readOnly || busy} onClick={onSave}>
            Set
          </button>
          {setting.configured && onClearSecret ? (
            <button className="lv-btn lv-btn--ghost" type="button" disabled={busy} onClick={onClearSecret}>
              Clear
            </button>
          ) : null}
        </div>
      ) : setting.type === "boolean" ? (
        <button
          id={inputId}
          className="lv-toggle"
          type="button"
          disabled={readOnly || busy}
          onClick={() => {
            onChange(!(draft ?? setting.effective_value));
          }}
        >
          <span className={`lv-switch${draft ? " is-on" : ""}`} />
          {draft ? "Enabled" : "Disabled"}
        </button>
      ) : setting.type === "enum" ? (
        <select
          id={inputId}
          className="lv-select"
          disabled={readOnly || busy}
          value={formatValue(draft)}
          onChange={(event) => onChange(event.target.value)}
        >
          {setting.enum_values.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={inputId}
          className="lv-input"
          style={{ width: "100%" }}
          type={setting.type === "integer" || setting.type === "float" ? "number" : "text"}
          min={setting.min_value ?? undefined}
          max={setting.max_value ?? undefined}
          step={setting.type === "float" ? "any" : undefined}
          disabled={readOnly || busy}
          value={formatValue(draft)}
          onChange={(event) => {
            if (setting.type === "integer") {
              onChange(Number(event.target.value));
            } else if (setting.type === "float") {
              onChange(Number(event.target.value));
            } else {
              onChange(event.target.value);
            }
          }}
        />
      )}

      {setting.restart_required && !setting.effective_now ? (
        <p className="lv-settings-effective-diff">
          Active: <code>{formatValue(setting.effective_value)}</code>
          {" · "}
          After restart: <code>{formatValue(setting.desired_value)}</code>
        </p>
      ) : null}

      <div className="lv-settings-field-actions">
        <small className="lv-muted">
          source={setting.source}
          {setting.consumer ? ` · ${setting.consumer}` : ""}
        </small>
        <div className="lv-settings-field-buttons">
          {!setting.secret && setting.editable ? (
            <button className="lv-btn" type="button" disabled={readOnly || busy} onClick={onSave}>
              Apply
            </button>
          ) : null}
          {setting.editable && !setting.secret ? (
            <button className="lv-btn lv-btn--ghost" type="button" disabled={busy} onClick={onReset}>
              Reset
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
