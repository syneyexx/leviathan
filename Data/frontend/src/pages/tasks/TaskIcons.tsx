import type { SVGProps } from "react";

export type IconProps = SVGProps<SVGSVGElement>;

function Svg(props: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    />
  );
}

export function IconLayers(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3 3 8l9 5 9-5-9-5Z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 16 9 5 9-5" />
    </Svg>
  );
}

export function IconProgress(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8" strokeDasharray="6 4" />
      <path d="M12 8v4l2.5 1.5" />
    </Svg>
  );
}

export function IconWarning(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 4 3.5 19h17L12 4Z" />
      <path d="M12 10v4" />
      <path d="M12 17h.01" />
    </Svg>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="m8.5 12 2.5 2.5 4.5-5" />
    </Svg>
  );
}

export function IconClock(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l2.5 2" />
    </Svg>
  );
}

export function IconRobot(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="5" y="8" width="14" height="11" rx="3" />
      <path d="M12 5v3" />
      <circle cx="9.5" cy="13" r="1" fill="currentColor" stroke="none" />
      <circle cx="14.5" cy="13" r="1" fill="currentColor" stroke="none" />
      <path d="M9 16.5h6" />
    </Svg>
  );
}

export function IconSearch(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </Svg>
  );
}

export function IconBolt(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M13 3 6 13h5l-1 8 8-11h-5l0-7Z" />
    </Svg>
  );
}

export function IconSparkle(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
      <path d="m6.5 6.5 2.5 2.5M15 15l2.5 2.5M17.5 6.5 15 9M9 15l-2.5 2.5" />
      <circle cx="12" cy="12" r="2.2" />
    </Svg>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 6v12M6 12h12" />
    </Svg>
  );
}

export function IconMore(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="6" cy="12" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="18" cy="12" r="1.3" fill="currentColor" stroke="none" />
    </Svg>
  );
}

export function IconClipboard(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="7" y="5" width="10" height="15" rx="2" />
      <path d="M9 5V4h6v1" />
      <path d="M10 10h4M10 14h4" />
    </Svg>
  );
}

export function IconShield(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3 5 6v5c0 4.2 2.8 7.4 7 9 4.2-1.6 7-4.8 7-9V6l-7-3Z" />
      <path d="m9.5 12 1.8 1.8 3.4-3.6" />
    </Svg>
  );
}

export function IconLink(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9.5 14.5 14.5 9.5" />
      <path d="M11 17.5 9 19.5a3.2 3.2 0 0 1-4.5-4.5L6.5 13" />
      <path d="M13 6.5 15 4.5a3.2 3.2 0 0 1 4.5 4.5L17.5 11" />
    </Svg>
  );
}

export function IconClose(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M7 7l10 10M17 7 7 17" />
    </Svg>
  );
}

export function IconCalendar(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="4" y="5" width="16" height="15" rx="2" />
      <path d="M4 10h16M9 3v4M15 3v4" />
    </Svg>
  );
}

export function IconPlay(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9 7.5v9l8-4.5-8-4.5Z" />
    </Svg>
  );
}

export function IconStop(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
    </Svg>
  );
}

export function KpiIcon({ type }: { type: "layers" | "progress" | "warning" | "check" | "clock" | "robot" }) {
  switch (type) {
    case "layers":
      return <IconLayers />;
    case "progress":
      return <IconProgress />;
    case "warning":
      return <IconWarning />;
    case "check":
      return <IconCheck />;
    case "clock":
      return <IconClock />;
    case "robot":
      return <IconRobot />;
    default:
      return <IconLayers />;
  }
}

export function ColumnIcon({ type }: { type: "clipboard" | "layers" | "shield" | "check" }) {
  switch (type) {
    case "clipboard":
      return <IconClipboard />;
    case "layers":
      return <IconLayers />;
    case "shield":
      return <IconShield />;
    case "check":
      return <IconCheck />;
    default:
      return <IconClipboard />;
  }
}

export function ProgressRing({ value }: { value: number }) {
  const r = 7.2;
  const c = 2 * Math.PI * r;
  const offset = c - (Math.max(0, Math.min(100, value)) / 100) * c;
  return (
    <svg className="lv-tasks-ring" viewBox="0 0 20 20" aria-hidden="true">
      <circle className="lv-tasks-ring-track" cx="10" cy="10" r={r} />
      <circle
        className={`lv-tasks-ring-value${value >= 100 ? " is-done" : ""}`}
        cx="10"
        cy="10"
        r={r}
        strokeDasharray={c}
        strokeDashoffset={offset}
      />
    </svg>
  );
}
