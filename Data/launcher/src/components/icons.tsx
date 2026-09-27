import type { ReactNode } from "react";

type IconProps = { className?: string };

function Svg({ className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg className={className || "icon"} viewBox="0 0 16 16" aria-hidden="true">
      {children}
    </svg>
  );
}

const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export function IconStart(props: IconProps) {
  return <Svg {...props}><path {...common} d="M5 3.5v9l8-4.5z" /></Svg>;
}
export function IconStop(props: IconProps) {
  return <Svg {...props}><rect {...common} x="4" y="4" width="8" height="8" /></Svg>;
}
export function IconRestart(props: IconProps) {
  return <Svg {...props}><path {...common} d="M13 8a5 5 0 1 1-1.4-3.4" /><path {...common} d="M13 2.8V5.2H10.6" /></Svg>;
}
export function IconSafe(props: IconProps) {
  return <Svg {...props}><path {...common} d="M8 2.2 13 4.2v4.2c0 2.6-2 4.4-5 5.4-3-1-5-2.8-5-5.4V4.2z" /></Svg>;
}
export function IconFrontend(props: IconProps) {
  return <Svg {...props}><rect {...common} x="2.5" y="3" width="11" height="8" /><path {...common} d="M2.5 6h11" /></Svg>;
}
export function IconConfig(props: IconProps) {
  return <Svg {...props}><circle {...common} cx="8" cy="8" r="2" /><path {...common} d="M8 2.2v1.6M8 12.2v1.6M2.2 8h1.6M12.2 8h1.6M4 4l1.1 1.1M10.9 10.9 12 12M12 4l-1.1 1.1M5.1 10.9 4 12" /></Svg>;
}
export function IconLogs(props: IconProps) {
  return <Svg {...props}><path {...common} d="M3 4.5h4l1.2 1.4H13V12H3z" /></Svg>;
}
export function IconEmergency(props: IconProps) {
  return <Svg {...props}><path {...common} d="M8 2.5 14 13H2z" /><path {...common} d="M8 6.5v3.2" /><path {...common} d="M8 11.4h.01" /></Svg>;
}
export function IconApi(props: IconProps) {
  return <Svg {...props}><path {...common} d="M3 8h10M8 3l5 5-5 5" /></Svg>;
}
export function IconWorkers(props: IconProps) {
  return <Svg {...props}><circle {...common} cx="5" cy="6" r="1.6" /><circle {...common} cx="11" cy="6" r="1.6" /><path {...common} d="M2.8 12c.4-1.6 1.5-2.4 2.2-2.4S7.4 10.4 7.8 12M8.2 12c.4-1.6 1.5-2.4 2.2-2.4s1.8.8 2.2 2.4" /></Svg>;
}
export function IconNative(props: IconProps) {
  return <Svg {...props}><rect {...common} x="3" y="3" width="10" height="10" /><path {...common} d="M6 8h4M8 6v4" /></Svg>;
}
export function IconPython(props: IconProps) {
  return <Svg {...props}><path {...common} d="M6 3.5h4.2v3.2H7.2V8h3.6v4.5H5.8V8.8h3V7H6z" /></Svg>;
}
export function IconDatabase(props: IconProps) {
  return <Svg {...props}><ellipse {...common} cx="8" cy="4.2" rx="4.2" ry="1.6" /><path {...common} d="M3.8 4.2v7.6c0 .9 1.9 1.6 4.2 1.6s4.2-.7 4.2-1.6V4.2" /></Svg>;
}
export function IconModel(props: IconProps) {
  return <Svg {...props}><circle {...common} cx="8" cy="8" r="2" /><circle {...common} cx="8" cy="3" r="1" /><circle {...common} cx="12.2" cy="10.5" r="1" /><circle {...common} cx="3.8" cy="10.5" r="1" /></Svg>;
}
export function IconQueue(props: IconProps) {
  return <Svg {...props}><path {...common} d="M3 5h10M3 8h10M3 11h10" /></Svg>;
}
export function IconWatcher(props: IconProps) {
  return <Svg {...props}><path {...common} d="M2 8s2.2-3.5 6-3.5S14 8 14 8s-2.2 3.5-6 3.5S2 8 2 8z" /><circle {...common} cx="8" cy="8" r="1.4" /></Svg>;
}

const serviceIcons: Record<string, (props: IconProps) => ReactNode> = {
  api: IconApi,
  workers: IconWorkers,
  native: IconNative,
  python: IconPython,
  control: IconDatabase,
  knowledge: IconDatabase,
  market: IconDatabase,
  vector: IconDatabase,
  database: IconDatabase,
  watcher: IconWatcher,
  rust: IconNative,
  model: IconModel,
  queue: IconQueue,
};

export function ServiceIcon({ id }: { id: string }) {
  const Icon = serviceIcons[id] || IconWatcher;
  return <Icon />;
}
