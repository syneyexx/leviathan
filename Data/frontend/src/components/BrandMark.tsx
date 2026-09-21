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
          <stop offset="0%" stopColor="#F5DFA9" stopOpacity="0.7" />
          <stop offset="28%" stopColor="#F0C875" stopOpacity="0.28" />
          <stop offset="70%" stopColor="#D6A957" stopOpacity="0.08" />
          <stop offset="100%" stopColor="#D6A957" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="ornStroke" x1="18" y1="12" x2="102" y2="108">
          <stop stopColor="#F5DFA9" />
          <stop offset="0.45" stopColor="#F0C875" />
          <stop offset="1" stopColor="#8A6528" />
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="56" fill="url(#ornGlow)" />
      <circle cx="60" cy="60" r="50" stroke="url(#ornStroke)" strokeWidth="1.05" opacity="0.95" />
      <circle cx="60" cy="60" r="38" stroke="url(#ornStroke)" strokeWidth="0.8" opacity="0.65" />
      <circle cx="60" cy="60" r="24" stroke="url(#ornStroke)" strokeWidth="0.7" opacity="0.55" />
      {/* Orbital ellipses */}
      <ellipse cx="60" cy="60" rx="44" ry="18" stroke="#F0C875" strokeWidth="0.65" opacity="0.4" transform="rotate(-28 60 60)" />
      <ellipse cx="60" cy="60" rx="42" ry="16" stroke="#D6A957" strokeWidth="0.55" opacity="0.35" transform="rotate(34 60 60)" />
      {/* Star rays */}
      {Array.from({ length: 8 }).map((_, i) => {
        const a = (i * Math.PI) / 4 - Math.PI / 2;
        const long = i % 2 === 0;
        const outer = long ? 47 : 34;
        const inner = long ? 10 : 12;
        return (
          <line
            key={i}
            x1={60 + Math.cos(a) * inner}
            y1={60 + Math.sin(a) * inner}
            x2={60 + Math.cos(a) * outer}
            y2={60 + Math.sin(a) * outer}
            stroke="#F0C875"
            strokeWidth={long ? 1.2 : 0.7}
            opacity={long ? 0.95 : 0.55}
            strokeLinecap="round"
          />
        );
      })}
      {/* Central star */}
      <path
        d="M60 48l2.4 7.4H70l-6.2 4.5 2.4 7.4L60 62.8l-6.2 4.5 2.4-7.4-6.2-4.5h7.6L60 48z"
        fill="#F5DFA9"
        opacity="0.95"
      />
      <circle cx="60" cy="60" r="3.2" fill="#FFF6D8" />
      <circle cx="88" cy="38" r="1.4" fill="#F5DFA9" opacity="0.85" />
      <circle cx="34" cy="78" r="1.1" fill="#F0C875" opacity="0.75" />
      <circle cx="82" cy="82" r="1" fill="#F0C875" opacity="0.7" />
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
