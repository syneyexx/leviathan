import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost";
type ButtonSize = "sm" | "md";

export type ButtonProps = {
  variant: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  disabled?: boolean;
  type?: ButtonHTMLAttributes<HTMLButtonElement>["type"];
  onClick?: ButtonHTMLAttributes<HTMLButtonElement>["onClick"];
  children: ReactNode;
  className?: string;
  title?: string;
  "aria-label"?: string;
};

export function Button({
  variant,
  size = "md",
  loading = false,
  disabled = false,
  type = "button",
  onClick,
  children,
  className = "",
  title,
  "aria-label": ariaLabel,
}: ButtonProps) {
  const classes = [
    "lv-v2-button",
    `lv-v2-button--${variant}`,
    size === "sm" ? "lv-v2-button--sm" : "",
    loading ? "is-loading" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      aria-busy={loading || undefined}
    >
      {children}
    </button>
  );
}
