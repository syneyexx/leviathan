import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { title?: string };

export function Icon({ children, className = "lv-icon", ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" {...props}>
      {children}
    </svg>
  );
}

/** Circular trident mark used in header + sidebar brand lockups. */
export function BrandMark({ id = "g1" }: { id?: string }) {
  return (
    <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <circle cx="24" cy="24" r="21.5" stroke={`url(#${id})`} strokeWidth="1.15" />
      <circle cx="24" cy="24" r="17.5" stroke="rgba(240,200,117,0.22)" strokeWidth="0.8" />
      {/* Trident */}
      <path
        d="M24 10v22M24 14c-4.2 0-7 2.2-7 5.2 0 0 2.2-1.6 7-1.6s7 1.6 7 1.6C31 16.2 28.2 14 24 14z"
        stroke="#F0C875"
        strokeWidth="1.35"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M17 16.5c-2.4 1.2-3.8 3.2-3.8 5.4M31 16.5c2.4 1.2 3.8 3.2 3.8 5.4"
        stroke="#F0C875"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <path d="M18 36h12M21 32.5h6" stroke="#F0C875" strokeWidth="1.2" strokeLinecap="round" />
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
