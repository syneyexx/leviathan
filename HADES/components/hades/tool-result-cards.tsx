"use client";

type ToolCard = Record<string, unknown>;

export function ToolResultCards({ cards }: { cards?: ToolCard[] | null }) {
  if (!cards?.length) return null;
  return (
    <div className="tool-cards" aria-label="Tool result cards">
      {cards.map((card, index) => {
        const cardType = String(card.card_type || "log");
        const table = Array.isArray(card.table) ? (card.table as unknown[][]) : null;
        const rows = Array.isArray(card.rows) ? (card.rows as Array<Record<string, unknown>>) : null;
        const diff = typeof card.diff === "string" ? card.diff : null;
        return (
          <div className="tool-card" key={`${String(card.tool_name || index)}-${index}`}>
            <strong>{String(card.tool_name || "tool")}</strong>
            <small>{cardType} · {String(card.status || "")}</small>
            {card.summary ? <p>{String(card.summary)}</p> : null}
            {card.error ? <p className="tool-card-error">{String(card.error)}</p> : null}
            {diff ? <pre className="tool-card-diff">{diff.slice(0, 4000)}</pre> : null}
            {table?.length ? (
              <div className="tool-card-table-wrap">
                <table className="tool-card-table">
                  <tbody>
                    {table.slice(0, 12).map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {(Array.isArray(row) ? row : [row]).slice(0, 6).map((cell, cellIndex) => (
                          <td key={cellIndex}>{String(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {!diff && !table?.length && rows?.length ? (
              <ul className="tool-card-rows">
                {rows.slice(0, 8).map((row, rowIndex) => (
                  <li key={rowIndex}>
                    <code>{String(row.key || "")}</code>
                    <span>{String(row.value || "").slice(0, 240)}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
