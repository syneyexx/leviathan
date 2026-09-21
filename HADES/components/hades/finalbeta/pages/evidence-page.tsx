/** FINALBETA Evidence Vault — live claim register + knowledge evidence inventory. */
"use client";

import { useEffect, useMemo, useState } from "react";
import {
  useHadesEvidence,
  type EvidenceClaimView,
} from "@/components/hades/features/evidence/hooks/useHadesEvidence";
import { formatDate, hadesApi } from "@/lib/hades-api";
import { donutSegments } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";
import "../../styles/finalbeta/v2/evidence.css";

type Props = { onNavigate: FinalBetaNavigate };
type ViewId = "list" | "timeline" | "graph";

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = [
  "januari",
  "februari",
  "maart",
  "april",
  "mei",
  "juni",
  "juli",
  "augustus",
  "september",
  "oktober",
  "november",
  "december",
];

const VIEWS: Array<{ id: ViewId; label: string; icon: string }> = [
  { id: "list", label: "Lijst", icon: "list" },
  { id: "timeline", label: "Tijdlijn", icon: "clock" },
  { id: "graph", label: "Graph", icon: "target" },
];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function reliabilityTone(value: number | null): "hi" | "mid" | "lo" {
  if (value == null) return "lo";
  if (value >= 90) return "hi";
  if (value >= 75) return "mid";
  return "lo";
}

function ClaimRow({
  claim,
  active,
  onSelect,
}: {
  claim: EvidenceClaimView;
  active: boolean;
  onSelect: () => void;
}) {
  const tone = reliabilityTone(claim.reliability);
  return (
    <button type="button" className={`evidence-claim-row${active ? " active" : ""}`} onClick={onSelect}>
      <span className={`evidence-claim-status ${claim.status}`} aria-label={claim.statusLabel}>
        <FbIcon name={claim.status === "verified" ? "check" : claim.status === "review" ? "flask" : "stop"} size={12} />
      </span>
      <span className="evidence-claim-title">{claim.title}</span>
      <span className="evidence-claim-topic">{claim.topic}</span>
      <span className="evidence-reliability">
        {claim.reliability != null ? (
          <>
            <span className={`evidence-reliability-bar ${tone}`}>
              <i style={{ width: `${claim.reliability}%` }} />
            </span>
            <b>{claim.reliability}%</b>
          </>
        ) : (
          <b>—</b>
        )}
      </span>
      <span className="evidence-claim-updated">{formatDate(claim.updated)}</span>
      <span className="evidence-claim-menu" aria-hidden="true">
        <FbIcon name="more" size={14} />
      </span>
    </button>
  );
}

export function EvidencePage({ onNavigate }: Props) {
  const [now, setNow] = useState(() => new Date());
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [view, setView] = useState<ViewId>("list");
  const [topic, setTopic] = useState<string | null>(null);
  const [draftClaim, setDraftClaim] = useState("");
  const [busy, setBusy] = useState(false);
  const { cards, stats, loading, error, refresh, reassess } = useHadesEvidence();

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const topics = useMemo(() => {
    const set = new Set<string>();
    for (const card of cards) {
      if (card.topic) set.add(card.topic);
      for (const tag of card.tags) if (tag) set.add(String(tag));
    }
    return Array.from(set).slice(0, 12);
  }, [cards]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return cards.filter((item) => {
      if (topic && item.topic !== topic && !item.tags.includes(topic)) return false;
      if (!q) return true;
      return (
        item.title.toLowerCase().includes(q) ||
        item.topic.toLowerCase().includes(q) ||
        item.tags.some((tag) => tag.toLowerCase().includes(q)) ||
        item.summary.toLowerCase().includes(q)
      );
    });
  }, [cards, query, topic]);

  useEffect(() => {
    if (!filtered.length) {
      setSelectedId("");
      return;
    }
    setSelectedId((current) =>
      current && filtered.some((c) => c.id === current) ? current : filtered[0]!.id,
    );
  }, [filtered]);

  const selected = filtered.find((item) => item.id === selectedId) ?? null;

  const validationSlices = useMemo(() => {
    const total = Math.max(1, stats.claims);
    const rows = [
      { label: "Geverifieerd", count: stats.verified, color: "#20e38d" },
      { label: "In review", count: stats.review, color: "#f0b429" },
      { label: "Conflict", count: stats.conflicts, color: "#e85b5b" },
    ];
    return rows.map((row) => ({
      ...row,
      pct: `${Math.round((row.count / total) * 100)}%`,
    }));
  }, [stats]);

  const donut = donutSegments(
    validationSlices.map((s) => ({ label: s.label, count: s.count, color: s.color })),
  );

  const sourceBars = useMemo(() => {
    const inventory = stats.evidenceInventory || [];
    const byType = new Map<string, number>();
    for (const item of inventory) {
      const kind = String((item as { source_type?: string }).source_type || "source");
      byType.set(kind, (byType.get(kind) || 0) + 1);
    }
    const entries = Array.from(byType.entries()).sort((a, b) => b[1] - a[1]).slice(0, 6);
    const max = Math.max(1, ...entries.map(([, n]) => n));
    return entries.map(([label, count]) => ({
      label,
      count,
      pct: Math.round((count / max) * 100),
      width: Math.round((count / max) * 100),
      icon: "file",
    }));
  }, [stats.evidenceInventory]);

  const chainSteps = useMemo(() => {
    if (!selected) return [];
    return (selected.evidenceLinks || []).map((link, index) => ({
      id: String((link as { evidence_id?: string }).evidence_id || `ev-${index}`),
      step: index + 1,
      title: String((link as { note?: string; evidence_id?: string }).note || (link as { evidence_id?: string }).evidence_id || `Evidence ${index + 1}`),
      kind: String((link as { relation?: string }).relation || "supports"),
      source: selected.provenance,
      reliability: selected.reliability,
      badge: index === 0 ? ("Primair" as const) : ("Secundair" as const),
      badgeTone: index === 0 ? ("green" as const) : ("blue" as const),
    }));
  }, [selected]);

  async function createClaim() {
    const text = draftClaim.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      await hadesApi.addClaim({ text, provenance: "user", verification_status: "unverified" });
      setDraftClaim("");
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const liveStats = [
    {
      id: "claims",
      label: "Claims",
      value: loading ? "…" : String(stats.claims),
      hint: `${stats.verified} geverifieerd`,
      icon: "checkcircle",
      tone: "cyan",
    },
    {
      id: "sources",
      label: "Bronnen in vault",
      value: loading ? "…" : String(stats.sources),
      hint: "Knowledge evidence inventory",
      icon: "link",
      tone: "cyan",
    },
    {
      id: "reliability",
      label: "Gem. betrouwbaarheid",
      value: loading ? "…" : stats.avgReliability != null ? `${stats.avgReliability}%` : "—",
      hint: stats.avgReliability == null ? "Alleen bij observable signals" : "Uit evidence signals",
      icon: "shield",
      tone: "green",
    },
    {
      id: "chains",
      label: "Evidence links",
      value: loading ? "…" : String(cards.reduce((n, c) => n + c.relatedCount, 0)),
      hint: "Supports / contradicts / links",
      icon: "target",
      tone: "cyan",
    },
    {
      id: "conflicts",
      label: "Conflicten",
      value: loading ? "…" : String(stats.conflicts),
      hint: "CONTRADICTED claims",
      icon: "flask",
      tone: "gold",
    },
  ];

  const body = (
    <div className="evidence-page" data-live="evidence">
      <div className="evidence-welcome">
        <div className="evidence-welcome-copy">
          <h1>Evidence Vault</h1>
          <p>Geverifieerde beweringen, bronnen en bewijsketens. Van claim naar waarheid.</p>
        </div>
        <div className="evidence-welcome-mid">“Evidence turns information into intelligence.”</div>
        <div className="evidence-clock">
          <div className="evidence-clock-copy">
            <div className="date">
              {DAYS[now.getDay()]} {now.getDate()} {MONTHS[now.getMonth()]} {now.getFullYear()}
            </div>
            <div className="time">
              {pad(now.getHours())}:{pad(now.getMinutes())}
            </div>
          </div>
          <FbIcon name="bolt" size={22} className="evidence-sun" />
        </div>
      </div>

      {error ? (
        <div className="card" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Evidence laden mislukt.</strong> {error.message}{" "}
          <button type="button" className="btn btn-sm btn-outline" onClick={() => void refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="evidence-stats">
        {liveStats.map((stat) => (
          <article key={stat.id} className="evidence-stat card">
            <span className={`evidence-stat-ico ${stat.tone}`}>
              <FbIcon name={stat.icon} size={15} />
            </span>
            <div>
              <div className="evidence-stat-label">{stat.label}</div>
              <div className="evidence-stat-value-row">
                <div className="evidence-stat-value">{stat.value}</div>
              </div>
              <div className="evidence-stat-hint">{stat.hint}</div>
            </div>
          </article>
        ))}
      </div>

      <div className="evidence-toolbar">
        <div className="evidence-toolbar-row">
          <label className="evidence-search">
            <FbIcon name="search" size={14} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Zoek in claims, bronnen, onderwerpen..."
              aria-label="Zoek in claims, bronnen, onderwerpen"
            />
          </label>
          <button type="button" className="btn btn-gold evidence-search-btn" onClick={() => undefined}>
            <FbIcon name="search" size={12} />
            Zoeken
          </button>
          <button type="button" className="evidence-filter" onClick={() => void refresh()}>
            Vernieuwen
            <FbIcon name="refresh" size={12} />
          </button>
        </div>

        <div className="evidence-topics-row">
          <span className="evidence-topics-label">Onderwerpen:</span>
          <div className="evidence-topics">
            <button
              type="button"
              className={`evidence-topic${topic == null ? " active" : ""}`}
              onClick={() => setTopic(null)}
            >
              Alle
            </button>
            {topics.map((item) => (
              <button
                key={item}
                type="button"
                className={`evidence-topic${topic === item ? " active" : ""}`}
                onClick={() => setTopic(item)}
              >
                {item}
              </button>
            ))}
          </div>
          <div className="evidence-views" role="group" aria-label="Weergave">
            {VIEWS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`evidence-view${view === item.id ? " active" : ""}`}
                onClick={() => setView(item.id)}
              >
                <FbIcon name={item.icon} size={12} />
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="evidence-mid">
        <section className="card evidence-claims">
          <div className="evidence-panel-head">
            <div>
              <h2>Claims ({filtered.length})</h2>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input
                type="text"
                value={draftClaim}
                onChange={(e) => setDraftClaim(e.target.value)}
                placeholder="Nieuwe claim…"
                style={{ minWidth: 180 }}
                aria-label="Nieuwe claim tekst"
              />
              <button
                type="button"
                className="btn btn-sm btn-gold"
                disabled={busy || !draftClaim.trim()}
                onClick={() => void createClaim()}
              >
                <FbIcon name="plus" size={12} />
                Nieuwe claim
              </button>
            </div>
          </div>
          <div className="evidence-table-head" aria-hidden="true">
            <span>Status</span>
            <span>Claim</span>
            <span>Onderwerp</span>
            <span>Betrouwbaarheid</span>
            <span>Update</span>
            <span />
          </div>
          <div className="evidence-table">
            {loading && !cards.length ? (
              <p className="muted" style={{ padding: 12 }}>
                Claims laden…
              </p>
            ) : !filtered.length ? (
              <p className="muted" style={{ padding: 12 }}>
                Geen claims. Voeg een claim toe of laat research tegenstrijdigheden registreren.
              </p>
            ) : view === "list" ? (
              filtered.map((claim) => (
                <ClaimRow
                  key={claim.id}
                  claim={claim}
                  active={claim.id === selected?.id}
                  onSelect={() => setSelectedId(claim.id)}
                />
              ))
            ) : view === "timeline" ? (
              filtered.map((claim) => (
                <button
                  key={claim.id}
                  type="button"
                  className={`evidence-claim-row${claim.id === selected?.id ? " active" : ""}`}
                  onClick={() => setSelectedId(claim.id)}
                >
                  <span className="evidence-claim-updated">{formatDate(claim.updated)}</span>
                  <span className="evidence-claim-title">{claim.title}</span>
                  <span className="evidence-claim-topic">{claim.statusLabel}</span>
                </button>
              ))
            ) : (
              <p className="muted" style={{ padding: 12 }}>
                Graph-weergave: open Brain voor de live graaf.
              </p>
            )}
          </div>
        </section>

        <section className="card evidence-chain">
          <div className="evidence-panel-head">
            <div>
              <h2>Bewijsketen</h2>
              <p>Bronnen, relaties en validatiestappen voor de geselecteerde claim.</p>
            </div>
            <div className="evidence-chain-head-actions">
              <button type="button" className="evidence-open-graph" data-fb-page="brain">
                <FbIcon name="target" size={12} />
                Open in graph
              </button>
            </div>
          </div>
          <div className="evidence-chain-list">
            {!selected ? (
              <p className="muted">Selecteer een claim.</p>
            ) : !chainSteps.length ? (
              <p className="muted">Nog geen evidence links gekoppeld aan deze claim.</p>
            ) : (
              chainSteps.map((step, index) => (
                <div key={step.id} className="evidence-chain-step">
                  <div className="evidence-chain-rail">
                    <span className="evidence-chain-num">{step.step}</span>
                    {index < chainSteps.length - 1 ? <span className="evidence-chain-line" /> : null}
                  </div>
                  <div className="evidence-chain-card">
                    <span className="evidence-chain-ico">
                      <FbIcon name="file" size={14} />
                    </span>
                    <div className="evidence-chain-copy">
                      <strong>{step.title}</strong>
                      <small>
                        {step.kind} · {step.source}
                      </small>
                    </div>
                    <div className="evidence-chain-meta">
                      {step.reliability != null ? (
                        <span className="evidence-chain-pct">
                          <i />
                          {step.reliability}%
                        </span>
                      ) : null}
                      <span className={`evidence-badge ${step.badgeTone}`}>{step.badge}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
            {selected ? (
              <div className="evidence-validated">
                <span className="evidence-validated-ico">
                  <FbIcon name="shield" size={15} />
                </span>
                <div>
                  <strong>{selected.statusLabel}</strong>
                  <small>{selected.title}</small>
                </div>
                <div className="evidence-chain-meta">
                  {selected.reliability != null ? (
                    <span className="evidence-chain-pct">
                      <i />
                      {selected.reliability}%
                    </span>
                  ) : (
                    <span className="evidence-chain-pct">—</span>
                  )}
                  <span className={`evidence-badge ${selected.status === "verified" ? "green" : "blue"}`}>
                    {selected.statusLabel}
                  </span>
                </div>
              </div>
            ) : null}
          </div>
        </section>
      </div>

      <div className="evidence-bottom">
        <section className="card evidence-validation">
          <div className="evidence-panel-head compact">
            <h2>Validatie statistieken</h2>
          </div>
          <div className="evidence-validation-body">
            <div className="evidence-donut-wrap">
              <svg viewBox="0 0 42 42" className="evidence-donut" aria-hidden="true">
                <circle cx="21" cy="21" r="14" fill="none" stroke="rgba(74,163,255,0.12)" strokeWidth="5" />
                {donut.map((seg, index) => (
                  <circle
                    key={validationSlices[index]!.label}
                    cx="21"
                    cy="21"
                    r="14"
                    fill="none"
                    stroke={seg.color}
                    strokeWidth="5"
                    strokeDasharray={seg.dash}
                    strokeDashoffset={seg.offset}
                    transform="rotate(-90 21 21)"
                  />
                ))}
              </svg>
              <div className="evidence-donut-center">
                <strong>{stats.avgReliability != null ? `${stats.avgReliability}%` : "—"}</strong>
                <span>Observable confidence</span>
              </div>
            </div>
            <ul className="evidence-validation-legend">
              {validationSlices.map((slice) => (
                <li key={slice.label}>
                  <i style={{ background: slice.color }} />
                  <span>{slice.label}</span>
                  <b>{slice.pct}</b>
                  <em>{slice.count}</em>
                </li>
              ))}
            </ul>
          </div>
          <div className="evidence-validation-total">
            <span>Totaal</span>
            <b>{stats.claims}</b>
          </div>
        </section>

        <section className="card evidence-sources">
          <div className="evidence-panel-head compact">
            <h2>Bronverdeling</h2>
          </div>
          <ul className="evidence-source-list">
            {!sourceBars.length ? (
              <li>
                <div>
                  <span>Geen knowledge evidence inventory</span>
                </div>
              </li>
            ) : (
              sourceBars.map((row) => (
                <li key={row.label}>
                  <span className="ico">
                    <FbIcon name={row.icon} size={12} />
                  </span>
                  <div>
                    <span>{row.label}</span>
                    <div className="evidence-source-bar">
                      <i style={{ width: `${row.width}%` }} />
                    </div>
                  </div>
                  <b>{row.pct}%</b>
                  <em>{row.count}</em>
                </li>
              ))
            )}
          </ul>
        </section>

        <section className="card evidence-activity">
          <div className="evidence-panel-head compact">
            <h2>Recente claims</h2>
          </div>
          <ul className="evidence-activity-list">
            {!cards.length ? (
              <li>
                <div>
                  <strong>Geen activiteit</strong>
                  <small>Nog geen claims in het register</small>
                </div>
              </li>
            ) : (
              cards.slice(0, 6).map((item) => (
                <li key={item.id}>
                  <span className={`evidence-activity-ico ${item.status === "verified" ? "green" : "cyan"}`}>
                    <FbIcon name="bolt" size={11} />
                  </span>
                  <div>
                    <strong>{item.statusLabel}</strong>
                    <small>{item.title}</small>
                  </div>
                  <span className="evidence-activity-ago">{formatDate(item.updated)}</span>
                </li>
              ))
            )}
          </ul>
        </section>

        <section className="card evidence-audit">
          <div className="evidence-panel-head compact">
            <h2>Audit &amp; validatie</h2>
          </div>
          <div className="evidence-audit-grid">
            <button
              type="button"
              className="evidence-audit-btn"
              disabled={!selected || busy}
              onClick={() => selected && void reassess(selected.id)}
            >
              <FbIcon name="search" size={14} />
              <span>Claim herbeoordelen</span>
            </button>
            <button type="button" className="evidence-audit-btn" onClick={() => void refresh()}>
              <FbIcon name="refresh" size={14} />
              <span>Vernieuwen</span>
            </button>
            <button type="button" className="evidence-audit-btn" data-fb-page="knowledge">
              <FbIcon name="file" size={14} />
              <span>Open Knowledge</span>
            </button>
            <button type="button" className="evidence-audit-btn" data-fb-page="brain">
              <FbIcon name="target" size={14} />
              <span>Open Brain</span>
            </button>
          </div>
        </section>
      </div>
    </div>
  );

  const inspector = selected ? (
    <>
      <p className="evidence-insp-quote">“Truth is a process, not a point in time.”</p>

      <section className="insp-section">
        <div className="evidence-insp-head">
          <h3 className="insp-title">Claim details</h3>
          <button
            type="button"
            className="btn btn-sm btn-outline"
            disabled={busy}
            onClick={() => void reassess(selected.id)}
          >
            Herbeoordeel
          </button>
        </div>
        <h2 className="evidence-insp-claim-title">{selected.title}</h2>
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Status</span>
            <span className="v green">● {selected.statusLabel}</span>
          </div>
          <div className="detail-row">
            <span className="k">Betrouwbaarheid</span>
            <span className="v">{selected.reliability != null ? `${selected.reliability}%` : "— (geen signal)"}</span>
          </div>
          <div className="detail-row">
            <span className="k">Provenance</span>
            <span className="v">{selected.provenance}</span>
          </div>
          <div className="detail-row">
            <span className="k">Eerste melding</span>
            <span className="v">{formatDate(selected.firstSeen)}</span>
          </div>
          <div className="detail-row">
            <span className="k">Laatste update</span>
            <span className="v">{formatDate(selected.lastUpdate)}</span>
          </div>
          <div className="detail-row">
            <span className="k">Onderwerp</span>
            <span className="v">{selected.topic}</span>
          </div>
          <div className="detail-row">
            <span className="k">Tags</span>
            <span className="v evidence-insp-tags">
              {selected.tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </span>
          </div>
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Samenvatting</h3>
        <div className="insp-card">
          <p className="evidence-insp-summary">{selected.summary}</p>
        </div>
      </section>

      <section className="insp-section">
        <div className="insp-card">
          <div className="detail-row">
            <span className="k">Verificatie</span>
            <span className="v">{selected.verificationStatus}</span>
          </div>
          <div className="detail-row">
            <span className="k">Gerelateerde links</span>
            <span className="v">
              <span className="evidence-related-pill">
                <b>{selected.relatedCount}</b>
              </span>
            </span>
          </div>
        </div>
      </section>

      <section className="insp-section">
        <div className="evidence-insp-head">
          <h3 className="insp-title">Evidence links ({selected.evidenceLinks.length})</h3>
        </div>
        <div className="evidence-source-refs">
          {!selected.evidenceLinks.length ? (
            <p className="muted">Geen gekoppelde evidence.</p>
          ) : (
            selected.evidenceLinks.map((source, index) => (
              <div key={String((source as { evidence_id?: string }).evidence_id || index)} className="evidence-source-ref">
                <span className="num">{index + 1}</span>
                <div>
                  <strong>{String((source as { evidence_id?: string }).evidence_id || `link-${index + 1}`)}</strong>
                  <small>{String((source as { relation?: string }).relation || "supports")}</small>
                </div>
                <span className="evidence-badge blue">Link</span>
              </div>
            ))
          )}
        </div>
      </section>
    </>
  ) : (
    <>
      <p className="evidence-insp-quote">“Truth is a process, not a point in time.”</p>
      <section className="insp-section">
        <div className="insp-card">
          <p className="muted">{loading ? "Laden…" : "Geen claim geselecteerd."}</p>
        </div>
      </section>
    </>
  );

  const footer = (
    <footer className="dash-footer evidence-footer">
      <span>HADES FINALBETA v0.9.0&nbsp;&nbsp;|&nbsp;&nbsp;Knowledge Platform</span>
      <span className="motto">
        Build a smarter tomorrow. <b>━━</b>
      </span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="evidence"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="evidence-app"
      mainClassName="evidence-main"
      footer={footer}
    />
  );
}
