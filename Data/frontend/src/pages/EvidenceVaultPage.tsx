import { useCallback, useEffect, useMemo, useState } from "react";
import { mediaPageArt, mediaPageHeroes } from "../assets/mediaPagesAssets";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { EvidenceRecord, EvidenceStatus } from "../types/api";
import { BarRow, Donut, PageHero, Panel, Pill } from "./media/mr-shared";

type StatusFilter = "all" | "UNVERIFIED" | "VERIFIED" | "FAILED";
type KindFilter = "All" | "ARTIFACT_HASH" | "OBSERVATION_REF" | "FILE_EXISTS" | "COMPOSITE";

const KIND_CHIPS: KindFilter[] = ["All", "ARTIFACT_HASH", "OBSERVATION_REF", "FILE_EXISTS", "COMPOSITE"];

const STATUS_TONE: Record<string, "green" | "gold" | "red" | "cyan" | "muted"> = {
  VERIFIED: "green",
  UNVERIFIED: "gold",
  FAILED: "red",
};

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function formatTs(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString();
  } catch {
    return value;
  }
}

function shortHash(hash: string | null | undefined): string {
  if (!hash) return "—";
  if (hash.length <= 16) return hash;
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`;
}

function confidenceLabel(item: EvidenceRecord): string {
  if (item.confidence == null || Number.isNaN(Number(item.confidence))) return "Not assessed";
  const n = Number(item.confidence);
  if (n <= 1) return `${Math.round(n * 100)}%`;
  return `${Math.round(n)}%`;
}

function statusLabel(status: EvidenceStatus): string {
  return String(status);
}

function kindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
}

export function EvidenceVaultPage() {
  const toast = useAppToast();
  const [items, setItems] = useState<EvidenceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [kindFilter, setKindFilter] = useState<KindFilter>("All");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EvidenceRecord | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listEvidence({
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: 200,
      });
      setItems(res.evidence);
      if (res.evidence.length === 0) {
        setSelectedId(null);
      } else if (!selectedId || !res.evidence.some((e) => e.evidence_id === selectedId)) {
        setSelectedId(res.evidence[0].evidence_id);
      }
    } catch (err) {
      setError(errMsg(err, "Failed to load evidence"));
      setItems([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }, [selectedId, statusFilter]);

  useEffect(() => {
    void loadList();
  }, [statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps -- reload when status filter changes

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setDetailError(null);
      try {
        const res = await api.getEvidence(selectedId);
        if (!cancelled) setDetail(res.evidence);
      } catch (err) {
        if (!cancelled) {
          setDetail(null);
          setDetailError(errMsg(err, "Failed to load evidence detail"));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (kindFilter !== "All" && item.kind !== kindFilter) return false;
      if (!query.trim()) return true;
      const hay = [
        item.evidence_id,
        item.claim,
        item.kind,
        item.status,
        item.path,
        item.content_hash,
        item.artifact_id,
        item.observation_id,
        item.run_id,
        item.job_id,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(query.trim().toLowerCase());
    });
  }, [items, kindFilter, query]);

  const selected = detail?.evidence_id === selectedId ? detail : filtered.find((i) => i.evidence_id === selectedId) ?? null;

  const counts = useMemo(() => {
    const verified = items.filter((i) => i.status === "VERIFIED").length;
    const unverified = items.filter((i) => i.status === "UNVERIFIED").length;
    const failed = items.filter((i) => i.status === "FAILED").length;
    const byKind = new Map<string, number>();
    for (const item of items) {
      byKind.set(item.kind, (byKind.get(item.kind) ?? 0) + 1);
    }
    return { verified, unverified, failed, byKind, total: items.length };
  }, [items]);

  const reviewQueue = useMemo(
    () => items.filter((i) => i.status === "UNVERIFIED" || i.status === "FAILED").slice(0, 12),
    [items],
  );

  const recent = useMemo(() => {
    return [...items]
      .sort((a, b) => String(b.verified_at || b.created_at).localeCompare(String(a.verified_at || a.created_at)))
      .slice(0, 8);
  }, [items]);

  const copyHash = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      /* clipboard may be unavailable */
    }
    toast(`${label} copied`);
  };

  async function onVerify(evidenceId: string) {
    setBusy(true);
    try {
      const res = await api.verifyEvidence(evidenceId);
      setDetail(res.evidence);
      setItems((prev) => prev.map((e) => (e.evidence_id === evidenceId ? res.evidence : e)));
      toast(`Verification: ${res.evidence.status}`);
    } catch (err) {
      toast(errMsg(err, "Verification failed"));
    } finally {
      setBusy(false);
    }
  }

  const donutSlices = [
    { value: counts.verified || 0, color: "#4ade80" },
    { value: counts.unverified || 0, color: "#f0c875" },
    { value: counts.failed || 0, color: "#f87171" },
  ];
  const donutTotal = donutSlices.reduce((s, x) => s + x.value, 0);
  const verifiedPct = donutTotal === 0 ? "—" : `${Math.round((counts.verified / donutTotal) * 100)}%`;

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Evidence Mode"
      searchPlaceholder="Search evidence, sources, content, hash, or tags..."
      systemItems={[
        "SYSTEMS OPERATIONAL",
        `${counts.total} ITEMS`,
        loading ? "LOADING" : error ? "ERROR" : "LIVE",
      ]}
      layout="wide"
      pageClass="lv-app--media-research"
    >
      <main className="lv-main lv-mr-main">
        <PageHero image={mediaPageHeroes.evidence} title="EVIDENCE VAULT" imageOnly />

        <Panel>
          <div className="lv-mr-toolbar">
            <input
              className="lv-mr-input"
              style={{ flex: 1, minWidth: 220 }}
              placeholder="Search evidence, claim, hash, path…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search evidence"
            />
            <select
              className="lv-mr-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              aria-label="Status filter"
            >
              <option value="all">All statuses</option>
              <option value="VERIFIED">Verified</option>
              <option value="UNVERIFIED">Unverified</option>
              <option value="FAILED">Failed</option>
            </select>
            <button
              type="button"
              className="lv-mr-btn"
              disabled={busy || loading}
              onClick={() => void loadList()}
            >
              Refresh
            </button>
          </div>
          <div className="lv-mr-tabs" role="tablist" aria-label="Evidence kind">
            {KIND_CHIPS.map((c) => (
              <button
                key={c}
                type="button"
                role="tab"
                className={`lv-mr-tab${kindFilter === c ? " is-active" : ""}`}
                onClick={() => setKindFilter(c)}
              >
                {c === "All" ? "All" : kindLabel(c)}
              </button>
            ))}
          </div>
        </Panel>

        {error ? (
          <Panel>
            <div className="lv-models-banner is-error" role="alert">
              <strong>Evidence unavailable</strong>
              <span>{error}</span>
            </div>
          </Panel>
        ) : null}

        <section className="lv-ev-kpis" aria-label="Evidence KPIs">
          <article className="lv-mr-kpi is-cyan">
            <div className="lbl">Evidence Items</div>
            <div className="val">{loading ? "…" : counts.total}</div>
            <div className="sub">
              <span className="lv-mr-muted">from /api/evidence</span>
            </div>
          </article>
          <article className="lv-mr-kpi is-green">
            <div className="lbl">Verified</div>
            <div className="val">{loading ? "…" : counts.verified}</div>
            <div className="sub">
              <Pill tone="green">{verifiedPct}</Pill>
            </div>
          </article>
          <article className="lv-mr-kpi is-gold">
            <div className="lbl">Unverified</div>
            <div className="val">{loading ? "…" : counts.unverified}</div>
            <div className="sub">
              <span className="lv-mr-muted">awaiting verify</span>
            </div>
          </article>
          <article className="lv-mr-kpi is-red">
            <div className="lbl">Failed</div>
            <div className="val">{loading ? "…" : counts.failed}</div>
            <div className="sub">
              <span className={counts.failed > 0 ? "lv-mr-bad" : "lv-mr-muted"}>
                {counts.failed > 0 ? "needs attention" : "none"}
              </span>
            </div>
          </article>
        </section>

        <section className="lv-mr-split">
          <Panel title={`Evidence Items · ${filtered.length}`}>
            {loading ? (
              <div className="lv-models-banner" role="status">
                Loading evidence…
              </div>
            ) : null}
            {!loading && filtered.length === 0 ? (
              <div className="lv-models-empty">
                <h2>NO EVIDENCE</h2>
                <p>
                  The vault is empty or nothing matches this filter. Evidence appears only after real claims are
                  recorded — never fabricated.
                </p>
              </div>
            ) : (
              <div style={{ overflow: "auto" }}>
                <table className="lv-ev-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Claim</th>
                      <th>Kind</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((item) => (
                      <tr
                        key={item.evidence_id}
                        className={item.evidence_id === selectedId ? "is-active" : undefined}
                        onClick={() => setSelectedId(item.evidence_id)}
                        style={{ cursor: "pointer" }}
                      >
                        <td>
                          <strong>{item.evidence_id}</strong>
                        </td>
                        <td>{item.claim}</td>
                        <td>
                          <Pill tone="muted">{kindLabel(item.kind)}</Pill>
                        </td>
                        <td>
                          <Pill tone={STATUS_TONE[item.status] ?? "muted"}>{statusLabel(item.status)}</Pill>
                        </td>
                        <td className="lv-mr-muted">{formatTs(item.created_at)}</td>
                        <td>
                          <span className="lv-mr-muted">{confidenceLabel(item)}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel
            title="Evidence Details"
            action={
              selected ? (
                <Pill tone={STATUS_TONE[selected.status] ?? "muted"}>{statusLabel(selected.status)}</Pill>
              ) : undefined
            }
          >
            {detailError ? (
              <div className="lv-models-banner is-error" role="alert">
                {detailError}
              </div>
            ) : null}
            {!selected ? (
              <p className="lv-mr-muted" style={{ fontSize: 12 }}>
                Select an evidence record to inspect provenance and verification.
              </p>
            ) : (
              <>
                <div className="lv-ev-preview">
                  <img src={mediaPageArt.evidenceSat} alt="" />
                </div>
                <strong style={{ color: "#f0ebe3", marginTop: 8 }}>{selected.claim}</strong>
                <div className="lv-mr-muted" style={{ fontSize: 12, marginTop: 4 }}>
                  {selected.evidence_id} · {kindLabel(selected.kind)}
                </div>

                <div className="lv-mr-panel-title" style={{ marginTop: 12 }}>
                  Metadata
                </div>
                <div style={{ fontSize: 12, display: "grid", gap: 6 }}>
                  <div className="lv-rs-active-item">
                    <span className="lv-mr-muted">Created</span>
                    <span>{formatTs(selected.created_at)}</span>
                  </div>
                  <div className="lv-rs-active-item">
                    <span className="lv-mr-muted">Verified at</span>
                    <span>{formatTs(selected.verified_at)}</span>
                  </div>
                  <div className="lv-rs-active-item">
                    <span className="lv-mr-muted">Confidence</span>
                    <span>{confidenceLabel(selected)}</span>
                  </div>
                  <div className="lv-rs-active-item">
                    <span className="lv-mr-muted">Path</span>
                    <span>{dash(selected.path)}</span>
                  </div>
                  <div className="lv-rs-active-item">
                    <span className="lv-mr-muted">Artifact</span>
                    <span>{dash(selected.artifact_id)}</span>
                  </div>
                  <div className="lv-rs-active-item">
                    <span className="lv-mr-muted">Observation</span>
                    <span>{dash(selected.observation_id)}</span>
                  </div>
                  <div className="lv-rs-active-item">
                    <span className="lv-mr-muted">Run / Job</span>
                    <span>
                      {dash(selected.run_id)} / {dash(selected.job_id)}
                    </span>
                  </div>
                  {selected.error ? (
                    <div className="lv-rs-active-item">
                      <span className="lv-mr-muted">Error</span>
                      <span className="lv-mr-bad">{selected.error}</span>
                    </div>
                  ) : null}
                </div>

                <div className="lv-mr-panel-title" style={{ marginTop: 12 }}>
                  Content hash
                </div>
                <div className="lv-ev-hash">
                  <span>
                    <span className="lv-mr-muted">SHA / digest</span> {shortHash(selected.content_hash)}
                  </span>
                  {selected.content_hash ? (
                    <button
                      type="button"
                      className="lv-mr-btn lv-mr-btn--ghost"
                      onClick={() => void copyHash("Hash", selected.content_hash!)}
                    >
                      Copy
                    </button>
                  ) : null}
                </div>
                {selected.content_hash ? (
                  <p className="lv-mr-muted" style={{ fontSize: 10, wordBreak: "break-all" }}>
                    {selected.content_hash}
                  </p>
                ) : (
                  <p className="lv-mr-muted" style={{ fontSize: 11 }}>
                    No content hash on this record.
                  </p>
                )}

                <div className="lv-mr-toolbar" style={{ marginTop: 10 }}>
                  <button
                    type="button"
                    className="lv-mr-btn lv-mr-btn--gold"
                    disabled={busy}
                    onClick={() => void onVerify(selected.evidence_id)}
                  >
                    Verify
                  </button>
                </div>
              </>
            )}
          </Panel>
        </section>

        <section className="lv-ev-bottom">
          <Panel title="Kinds">
            {counts.byKind.size === 0 ? (
              <p className="lv-mr-muted" style={{ fontSize: 12 }}>
                No kind distribution until evidence exists.
              </p>
            ) : (
              [...counts.byKind.entries()].map(([label, value]) => {
                const pct = counts.total === 0 ? 0 : Math.round((value / counts.total) * 100);
                return (
                  <div key={label} className="lv-ev-cat-row">
                    <span>{kindLabel(label)}</span>
                    <div className="lv-mr-bar">
                      <span style={{ width: `${pct}%`, background: "#22c9d6" }} />
                    </div>
                    <strong>
                      {value} · {pct}%
                    </strong>
                  </div>
                );
              })
            )}
          </Panel>

          <Panel title="Status mix">
            {donutTotal === 0 ? (
              <p className="lv-mr-muted" style={{ fontSize: 12 }}>
                Not assessed — no records.
              </p>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <Donut slices={donutSlices.filter((s) => s.value > 0)} center={verifiedPct} />
                <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11 }}>
                  <BarRow
                    label="Verified"
                    value={donutTotal ? Math.round((counts.verified / donutTotal) * 100) : 0}
                    color="#4ade80"
                  />
                  <BarRow
                    label="Unverified"
                    value={donutTotal ? Math.round((counts.unverified / donutTotal) * 100) : 0}
                    color="#f0c875"
                  />
                  <BarRow
                    label="Failed"
                    value={donutTotal ? Math.round((counts.failed / donutTotal) * 100) : 0}
                    color="#f87171"
                  />
                </div>
              </div>
            )}
          </Panel>

          <Panel title="Review queue">
            {reviewQueue.length === 0 ? (
              <p className="lv-mr-muted" style={{ fontSize: 12 }}>
                Nothing pending verification.
              </p>
            ) : (
              reviewQueue.map((row) => (
                <button
                  key={row.evidence_id}
                  type="button"
                  className="lv-rs-active-item"
                  style={{ width: "100%", textAlign: "left", cursor: "pointer", background: "transparent", border: 0 }}
                  onClick={() => setSelectedId(row.evidence_id)}
                >
                  <span>
                    <strong>{row.evidence_id}</strong>
                    <span className="lv-mr-muted"> · {row.claim}</span>
                  </span>
                  <Pill tone={STATUS_TONE[row.status] ?? "muted"}>{statusLabel(row.status)}</Pill>
                </button>
              ))
            )}
          </Panel>

          <Panel title="Recent activity">
            {recent.length === 0 ? (
              <p className="lv-mr-muted" style={{ fontSize: 12 }}>
                No recent evidence events.
              </p>
            ) : (
              <ol className="lv-ev-timeline">
                {recent.map((ev) => (
                  <li key={ev.evidence_id}>
                    <time>{formatTs(ev.verified_at || ev.created_at)}</time>
                    <span>
                      {ev.evidence_id} · {statusLabel(ev.status)} · {ev.claim}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </Panel>
        </section>

        <blockquote className="lv-rs-quote">
          <img src={mediaPageArt.evidenceBust} alt="" />
          <span>“Provenance is the product. If we cannot verify it, we do not claim it.”</span>
        </blockquote>
      </main>
    </AppShell>
  );
}
