import type { ReactNode } from "react";

export type PanelProps = {
  title: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
};

export function Panel({
  title,
  icon,
  action,
  meta,
  children,
  className = "",
  bodyClassName = "",
}: PanelProps) {
  const rootClass = ["lv-v2-panel", className].filter(Boolean).join(" ");
  const bodyClass = ["lv-v2-panel__body", bodyClassName].filter(Boolean).join(" ");

  return (
    <article className={rootClass}>
      <div className="lv-v2-panel__head">
        <h3 className="lv-v2-panel__title">
          {icon ? <span className="lv-v2-panel__title-icon">{icon}</span> : null}
          <span>{title}</span>
          {meta ? <span className="lv-v2-panel__meta">{meta}</span> : null}
        </h3>
        {action ? <div className="lv-v2-panel__action">{action}</div> : null}
      </div>
      <div className={bodyClass}>{children}</div>
    </article>
  );
}
