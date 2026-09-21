import type { ReactNode } from "react";
import { ChevronRight, MoreHorizontal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { SystemHealth } from "@/lib/hades-api";
export type StatusTone = "success" | "warning" | "danger" | "info" | "neutral";

export function checkStatusTone(status: "ok" | "warn" | "error"): StatusTone {
  if (status === "ok") return "success";
  if (status === "warn") return "warning";
  return "danger";
}

export function overallHealthTone(health: SystemHealth | null): StatusTone {
  if (!health) return "danger";
  if (health.backend !== "ok" && health.overall !== "ok") return "danger";
  if (health.overall === "error") return "danger";
  if (health.lm_studio !== "connected") return "warning";
  if (!health.active_model) return "warning";
  if (health.overall === "warn") return "warning";
  if (health.overall === "ok") return "success";
  if (health.backend !== "ok") return "danger";
  return "success";
}

export function overallHealthLabel(health: SystemHealth | null): string {
  if (!health) return "Backend offline";
  if (health.backend !== "ok" && health.overall !== "ok") return "Backend offline";
  if (health.overall === "error" && health.lm_studio === "connected" && health.active_model) return "Probleem";
  if (health.lm_studio !== "connected") return "LM Studio offline";
  if (!health.active_model) return "Geen model geladen";
  if (health.overall === "warn") return "Let op";
  if (health.overall === "error") return "Probleem";
  if (health.overall === "ok") return "Verbonden · model geladen";
  if (health.backend !== "ok") return "Backend offline";
  return "Verbonden · model geladen";
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function Panel({ title, eyebrow, actions, children, className = "" }: { title?: string; eyebrow?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={`panel ${className}`}>
      {title || actions ? (
        <div className="panel-heading">
          <div>
            {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
            {title ? <h2>{title}</h2> : null}
          </div>
          {actions ? <div className="panel-actions">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </Card>
  );
}

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: StatusTone }) {
  return <Badge className={`status-badge status-${tone}`}>{children}</Badge>;
}

export function StatCard({ label, value, note, icon }: { label: string; value: string; note: string; icon?: ReactNode }) {
  return (
    <Card className="stat-card">
      <div className="stat-label">{icon}{label}</div>
      <strong>{value}</strong>
      <span>{note}</span>
    </Card>
  );
}

export function ProgressRow({ label, value, detail }: { label: string; value: number; detail?: string }) {
  return (
    <div className="progress-row">
      <div className="progress-copy"><span>{label}</span><strong>{detail ?? `${value}%`}</strong></div>
      <Progress value={value} />
    </div>
  );
}

export function TableAction() {
  return <Button aria-label="Meer opties" variant="ghost" size="icon"><MoreHorizontal /></Button>;
}

export function DetailLink({ children }: { children: ReactNode }) {
  return <button className="detail-link" type="button">{children}<ChevronRight /></button>;
}

export function EmptyLine({ children }: { children: ReactNode }) {
  return <div className="empty-line">{children}</div>;
}
