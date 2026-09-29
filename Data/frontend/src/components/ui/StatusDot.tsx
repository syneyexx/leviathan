type StatusDotTone = "success" | "info" | "warning" | "danger" | "muted";

export type StatusDotProps = {
  tone: StatusDotTone;
  pulse?: boolean;
  className?: string;
  title?: string;
};

export function StatusDot({ tone, pulse = false, className = "", title }: StatusDotProps) {
  const classes = [
    "lv-v2-status-dot",
    `lv-v2-status-dot--${tone}`,
    pulse ? "lv-v2-status-dot--pulse" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span
      className={classes}
      title={title}
      role={title ? "status" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    />
  );
}
