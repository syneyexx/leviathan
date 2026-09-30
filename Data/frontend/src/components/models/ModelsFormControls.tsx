import type { ReactNode } from "react";

/** Shared field-row + capability-gated controls for Models V2 load configuration cards. */

export function FieldRow({
  label,
  note,
  children,
}: {
  label: string;
  note?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="lv-v2-models-field-row">
      <span className="lv-v2-models-field-row__label" title={note ?? undefined}>
        {label}
      </span>
      <div className="lv-v2-models-field-row__control">{children}</div>
      {note ? <p className="lv-v2-models-cap-note">{note}</p> : null}
    </div>
  );
}

export function RangeControl({
  value,
  disabled,
  onChange,
  min = 0,
  max = 100,
}: {
  value: number;
  disabled?: boolean;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <div className="lv-v2-models-range">
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="lv-v2-range"
      />
      <span className="lv-v2-models-range__value">{Math.round(value)}%</span>
    </div>
  );
}

export function ToggleControl({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
}) {
  return (
    <label className={`lv-v2-toggle${disabled ? " is-disabled" : ""}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}
