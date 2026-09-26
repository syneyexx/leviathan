import { useCallback, useEffect, useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { Panel, TradingHero } from "./shared";
import {
  controlRoomStatusLabel,
  controlRoomStatusTone,
} from "./controlRoomStatus";

type ControlRoomSnapshot = {
  generatedAt?: string;
  liveTrading?: Record<string, unknown>;
  gaps?: Record<string, unknown>;
  multiAsset?: Record<string, unknown>;
  health?: Record<string, unknown>;
  reconciliation?: Record<string, unknown>;
  exceptions?: Record<string, unknown>;
  audit?: Record<string, unknown>;
  overallStatus?: string;
  notes?: string[];
  truth?: Record<string, unknown>;
};

function pillClass(status: string | null | undefined): string {
  const tone = controlRoomStatusTone(status);
  if (tone === "good") return " is-live";
  if (tone === "bad") return " is-bad";
  return "";
}

function StatusPill({ status }: { status: string | null | undefined }) {
  const label = controlRoomStatusLabel(status);
  return <span className={`lv-tp-pill${pillClass(label)}`}>{label}</span>;
}

export function InstitutionalControlRoomPage() {
  const [snap, setSnap] = useState<ControlRoomSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.marketSimInstitutionalControlRoom();
      setSnap(data as ControlRoomSnapshot);
    } catch (err) {
      setSnap(null);
      setError(err instanceof Error ? err.message : "Control Room laden mislukt");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const live = snap?.liveTrading ?? {};
  const liveAvailable = String(live.LIVE_TRADING_AVAILABLE ?? "BLOCKED").toUpperCase();
  const liveBlocked = liveAvailable === "BLOCKED" || live.ok === true;
  const healthOverall = String(snap?.health?.overall ?? snap?.health?.status ?? "UNMEASURED");
  const gaps = snap?.gaps ?? {};
  const multi = snap?.multiAsset ?? {};
  const recon = snap?.reconciliation ?? {};
  const exceptions = snap?.exceptions ?? {};
  const audit = snap?.audit ?? {};

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <TradingHero
        title="Control Room"
        kicker="Institutionele waarheidsstatus — geen nep-groen"
        image={tradingHeroes.broker}
      />
      <main className="lv-main lv-tp-main">
        <div className="lv-tp-wrap">
          <p className="lv-tp-lede">
            Live trading blijft BLOCKED. Panels tonen UNMEASURED / EMPTY / DEGRADED eerlijk —
            geen fake metrics.
          </p>

          <div className="lv-tp-actions" style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem" }}>
            <button type="button" className="lv-tp-btn" disabled={loading} onClick={() => void load()}>
              Vernieuwen
            </button>
          </div>

          {error ? <div className="lv-tp-banner is-bad">{error}</div> : null}

          {loading && !snap ? (
            <p className="lv-tp-muted">Control Room laden…</p>
          ) : null}

          {!loading && !snap && !error ? (
            <p className="lv-tp-muted">Geen snapshot beschikbaar.</p>
          ) : null}

          {snap ? (
            <>
              <section className="lv-tp-ticker" aria-label="Control Room status">
                <article className="lv-tp-tick">
                  <div className="lv-tp-tick-label">Overall</div>
                  <div className="lv-tp-tick-value" style={{ fontSize: "0.85rem" }}>
                    <StatusPill status={snap.overallStatus} />
                  </div>
                  <div className="lv-tp-tick-foot">
                    <span>{snap.generatedAt ? String(snap.generatedAt).slice(0, 19) : "—"}</span>
                  </div>
                </article>
                <article className="lv-tp-tick">
                  <div className="lv-tp-tick-label">Live trading</div>
                  <div className="lv-tp-tick-value">{liveBlocked ? "BLOCKED" : "UNLOCKED"}</div>
                  <div className="lv-tp-tick-foot">
                    <span className={liveBlocked ? "is-good" : "is-bad"}>LiveTradingGuard</span>
                  </div>
                </article>
                <article className="lv-tp-tick">
                  <div className="lv-tp-tick-label">Health</div>
                  <div className="lv-tp-tick-value" style={{ fontSize: "0.85rem" }}>
                    <StatusPill status={healthOverall} />
                  </div>
                  <div className="lv-tp-tick-foot">
                    <span>
                      {healthOverall === "UNMEASURED"
                        ? "niet gemeten — geen groene claim"
                        : String(snap.health?.notes ?? "—")}
                    </span>
                  </div>
                </article>
                <article className="lv-tp-tick">
                  <div className="lv-tp-tick-label">Open gaps</div>
                  <div className="lv-tp-tick-value">{String(gaps.openGapCount ?? "—")}</div>
                  <div className="lv-tp-tick-foot">
                    <span>totaal {String(gaps.count ?? "—")}</span>
                  </div>
                </article>
              </section>

              <div className="lv-tp-grid-2" style={{ marginTop: "1rem" }}>
                <Panel title="Capability gaps">
                  {gaps.byStatus && typeof gaps.byStatus === "object" ? (
                    <ul className="lv-tp-list">
                      {Object.entries(gaps.byStatus as Record<string, unknown>).map(([k, v]) => (
                        <li key={k}>
                          <StatusPill status={k} /> {String(v)}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="lv-tp-muted">Geen gap-statusbreakdown.</p>
                  )}
                </Panel>

                <Panel title="Multi-asset">
                  <ul className="lv-tp-list">
                    <li>
                      Status: <StatusPill status={String(multi.status ?? multi.overall ?? "UNMEASURED")} />
                    </li>
                    <li>
                      Families:{" "}
                      {Array.isArray(multi.families)
                        ? multi.families.length
                        : String(multi.familyCount ?? "—")}
                    </li>
                  </ul>
                  {Array.isArray(multi.families) && multi.families.length > 0 ? (
                    <ul className="lv-tp-list">
                      {(multi.families as Record<string, unknown>[]).slice(0, 12).map((f, i) => (
                        <li key={String(f.family ?? f.name ?? i)}>
                          {String(f.family ?? f.name ?? "?")}:{" "}
                          <StatusPill
                            status={String(
                              f.capability ?? f.status ?? f.HISTORICAL_SIM_AVAILABLE ?? "UNMEASURED",
                            )}
                          />
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="lv-tp-muted">Geen family-detail in snapshot.</p>
                  )}
                </Panel>

                <Panel title="Reconciliation">
                  <ul className="lv-tp-list">
                    <li>
                      Status: <StatusPill status={String(recon.status ?? "EMPTY")} />
                    </li>
                    <li>Open breaks: {String(recon.openCount ?? 0)}</li>
                  </ul>
                  {Array.isArray(recon.notes) ? (
                    <p className="lv-tp-muted">{(recon.notes as string[]).join(" · ")}</p>
                  ) : null}
                </Panel>

                <Panel title="Exceptions & audit">
                  <ul className="lv-tp-list">
                    <li>
                      Exceptions: <StatusPill status={String(exceptions.status ?? "EMPTY")} /> · open{" "}
                      {String(exceptions.openCount ?? 0)}
                    </li>
                    <li>
                      Audit: <StatusPill status={String(audit.status ?? "UNMEASURED")} />
                    </li>
                  </ul>
                  {Array.isArray(audit.notes) ? (
                    <p className="lv-tp-muted">{(audit.notes as string[]).join(" · ")}</p>
                  ) : null}
                </Panel>
              </div>

              {Array.isArray(snap.notes) && snap.notes.length > 0 ? (
                <Panel title="Notities">
                  <ul className="lv-tp-list">
                    {snap.notes.map((n) => (
                      <li key={n} className="lv-tp-muted">
                        {n}
                      </li>
                    ))}
                  </ul>
                </Panel>
              ) : null}

              <p className="lv-tp-footer">
                Truth: snapshot_from_real_state · unmeasured_panels_stay_unmeasured · no_fake_green ·
                live BLOCKED
              </p>
            </>
          ) : null}
        </div>
      </main>
    </AppShell>
  );
}
