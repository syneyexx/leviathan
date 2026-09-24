import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { title?: string };

export function Icon({ children, className = "lv-icon", ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" {...props}>
      {children}
    </svg>
  );
}

/**
 * REFERENCE 1 sidebar mark — open three-prong metallic crest (no circular frame).
 * Three sharp blades converging upward; used for sidebar brand + footer signature.
 */
export function TridentMark({ id = "tri" }: { id?: string }) {
  return (
    <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-fill`} x1="10" y1="2" x2="38" y2="46">
          <stop stopColor="#FFF4C8" />
          <stop offset="0.4" stopColor="#F0C875" />
          <stop offset="0.75" stopColor="#C9963E" />
          <stop offset="1" stopColor="#7A5520" />
        </linearGradient>
      </defs>
      {/* Left tine */}
      <path
        d="M24 6.5C17.2 8.2 12.4 13.8 10.2 21.5L14.6 23.1C16.2 17.6 19.6 13.6 24 12.2V6.5Z"
        fill={`url(#${id}-fill)`}
      />
      <path
        d="M12.8 22.2L5.5 36.8c3.8-1.2 7.6-3.4 10.6-6.6L12.8 22.2Z"
        fill={`url(#${id}-fill)`}
      />
      {/* Right tine */}
      <path
        d="M24 6.5C30.8 8.2 35.6 13.8 37.8 21.5L33.4 23.1C31.8 17.6 28.4 13.6 24 12.2V6.5Z"
        fill={`url(#${id}-fill)`}
      />
      <path
        d="M35.2 22.2L42.5 36.8c-3.8-1.2-7.6-3.4-10.6-6.6L35.2 22.2Z"
        fill={`url(#${id}-fill)`}
      />
      {/* Center spike */}
      <path
        d="M22.35 4.2h3.3L27.4 28.5 24 45.2 20.6 28.5 22.35 4.2Z"
        fill={`url(#${id}-fill)`}
      />
      {/* Cross-bar */}
      <path
        d="M16.5 19.8h15"
        stroke="#F5DFA9"
        strokeWidth="1.6"
        strokeLinecap="round"
        opacity="0.85"
      />
      {/* Base ticks */}
      <path
        d="M20.8 41.5h6.4M19.2 44.6h9.6"
        stroke="#E8C56A"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Circular trident mark used in page headers and other lockups. */
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
