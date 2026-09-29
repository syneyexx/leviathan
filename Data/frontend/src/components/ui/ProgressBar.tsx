type ProgressTone = "default" | "success" | "warning" | "research" | "trading";

export type ProgressBarProps = {
  value: number | null;
  tone?: ProgressTone;
  className?: string;
  label?: string;
};

function clampPercent(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

export function ProgressBar({ value, tone = "default", className = "", label }: ProgressBarProps) {
  const unknown = value === null;
  const clamped = unknown ? 0 : clampPercent(value);
  const toneMod = tone !== "default" ? `lv-v2-progress--${tone}` : "";
  const classes = ["lv-v2-progress", toneMod, unknown ? "is-unknown" : "", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={classes}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={unknown ? undefined : Math.round(clamped)}
      aria-label={unknown ? "UNMEASURED" : (label ?? `${Math.round(clamped)}%`)}
      style={{ ["--lv2-progress" as string]: clamped }}
    >
      {!unknown ? <div className="lv-v2-progress__fill" /> : null}
    </div>
  );
}
