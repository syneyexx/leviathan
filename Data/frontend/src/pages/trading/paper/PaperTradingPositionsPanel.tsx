import type { PortfolioPosition } from "../../../types/api";
import { fmtMoney, fmtSigned, num, toneClass } from "./utils/format";

export function PaperTradingPositionsPanel({
  positions,
  busyAction,
  onClose,
}: {
  positions: PortfolioPosition[];
  busyAction: string | null;
  onClose: (positionId: string) => void;
}) {
  return (
    <article className="lv-paper-panel lv-paper-positions">
      <header className="lv-paper-panel-head">
        <h2>Open Positions</h2>
        <span className="lv-paper-muted">{positions.length}</span>
      </header>
      {positions.length === 0 ? (
        <p className="lv-paper-state">No active paper positions.</p>
      ) : (
        <div className="lv-paper-table-wrap">
          <table className="lv-paper-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Side</th>
                <th>Size</th>
                <th>Entry</th>
                <th>Mark</th>
                <th>PnL</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.position_id}>
                  <td>{p.symbol}</td>
                  <td className={p.side === "LONG" || p.side === "BUY" ? "is-good" : "is-bad"}>
                    {p.side}
                  </td>
                  <td>{fmtMoney(p.qty, 4)}</td>
                  <td>{fmtMoney(p.avg_entry_price)}</td>
                  <td>{fmtMoney(p.mark_price)}</td>
                  <td className={toneClass(num(p.unrealized_pnl))}>
                    {fmtSigned(p.unrealized_pnl)}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="lv-paper-btn is-mini is-flatten"
                      disabled={busyAction !== null}
                      onClick={() => onClose(p.position_id)}
                    >
                      Close
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}

export function PaperTradingOrdersPanel({ orders }: { orders: Array<Record<string, unknown>> }) {
  const pending = orders.filter((o) => {
    const st = String(o.status || o.state || "").toLowerCase();
    return ["working", "open", "pending", "new", "accepted", "partial"].some((x) => st.includes(x));
  });

  return (
    <article className="lv-paper-panel lv-paper-orders">
      <header className="lv-paper-panel-head">
        <h2>Pending Orders</h2>
        <span className="lv-paper-muted">{pending.length}</span>
      </header>
      {pending.length === 0 ? (
        <p className="lv-paper-state">No pending paper orders.</p>
      ) : (
        <div className="lv-paper-table-wrap">
          <table className="lv-paper-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Side</th>
                <th>Type</th>
                <th>Size</th>
                <th>Price</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {pending.slice(0, 20).map((o, i) => (
                <tr key={String(o.order_id || o.client_order_id || i)}>
                  <td>{String(o.symbol || "—")}</td>
                  <td>{String(o.side || "—")}</td>
                  <td>{String(o.order_type || o.type || "MARKET")}</td>
                  <td>{fmtMoney(String(o.qty ?? o.quantity ?? 0), 4)}</td>
                  <td>{o.price != null ? fmtMoney(String(o.price)) : "—"}</td>
                  <td>
                    <span className="lv-paper-pill is-live">{String(o.status || "working")}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}
