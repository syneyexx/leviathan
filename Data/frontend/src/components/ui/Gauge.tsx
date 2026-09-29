import type { CSSProperties } from "react";

export type GaugeProps = {
  label: string;
  value: number | null;
  sublabel?: string;
  color?: string;
  className?: string;
};

const GAUGE_R = 30;
const GAUGE_CX = 36;
const GAUGE_CY = 36;

function clampPercent(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

export function Gauge({ label, value, sublabel, color, className = "" }: GaugeProps) {
  const unknown = value === null;
  const clamped = unknown ? 0 : clampPercent(value);
  const display = unknown ? "N/A" : `${Math.round(clamped)}%`;
  const classes = ["lv-v2-gauge", unknown ? "is-unknown" : "", className].filter(Boolean).join(" ");

  const style = {
    ["--lv2-gauge" as string]: clamped,
    ...(color ? { ["--lv2-gauge-color" as string]: color } : {}),
  } as CSSProperties;

  return (
    <div className={classes} style={style} role="img" aria-label={unknown ? `${label}: unknown` : `${label}: ${display}`}>
      <div className="lv-v2-gauge__ring">
        <svg viewBox="0 0 72 72" aria-hidden="true">
          <circle className="lv-v2-gauge__track" cx={GAUGE_CX} cy={GAUGE_CY} r={GAUGE_R} />
          <circle className="lv-v2-gauge__value" cx={GAUGE_CX} cy={GAUGE_CY} r={GAUGE_R} />
        </svg>
        <div className="lv-v2-gauge__center">{display}</div>
      </div>
      <div className="lv-v2-gauge__label">{label}</div>
      {sublabel ? <div className="lv-v2-gauge__sub">{sublabel}</div> : null}
    </div>
  );
}
