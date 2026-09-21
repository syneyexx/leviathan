import type { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement> & {
  name: string;
  size?: number;
};

/**
 * Header-only icon set traced to the canonical 1672x941 FINALBETA dashboard.
 * These are intentionally separate from the generic page icon set: the top
 * navigation uses six distinct reference glyphs.
 */
export function FinalBetaTopnavIcon({ name, size = 24, ...props }: Props) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    ...props,
  };

  if (name === "brain") {
    return (
      <svg {...common}>
        <path d="M12 3.2 5.5 18.8h13L12 3.2Z" />
        <path d="m8.7 16.8 3.3-8 3.3 8M10 13.7h4M12 8.8v9" />
      </svg>
    );
  }

  if (name === "database") {
    return (
      <svg {...common}>
        <rect x="6" y="6" width="12" height="12" rx="1.8" />
        <rect x="9" y="9" width="6" height="6" rx="1" />
        <path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5" />
        <path d="M5 4h2M4 5v2M17 4h2M20 5v2M5 20h2M4 17v2M17 20h2M20 17v2" />
      </svg>
    );
  }

  if (name === "play") {
    return (
      <svg {...common}>
        <path d="M6.5 20V8.2L12 10.5l5.5-2.3V20" />
        <path d="M5 20h14M7 7l5-3 5 3M7 4.7 12 7l5-2.3" />
        <path d="M10 16h4" />
      </svg>
    );
  }

  if (name === "chart") {
    return (
      <svg {...common}>
        <path d="M4 20v-5h4v5M10 20v-8h4v8M16 20V9h4v11" />
        <path d="m4 11 5-4.3 4 2 7-6.2" />
        <path d="M16.5 2.5H20v3.5" />
      </svg>
    );
  }

  if (name === "search") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="2.5" />
        <path d="m10.4 10-4-5M13.6 10l4-5M9.5 12H3M14.5 12H21M10.4 14l-4 5M13.6 14l4 5" />
      </svg>
    );
  }

  if (name === "wrench") {
    return (
      <svg {...common}>
        <path d="m5 4 15 15M19 4 4 19" />
        <circle cx="5" cy="4" r="1.7" />
        <circle cx="19" cy="4" r="1.7" />
        <circle cx="4" cy="19" r="1.7" />
        <path d="m17.5 17.5 2.5 2.5" />
      </svg>
    );
  }

  if (name === "settings") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    );
  }

  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="8" />
    </svg>
  );
}
