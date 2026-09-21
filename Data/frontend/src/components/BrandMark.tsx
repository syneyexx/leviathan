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

/** Celestial compass / astrolabe for the sidebar footer. */
export function SidebarOrnament() {
  return (
    <svg className="lv-ornament-svg" viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <defs>
        <radialGradient id="ornGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#F0C875" stopOpacity="0.55" />
          <stop offset="45%" stopColor="#D6A957" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#D6A957" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="ornStroke" x1="20" y1="10" x2="100" y2="110">
          <stop stopColor="#F5DFA9" />
          <stop offset="0.5" stopColor="#D6A957" />
          <stop offset="1" stopColor="#745522" />
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="54" fill="url(#ornGlow)" />
      <circle cx="60" cy="60" r="48" stroke="url(#ornStroke)" strokeWidth="1" opacity="0.9" />
      <circle cx="60" cy="60" r="36" stroke="url(#ornStroke)" strokeWidth="0.85" opacity="0.7" />
      <circle cx="60" cy="60" r="22" stroke="url(#ornStroke)" strokeWidth="0.75" opacity="0.65" />
      <circle cx="60" cy="60" r="8" stroke="#F0C875" strokeWidth="1.1" />
      <circle cx="60" cy="60" r="2.4" fill="#F0C875" />
      {/* Cardinal rays */}
      {Array.from({ length: 12 }).map((_, i) => {
        const a = (i * Math.PI) / 6;
        const outer = i % 3 === 0 ? 46 : 40;
        const inner = i % 3 === 0 ? 26 : 30;
        const x1 = 60 + Math.cos(a) * inner;
        const y1 = 60 + Math.sin(a) * inner;
        const x2 = 60 + Math.cos(a) * outer;
        const y2 = 60 + Math.sin(a) * outer;
        return (
          <line
            key={i}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            stroke="#F0C875"
            strokeWidth={i % 3 === 0 ? 1.15 : 0.7}
            opacity={i % 3 === 0 ? 0.95 : 0.55}
            strokeLinecap="round"
          />
        );
      })}
      {/* Orbital arcs */}
      <path
        d="M24 60a36 36 0 0166-20"
        stroke="#F0C875"
        strokeWidth="0.7"
        opacity="0.45"
        strokeDasharray="2 3"
      />
      <path
        d="M30 78a36 36 0 0158-10"
        stroke="#D6A957"
        strokeWidth="0.7"
        opacity="0.4"
        strokeDasharray="1.5 2.5"
      />
      {/* Star points */}
      <circle cx="60" cy="24" r="1.6" fill="#F5DFA9" />
      <circle cx="96" cy="60" r="1.3" fill="#F0C875" />
      <circle cx="60" cy="96" r="1.3" fill="#F0C875" />
      <circle cx="24" cy="60" r="1.3" fill="#F0C875" />
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
