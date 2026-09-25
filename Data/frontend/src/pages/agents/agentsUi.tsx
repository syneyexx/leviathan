import type { ReactNode } from "react";

export function AgentIcon({ kind }: { kind: string }) {
  switch (kind) {
    case "research":
      return (<><circle cx="11" cy="11" r="6" /><path d="M16 16l3.5 3.5" /></>);
    case "coding":
      return <path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13 6l-2 12" />;
    case "trading":
      return <path d="M4 16l5-6 3 3 5-7" />;
    case "memory":
      return (<><ellipse cx="12" cy="8" rx="6" ry="3" /><path d="M6 8v6c0 1.7 2.7 3 6 3s6-1.3 6-3V8" /></>);
    case "media":
      return (<><rect x="4" y="6" width="16" height="12" rx="2" /><path d="M10 10l5 3-5 3z" /></>);
    case "critic":
      return (<><path d="M12 4l7 4v6c0 4-3 6-7 8-4-2-7-4-7-8V8l7-4z" /><path d="M9 12l2 2 4-4" /></>);
    case "planner":
      return (<><rect x="5" y="4" width="14" height="16" rx="2" /><path d="M9 8h6M9 12h6M9 16h4" /></>);
    case "core":
      return (<><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" /><circle cx="12" cy="12" r="3" /></>);
    case "tools":
      return <path d="M14 6a4 4 0 00-5 5l-5 5 3 3 5-5a4 4 0 005-5l-2 2-2-2 2-2z" />;
    case "models":
      return (<><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M8 12h8M12 8v8" /></>);
    case "runtime":
      return (<><rect x="4" y="5" width="16" height="6" rx="1.5" /><rect x="4" y="13" width="16" height="6" rx="1.5" /></>);
    case "workers":
      return (<><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>);
    case "flow":
      return <path d="M4 12h12M12 6l6 6-6 6" />;
    case "check":
      return <path d="M5 12l4 4 10-10" />;
    case "clock":
      return (<><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></>);
    case "sync":
      return <path d="M5 12a7 7 0 0112-5l2 2M19 12a7 7 0 01-12 5l-2-2M17 5v4h-4M7 19v-4h4" />;
    case "users":
      return (<><circle cx="9" cy="9" r="3" /><circle cx="16" cy="10" r="2.5" /><path d="M3 19c0-3 3-5 6-5s6 2 6 5M14 19c0-2 1.5-3.5 4-3.5" /></>);
    case "tasks":
      return (<><rect x="5" y="4" width="14" height="16" rx="2" /><path d="M9 9l1.5 1.5L13 8M9 15h6" /></>);
    case "gauge":
      return (<><path d="M4 16a8 8 0 1116 0" /><path d="M12 16l4-5" /></>);
    default:
      return (<><circle cx="12" cy="12" r="7" /><path d="M12 8v4l3 2" /></>);
  }
}

export function Glyph({ kind, className }: { kind: string; className?: string }) {
  return (
    <span className={`lv-ag-glyph${className ? ` ${className}` : ""}`} aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <AgentIcon kind={kind} />
      </svg>
    </span>
  );
}

export function PanelHead({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <header className="lv-ag-phead">
      <div className="lv-ag-phead-title">
        <h2>{title}</h2>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {right ? <div className="lv-ag-phead-right">{right}</div> : null}
    </header>
  );
}

export function LiveBadge({ live, label }: { live: boolean; label?: string }) {
  return (
    <span className={`lv-ag-livebadge${live ? " is-live" : " is-stale"}`}>
      <i />
      {label ?? (live ? "Live" : "Stale")}
    </span>
  );
}

export function StatusChip({ label, tone }: { label: string; tone: string }) {
  return <span className={`lv-ag-chip is-${tone}`}>{label}</span>;
}

export function Bar({ ratio, tone = "cyan" }: { ratio: number | null; tone?: string }) {
  const pct = ratio == null || !Number.isFinite(ratio) ? 0 : Math.max(0, Math.min(1, ratio)) * 100;
  return (
    <span className={`lv-ag-bar is-${tone}${ratio == null ? " is-null" : ""}`}>
      <span style={{ width: `${pct}%` }} />
    </span>
  );
}

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
  className,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  className?: string;
}) {
  return (
    <div className="lv-ag-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className={`lv-ag-modal${wide ? " is-wide" : ""}${className ? ` ${className}` : ""}`}
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="lv-ag-modal-head">
          <h2>{title}</h2>
          <button type="button" className="lv-ag-btn-ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="lv-ag-modal-body">{children}</div>
        {footer ? <footer className="lv-ag-modal-foot">{footer}</footer> : null}
      </div>
    </div>
  );
}
