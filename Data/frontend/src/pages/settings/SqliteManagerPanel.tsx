import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { SqliteDatabaseStatus, SqliteTableInfo } from "../../types/api";

const DOMAINS = ["CONTROL", "KNOWLEDGE", "MARKET"] as const;

/**
 * Operator panel for the three canonical SQLite databases.
 * Backend remains authority — this UI only presents /api/sqlite/* truth.
 */
export function SqliteManagerPanel() {
  const [databases, setDatabases] = useState<SqliteDatabaseStatus[] | null>(null);
  const [domain, setDomain] = useState<(typeof DOMAINS)[number]>("CONTROL");
  const [tables, setTables] = useState<SqliteTableInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sql, setSql] = useState("SELECT name FROM sqlite_master WHERE type='table' LIMIT 20");
  const [queryResult, setQueryResult] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await api.listSqliteDatabases();
      setDatabases(payload.databases);
    } catch (err) {
      setDatabases(null);
      setError(err instanceof ApiError ? err.message : "Failed to load SQLite databases");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadTables = useCallback(async (selected: string) => {
    setTables(null);
    setError(null);
    try {
      const payload = await api.sqliteDatabaseTables(selected);
      setTables(payload.tables);
    } catch (err) {
      setTables([]);
      setError(err instanceof ApiError ? err.message : `Failed to list tables for ${selected}`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadTables(domain);
  }, [domain, loadTables]);

  async function runQuery() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.sqliteQuery(domain, sql, 50);
      setQueryResult(JSON.stringify(result, null, 2));
    } catch (err) {
      setQueryResult("");
      setError(err instanceof ApiError ? err.message : "Query failed");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <p className="lv-muted">Loading SQLite databases…</p>;
  }

  if (!databases?.length) {
    return (
      <div>
        <p className="lv-muted">No canonical databases reported.</p>
        {error ? <p role="alert">{error}</p> : null}
        <button type="button" onClick={() => void load()}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <section aria-label="SQLite Manager" style={{ display: "grid", gap: "0.75rem" }}>
      <header>
        <h3 style={{ margin: 0 }}>SQLite Manager</h3>
        <p className="lv-muted" style={{ margin: "0.25rem 0 0" }}>
          Control / Knowledge / Market — reads and allowlisted writes require an explicit selected domain.
        </p>
      </header>

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {DOMAINS.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={domain === item}
            onClick={() => setDomain(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
        {databases.map((db) => (
          <li key={db.domain}>
            <strong>{db.domain}</strong>
            {db.exists ? ` · v${db.schemaVersion} · ${db.sizeBytes} bytes` : " · missing"}
            {domain === db.domain ? " ← selected" : ""}
          </li>
        ))}
      </ul>

      {error ? (
        <p role="alert" style={{ color: "#b00020" }}>
          {error}
        </p>
      ) : null}

      <div>
        <h4 style={{ margin: "0 0 0.35rem" }}>Tables ({domain})</h4>
        {tables == null ? (
          <p className="lv-muted">Loading tables…</p>
        ) : tables.length === 0 ? (
          <p className="lv-muted">No tables in {domain}.</p>
        ) : (
          <p className="lv-muted">{tables.map((t) => t.name).join(", ")}</p>
        )}
      </div>

      <label style={{ display: "grid", gap: "0.35rem" }}>
        <span>Read query against {domain}</span>
        <textarea value={sql} onChange={(event) => setSql(event.target.value)} rows={3} />
      </label>
      <button type="button" disabled={busy} onClick={() => void runQuery()}>
        {busy ? "Running…" : "Run SELECT/PRAGMA"}
      </button>
      {queryResult ? (
        <pre style={{ maxHeight: 240, overflow: "auto", fontSize: 12 }}>{queryResult}</pre>
      ) : null}
    </section>
  );
}
