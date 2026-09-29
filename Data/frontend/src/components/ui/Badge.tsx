import type { ReactNode } from "react";

type BadgeTone =
  | "research"
  | "trading"
  | "training"
  | "data"
  | "system"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "muted";

export type BadgeProps = {
  tone: BadgeTone;
  children: ReactNode;
  className?: string;
};

export function Badge({ tone, children, className = "" }: BadgeProps) {
  const classes = ["lv-v2-badge", `lv-v2-badge--${tone}`, className].filter(Boolean).join(" ");

  return <span className={classes}>{children}</span>;
}
