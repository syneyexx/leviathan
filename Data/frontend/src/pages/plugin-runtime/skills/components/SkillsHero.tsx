import type { ReactNode } from "react";
import codingHero from "../../../../assets/coding-hero.jpg";
import type { KpiModel } from "../viewModels";

const KPI_ICONS: Record<string, ReactNode> = {
  total: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <rect x="2.5" y="3" width="4" height="4" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <rect x="9.5" y="3" width="4" height="4" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <rect x="2.5" y="9.5" width="4" height="4" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <rect x="9.5" y="9.5" width="4" height="4" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  available: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <rect x="2.5" y="2.5" width="11" height="11" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M6.2 8 10.2 5.8v4.4z" fill="currentColor" />
    </svg>
  ),
  external_packs: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M3 5.5 8 3l5 2.5v5L8 13 3 10.5z" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M3 5.5 8 8l5-2.5M8 8v5" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  ),
  agent_skills: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M5.5 6.2a2 2 0 1 1 0-0.1M10.5 6.2a2 2 0 1 1 0-0.1" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M4.2 11.5c.5-1.8 1.8-2.7 3.8-2.7s3.3.9 3.8 2.7" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  ),
  issues: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M8 2.5 14 13.5H2z" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M8 6.5v3.2M8 11.2h.01" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  ),
  updates: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M3.5 8a4.5 4.5 0 0 1 7.7-3.1M12.5 8a4.5 4.5 0 0 1-7.7 3.1" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M11 2.8v2.6H8.4M5 13.2v-2.6h2.6" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
};

export function SkillsHero() {
  return (
    <section className="lv-sk-hero" aria-label="Skills">
      <div className="lv-sk-hero-media">
        <img src={codingHero} alt="" width={1280} height={720} />
      </div>
      <div className="lv-sk-hero-shade" />
      <div className="lv-sk-hero-content">
        <h1 className="lv-sk-hero-title">Skills</h1>
        <p className="lv-sk-hero-kicker">CAPABILITIES FOR INTELLIGENCE</p>
        <p className="lv-sk-hero-desc">
          Discover, manage and orchestrate skills from LEVIATHAN, external packs and agents.
        </p>
      </div>
    </section>
  );
}

export function SkillsKpiStrip({ items }: { items: KpiModel[] }) {
  return (
    <section className="lv-sk-kpi-row" aria-label="Skill KPIs">
      {items.map((kpi) => (
        <article key={kpi.id} className={`lv-sk-kpi is-${kpi.tone}${kpi.measured ? "" : " is-unmeasured"}`}>
          <div className="lv-sk-kpi-icon">{KPI_ICONS[kpi.id] ?? KPI_ICONS.total}</div>
          <div className="lv-sk-kpi-body">
            <div className="lv-sk-kpi-value">{kpi.value}</div>
            <div className="lv-sk-kpi-label">{kpi.label}</div>
          </div>
        </article>
      ))}
    </section>
  );
}
