"use client";

import { cn } from "@/lib/utils";

export type MicLevelMeterProps = {
  level: number;
  active?: boolean;
  label?: string;
  className?: string;
};

/**
 * Accessible mic level meter. No fake animation when inactive — bar stays at 0.
 */
export function MicLevelMeter({
  level,
  active = false,
  label = "Microfoonniveau",
  className,
}: MicLevelMeterProps) {
  const clamped = active ? Math.max(0, Math.min(1, level)) : 0;
  const percent = Math.round(clamped * 100);

  return (
    <div
      className={cn("mic-level-meter", className)}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={active ? `${percent} procent` : "Inactief"}
      data-active={active ? "true" : "false"}
      style={{
        display: "grid",
        gap: "0.28rem",
        minWidth: "4.5rem",
      }}
    >
      <div
        style={{
          height: "0.42rem",
          borderRadius: "999px",
          background: "#e8e3da",
          overflow: "hidden",
          border: "1px solid #ddd7cd",
        }}
      >
        <div
          style={{
            width: `${percent}%`,
            height: "100%",
            background: active
              ? percent > 70
                ? "#b85c4a"
                : percent > 35
                  ? "#8a7355"
                  : "#6d8f6a"
              : "transparent",
            transition: active ? "width 80ms linear" : "none",
          }}
        />
      </div>
      <span className="visually-hidden">
        {active ? `${label}: ${percent}%` : `${label}: inactief`}
      </span>
    </div>
  );
}
