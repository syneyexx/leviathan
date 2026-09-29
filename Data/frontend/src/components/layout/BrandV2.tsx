/**
 * Leviathan V2 brand lockup — cyan serpent mark + wordmark.
 * Prefer inline SVG so the mark scales crisply at sidebar sizes.
 */
export type BrandV2Props = {
  className?: string;
};

function LeviathanMarkV2() {
  return (
    <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path
        d="M8.5 28.5c2.2-7.4 7.8-13.6 15.2-16.2 3.4-1.2 7.1-1.3 10.4-.2 1.6.5 2.2 2.4 1.2 3.7l-2.1 2.7c4.1.2 7.8 2.1 10.3 5.2.9 1.1.3 2.8-1.1 3.2-3.2.9-6.1.4-8.6-1.1 1.8 3.9 1.4 8.4-1.2 11.9-1.1 1.5-3.3 1.5-4.4 0l-1.6-2.2c-1.6 2.8-4.2 4.9-7.4 5.8-1.5.4-2.9-.9-2.6-2.4.7-3.4 2.6-6.3 5.3-8.3-4.2.6-8.2-.4-11.4-2.9-.9-.7-.9-2.1.1-2.8 1.1-.8 2.2-1.4 3.3-1.9"
        stroke="currentColor"
        strokeWidth="2.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M30.2 15.6c1.4-2.1 3.6-3.6 6.2-4.1.8-.1 1.4.7 1 1.4-.8 1.5-2.1 2.7-3.7 3.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.85"
      />
      <circle cx="34.2" cy="18.4" r="1.35" fill="currentColor" />
      <path
        d="M12.8 33.8c2.6 1.4 5.6 1.8 8.4 1.1"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        opacity="0.55"
      />
    </svg>
  );
}

export function BrandV2({ className = "" }: BrandV2Props) {
  const classes = ["lv-v2-brand", className].filter(Boolean).join(" ");

  return (
    <div className={classes}>
      <div className="lv-v2-brand__mark">
        <LeviathanMarkV2 />
      </div>
      <div className="lv-v2-brand__copy">
        <div className="lv-v2-brand__title">LEVIATHAN</div>
        <div className="lv-v2-brand__tag">AI CONTROL CENTER</div>
      </div>
    </div>
  );
}
