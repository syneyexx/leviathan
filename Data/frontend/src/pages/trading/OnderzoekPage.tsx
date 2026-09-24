import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tradingHeroes } from "../../assets/tradingAssets";
import { api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import type { TradingDecision, TradingNewsFeed, TradingNewsItem, TradingNewsSignal } from "../../types/api";
import { TradeOrchestraSection } from "../agents/TradeOrchestraSection";
import { decisionOneLiner, stageLabel } from "../agents/tradingHelpers";
import { Panel, TradingHero } from "./shared";

export function OnderzoekPage() {
  const [feeds, setFeeds] = useState<TradingNewsFeed[]>([]);
  const [items, setItems] = useState<TradingNewsItem[]>([]);
  const [signals, setSignals] = useState<TradingNewsSignal[]>([]);
  const [decisions, setDecisions] = useState<TradingDecision[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pollResult, setPollResult] = useState<string | null>(null);
  const [feedName, setFeedName] = useState("");
  const [feedUrl, setFeedUrl] = useState("");
  const [latency, setLatency] = useState("0");
  const [license, setLicense] = useState("UNKNOWN");
  const [asOf, setAsOf] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [f, i, s, d] = await Promise.all([
        api.listTradingNewsFeeds(),
        api.listTradingNewsItems({ asOf: asOf.trim() || undefined, limit: 50 }),
        api.listTradingNewsSignals({ asOf: asOf.trim() || undefined, limit: 50 }),
        api.listTradingDecisions({ limit: 60 }),
      ]);
      setFeeds(f.feeds);
      setItems(i.items);
      setSignals(s.signals);
      setDecisions(d.decisions);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [asOf]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const addFeed = async () => {
    if (!feedName.trim() || !feedUrl.trim()) return;
    setBusy(true);
    try {
      await api.createTradingNewsFeed({
        name: feedName.trim(),
        url: feedUrl.trim(),
        declaredLatencySeconds: Number(latency) || 0,
        licenseState: license,
      });
      setFeedName("");
      setFeedUrl("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const poll = async (feedId?: string) => {
    setBusy(true);
    try {
      const res = await api.pollTradingNews(feedId);
      setPollResult(
        `${String(res.status)} · via ${String(res.executedVia ?? "?")}${res.jobId ? ` · job ${String(res.jobId)}` : ""}${
          res.inserted !== undefined ? ` · ${String(res.inserted)} nieuw` : ""
        }`,
      );
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggleFeed = async (feed: TradingNewsFeed) => {
    try {
      await api.updateTradingNewsFeed(feed.feedId, { enabled: !feed.enabled });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const removeFeed = async (feed: TradingNewsFeed) => {
    try {
      await api.deleteTradingNewsFeed(feed.feedId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <TradingHero title="Trading-onderzoek" image={tradingHeroes.paper} />
      <div className="lv-tp-wrap">
        <p className="lv-tp-lede">
          Trade-orkesten en trading-agents werken uitsluitend op papier. Agents stellen voor, bekritiseren en
          verklaren; een deterministische risico-engine beslist. Nieuws wordt via workers opgehaald en is pas
          zichtbaar vanaf <code>available_at</code>. Live trading is per constructie geblokkeerd.
        </p>
        {error && <div className="lv-tp-banner is-bad">{error}</div>}

        <Panel title="Trade-orkesten">
          <TradeOrchestraSection compact />
        </Panel>

        <div className="lv-tp-grid-2">
          <Panel
            title="Nieuwsfeeds"
            action={
              <button type="button" disabled={busy} onClick={() => void poll()}>
                Alle feeds ophalen
              </button>
            }
          >
            <div className="lv-tp-form">
              <label>
                Naam<input value={feedName} onChange={(e) => setFeedName(e.target.value)} />
              </label>
              <label>
                URL (RSS/Atom/JSON)<input value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} />
              </label>
              <label>
                Aangegeven vertraging (s)<input value={latency} onChange={(e) => setLatency(e.target.value)} />
              </label>
              <label>
                Licentie
                <select value={license} onChange={(e) => setLicense(e.target.value)}>
                  <option value="UNKNOWN">UNKNOWN</option>
                  <option value="DECLARED_FREE">DECLARED_FREE</option>
                  <option value="DECLARED_RESTRICTED">DECLARED_RESTRICTED</option>
                </select>
              </label>
              <button type="button" disabled={busy || !feedName.trim() || !feedUrl.trim()} onClick={() => void addFeed()}>
                Feed toevoegen
              </button>
            </div>
            {pollResult ? <p className="lv-tp-muted">Laatste poll: {pollResult}</p> : null}
            <ul className="lv-tp-list">
              {feeds.length === 0 ? <li className="lv-tp-muted">Nog geen feeds geregistreerd.</li> : null}
              {feeds.map((f) => (
                <li key={f.feedId}>
                  <strong>{f.name}</strong> · {f.kind} · {f.enabled ? "aan" : "uit"} · {f.licenseState} · laatste:{" "}
                  {f.lastStatus ?? "—"}
                  {f.lastError ? ` (${f.lastError})` : ""}
                  <div>
                    <button type="button" onClick={() => void poll(f.feedId)}>Ophalen</button>{" "}
                    <button type="button" onClick={() => void toggleFeed(f)}>{f.enabled ? "Uitzetten" : "Aanzetten"}</button>{" "}
                    <button type="button" onClick={() => void removeFeed(f)}>Verwijderen</button>
                  </div>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel
            title="Nieuwsitems (causaal gefilterd)"
            action={
              <input
                placeholder="as_of (ISO) — leeg = alles"
                value={asOf}
                onChange={(e) => setAsOf(e.target.value)}
                style={{ minWidth: 220 }}
              />
            }
          >
            <ul className="lv-tp-list">
              {items.length === 0 ? <li className="lv-tp-muted">Geen items zichtbaar voor dit as_of.</li> : null}
              {items.map((i) => (
                <li key={i.itemId}>
                  <strong>{i.title}</strong>
                  <div className="lv-tp-muted">
                    {i.source} · beschikbaar vanaf {i.availableAt} · gepubliceerd {i.publishedAt ?? "onbekend"} ·{" "}
                    {i.licenseState}
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <div className="lv-tp-grid-2">
          <Panel title="Nieuwssignalen (data, geen autoriteit)">
            <ul className="lv-tp-list">
              {signals.length === 0 ? <li className="lv-tp-muted">Nog geen signalen — start een nieuwsdigest-missie.</li> : null}
              {signals.map((s) => (
                <li key={s.signalId}>
                  {s.direction} · {s.eventType} · {s.instruments.join(", ") || "—"} · magnitude {s.magnitude.toFixed(2)} ·
                  conf {s.confidence.toFixed(2)} · {s.horizon} · as_of {s.asOf} · model {s.modelId ?? "—"}
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Beslissingsketen (append-only)">
            <ul className="lv-tp-list">
              {decisions.length === 0 ? <li className="lv-tp-muted">Nog geen beslissingsrecords.</li> : null}
              {decisions.map((d) => (
                <li key={d.decisionId}>
                  <span className="lv-tp-muted">{d.asOf.slice(0, 16)}</span> [{stageLabel(d.stage)}] {decisionOneLiner(d)}{" "}
                  <span className="lv-tp-muted">· {d.role} · {d.modelId ?? "tier0"} · mandaat {d.mandateFingerprint}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <p className="lv-tp-footer">
          <Link to="/agents">Agents</Link>
          {" · "}
          <Link to="/trading/paper">Paper trading</Link>
          {" · "}
          <Link to="/trading/simulatie">Simulatie</Link>
        </p>
      </div>
    </AppShell>
  );
}
