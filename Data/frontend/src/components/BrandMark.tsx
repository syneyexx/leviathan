import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { title?: string };

export function Icon({ children, className = "lv-icon", ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" {...props}>
      {children}
    </svg>
  );
}

export function BrandMark({ id = "g1" }: { id?: string }) {
  return (
    <svg viewBox="0 0 48 48" fill="none">
      <circle cx="24" cy="24" r="21.5" stroke={`url(#${id})`} strokeWidth="1.2" />
      <path
        d="M24 8v32M14 14l10-4 10 4M12 24h24M14 34l10 4 10-4"
        stroke="#F0C875"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <defs>
        <linearGradient id={id} x1="8" y1="6" x2="40" y2="42">
          <stop stopColor="#F5DFA9" />
          <stop offset="1" stopColor="#745522" />
        </linearGradient>
      </defs>
    </svg>
  );
}

export function BotAvatar() {
  return (
    <div className="lv-msg-avatar bot" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 3v18M7 7l5-3 5 3M5 12h14M7 17l5 3 5-3" />
      </svg>
    </div>
  );
}
