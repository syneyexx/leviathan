import type { AnalyticsDashboard } from "../../types/api";
import type { RankingRange } from "../../pages/analytics/useAnalyticsWorkspace";

type Props = {
  dashboard: AnalyticsDashboard | null;
  rankingRange: RankingRange;
  onRankingRange: (r: RankingRange) => void;
};

function formatItems(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

export function AnalyticsRankingsRow({ dashboard, rankingRange, onRankingRange }: Props) {
  const r = dashboard?.rankings;
  return (
    <section className="lv-an-rank-row" aria-label="Rankings">
      <article id="lv-an-panel-top-agents" className="lv-panel lv-an-card">
        <div className="lv-an-card-head">
          <div className="lv-section-label">Top Agents (Kennis Toevoegingen)</div>
          <label className="lv-an-range-select">
            <select
              value={rankingRange}
              onChange={(e) => onRankingRange(e.target.value as RankingRange)}
              aria-label="Ranking periode"
            >
              <option value="7d">Laatste 7 dagen</option>
              <option value="30d">Laatste 30 dagen</option>
            </select>
          </label>
        </div>
        {!r?.topAgents?.length ? (
          <p className="lv-muted lv-an-empty">Geen gegevens in deze periode.</p>
        ) : (
          <table className="lv-an-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Agent</th>
                <th>Items</th>
                <th>Grootte</th>
                <th>Success Rate</th>
              </tr>
            </thead>
            <tbody>
              {r.topAgents.map((a) => (
                <tr key={a.agentId}>
                  <td>{a.rank}</td>
                  <td>{a.name}</td>
                  <td>{formatItems(a.items)}</td>
                  <td>{a.sizeStatus === "MEASURED" && a.sizeGb != null ? `${a.sizeGb} GB` : "—"}</td>
                  <td>
                    {a.successStatus === "MEASURED" && a.successRatePercent != null ? (
                      <div className="lv-an-bar-cell">
                        <div className="lv-an-bar">
                          <span style={{ width: `${a.successRatePercent}%` }} />
                        </div>
                        <strong>{a.successRatePercent}%</strong>
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </article>

      <article id="lv-an-panel-top-bronnen" className="lv-panel lv-an-card">
        <div className="lv-an-card-head">
          <div className="lv-section-label">Top Bronnen</div>
        </div>
        {!r?.topSources?.length ? (
          <p className="lv-muted lv-an-empty">Geen gegevens in deze periode.</p>
        ) : (
          <table className="lv-an-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Bron</th>
                <th>Items</th>
                <th>Grootte</th>
                <th>Percentage</th>
              </tr>
            </thead>
            <tbody>
              {r.topSources.map((s) => (
                <tr key={s.key}>
                  <td>{s.rank}</td>
                  <td>{s.name}</td>
                  <td>{formatItems(s.items)}</td>
                  <td>{s.sizeStatus === "MEASURED" && s.sizeGb != null ? `${s.sizeGb} GB` : "—"}</td>
                  <td>
                    <div className="lv-an-bar-cell">
                      <div className="lv-an-bar">
                        <span style={{ width: `${s.percent}%` }} />
                      </div>
                      <strong>{s.percent}%</strong>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </article>

      <article id="lv-an-panel-tags" className="lv-panel lv-an-card">
        <div className="lv-an-card-head">
          <div className="lv-section-label">Populairste Tags</div>
        </div>
        {!r?.popularTags?.length ? (
          <p className="lv-muted lv-an-empty">Geen gegevens in deze periode.</p>
        ) : (
          <table className="lv-an-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Tag</th>
                <th>Aantal</th>
                <th>Trend</th>
              </tr>
            </thead>
            <tbody>
              {r.popularTags.map((t) => (
                <tr key={t.tag}>
                  <td>{t.rank}</td>
                  <td>
                    <span className="lv-an-tag">{t.tag}</span>
                  </td>
                  <td>{t.count.toLocaleString("nl-NL")}</td>
                  <td className={t.trendPercent != null && t.trendPercent >= 0 ? "is-good" : ""}>
                    {t.trendPercent == null
                      ? "—"
                      : `${t.trendPercent > 0 ? "+" : ""}${t.trendPercent}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </article>
    </section>
  );
}
