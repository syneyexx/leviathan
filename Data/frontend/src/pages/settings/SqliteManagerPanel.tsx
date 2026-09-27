import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import type {
  SqliteCellValue,
  SqliteDatabaseStatus,
  SqliteIntegrityResult,
  SqliteOwnershipAudit,
  SqliteRowsPage,
  SqliteRuntimeStatus,
  SqliteTableDetail,
  SqliteTableInfo,
} from "../../types/api";

const DOMAINS = ["CONTROL", "KNOWLEDGE", "MARKET"] as const;
type Domain = (typeof DOMAINS)[number];
type Section = "overview" | "explorer" | "sql" | "integrity" | "runtime";

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
}

function cellDisplay(cell: SqliteCellValue | undefined): string {
  if (!cell || cell.kind === "null") return "NULL";
  if (cell.kind === "blob") return `BLOB(${cell.byteLength ?? "?"}B) ${String(cell.value)}`;
  const text = String(cell.value ?? "");
  return cell.truncated ? `${text}…` : text;
}

/**
 * Operator panel for the three canonical SQLite databases.
 * Backend remains authority — this UI only presents /api/sqlite/* truth.
 */
export function SqliteManagerPanel() {
  const [databases, setDatabases] = useState<SqliteDatabaseStatus[] | null>(null);
  const [domain, setDomain] = useState<Domain>("CONTROL");
  const [section, setSection] = useState<Section>("overview");
  const [tables, setTables] = useState<SqliteTableInfo[] | null>(null);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [tableDetail, setTableDetail] = useState<SqliteTableDetail | null>(null);
  const [rowsPage, setRowsPage] = useState<SqliteRowsPage | null>(null);
  const [rowOffset, setRowOffset] = useState(0);
  const [rowSearch, setRowSearch] = useState("");
  const [pageSize, setPageSize] = useState(50);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [readSql, setReadSql] = useState("SELECT name FROM sqlite_master WHERE type='table' LIMIT 20");
  const [writeSql, setWriteSql] = useState("");
  const [confirmDomain, setConfirmDomain] = useState("");
  const [queryResult, setQueryResult] = useState<string>("");
  const [mutateResult, setMutateResult] = useState<string>("");

  const [integrityResult, setIntegrityResult] = useState<SqliteIntegrityResult | null>(null);
  const [ownershipAudit, setOwnershipAudit] = useState<SqliteOwnershipAudit | null>(null);
  const [runtime, setRuntime] = useState<SqliteRuntimeStatus | null>(null);

  const [editIdentity, setEditIdentity] = useState<Record<string, unknown> | null>(null);
  const [editDraft, setEditDraft] = useState<Record<string, string>>({});
  const [insertDraft, setInsertDraft] = useState<Record<string, string>>({});

  const selectedDb = useMemo(
    () => databases?.find((db) => db.domain === domain) ?? null,
    [databases, domain],
  );

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

  const clearDomainLocalState = useCallback(() => {
    setSelectedTable(null);
    setTableDetail(null);
    setRowsPage(null);
    setRowOffset(0);
    setRowSearch("");
    setQueryResult("");
    setMutateResult("");
    setIntegrityResult(null);
    setEditIdentity(null);
    setEditDraft({});
    setInsertDraft({});
    setConfirmDomain("");
  }, []);

  const switchDomain = useCallback(
    (next: Domain) => {
      if (next === domain) return;
      setDomain(next);
      clearDomainLocalState();
    },
    [clearDomainLocalState, domain],
  );

  const loadTables = useCallback(async (selected: string) => {
    setTables(null);
    try {
      const payload = await api.sqliteDatabaseTables(selected);
      setTables(payload.tables);
    } catch (err) {
      setTables([]);
      setError(err instanceof ApiError ? err.message : `Failed to list tables for ${selected}`);
    }
  }, []);

  const loadTableDetail = useCallback(async (selectedDomain: string, table: string) => {
    try {
      const payload = await api.sqliteTableDetail(selectedDomain, table);
      setTableDetail(payload.table);
    } catch (err) {
      setTableDetail(null);
      setError(err instanceof ApiError ? err.message : `Failed to load table ${table}`);
    }
  }, []);

  const loadRows = useCallback(
    async (selectedDomain: string, table: string, offset: number, limit: number, search: string) => {
      try {
        const page = await api.sqliteQueryRows(selectedDomain, table, {
          offset,
          limit,
          search: search.trim() || undefined,
          orderBy: undefined,
        });
        setRowsPage(page);
      } catch (err) {
        setRowsPage(null);
        setError(err instanceof ApiError ? err.message : `Failed to load rows for ${table}`);
      }
    },
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadTables(domain);
  }, [domain, loadTables]);

  useEffect(() => {
    if (!selectedTable) {
      setTableDetail(null);
      setRowsPage(null);
      return;
    }
    void loadTableDetail(domain, selectedTable);
    void loadRows(domain, selectedTable, rowOffset, pageSize, rowSearch);
  }, [domain, selectedTable, rowOffset, pageSize, rowSearch, loadTableDetail, loadRows]);

  async function runReadQuery() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.sqliteQuery(domain, readSql, 50);
      setQueryResult(JSON.stringify(result, null, 2));
    } catch (err) {
      setQueryResult("");
      setError(err instanceof ApiError ? err.message : "Query failed");
    } finally {
      setBusy(false);
    }
  }

  async function runWriteMutation() {
    if (confirmDomain.trim().toUpperCase() !== domain) {
      setError(`Type ${domain} in the confirm field to authorize this write.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.sqliteMutate(domain, confirmDomain.trim().toUpperCase(), writeSql);
      setMutateResult(JSON.stringify(result, null, 2));
      if (selectedTable) {
        await loadRows(domain, selectedTable, rowOffset, pageSize, rowSearch);
      }
      await loadTables(domain);
      await load();
    } catch (err) {
      setMutateResult("");
      setError(err instanceof ApiError ? err.message : "Mutation failed");
    } finally {
      setBusy(false);
    }
  }

  async function runIntegrity(kind: "quick_check" | "integrity_check" | "foreign_key_check") {
    setBusy(true);
    setError(null);
    try {
      const result = await api.sqliteIntegrity(domain, kind);
      setIntegrityResult(result);
    } catch (err) {
      setIntegrityResult(null);
      setError(err instanceof ApiError ? err.message : "Integrity check failed");
    } finally {
      setBusy(false);
    }
  }

  async function runOwnershipAudit() {
    setBusy(true);
    setError(null);
    try {
      setOwnershipAudit(await api.sqliteOwnershipAudit());
    } catch (err) {
      setOwnershipAudit(null);
      setError(err instanceof ApiError ? err.message : "Ownership audit failed");
    } finally {
      setBusy(false);
    }
  }

  async function loadRuntime() {
    setBusy(true);
    setError(null);
    try {
      setRuntime(await api.sqliteRuntime());
    } catch (err) {
      setRuntime(null);
      setError(err instanceof ApiError ? err.message : "Runtime status failed");
    } finally {
      setBusy(false);
    }
  }

  async function runCheckpoint() {
    if (confirmDomain.trim().toUpperCase() !== domain) {
      setError(`Type ${domain} to authorize WAL checkpoint.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.sqliteWalCheckpoint(domain, domain, "PASSIVE");
      setMutateResult(JSON.stringify(result, null, 2));
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Checkpoint failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveRowEdit() {
    if (!selectedTable || !editIdentity || !tableDetail?.rowEditAvailable) return;
    if (confirmDomain.trim().toUpperCase() !== domain) {
      setError(`Type ${domain} to authorize row edit.`);
      return;
    }
    const values: Record<string, unknown> = {};
    for (const [key, raw] of Object.entries(editDraft)) {
      if (tableDetail.primaryKey.includes(key)) continue;
      values[key] = raw === "" ? null : raw;
    }
    setBusy(true);
    setError(null);
    try {
      await api.sqliteUpdateRow(domain, domain, selectedTable, editIdentity, values);
      setEditIdentity(null);
      setEditDraft({});
      await loadRows(domain, selectedTable, rowOffset, pageSize, rowSearch);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Row update failed");
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelectedRow() {
    if (!selectedTable || !editIdentity || !tableDetail?.rowEditAvailable) return;
    if (confirmDomain.trim().toUpperCase() !== domain) {
      setError(`Type ${domain} to authorize row delete.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.sqliteDeleteRow(domain, domain, selectedTable, editIdentity);
      setEditIdentity(null);
      setEditDraft({});
      await loadRows(domain, selectedTable, rowOffset, pageSize, rowSearch);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Row delete failed");
    } finally {
      setBusy(false);
    }
  }

  async function insertRow() {
    if (!selectedTable || !tableDetail) return;
    if (confirmDomain.trim().toUpperCase() !== domain) {
      setError(`Type ${domain} to authorize row insert.`);
      return;
    }
    const values: Record<string, unknown> = {};
    for (const [key, raw] of Object.entries(insertDraft)) {
      if (raw === "") continue;
      values[key] = raw;
    }
    setBusy(true);
    setError(null);
    try {
      await api.sqliteInsertRow(domain, domain, selectedTable, values);
      setInsertDraft({});
      await loadRows(domain, selectedTable, 0, pageSize, rowSearch);
      setRowOffset(0);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Row insert failed");
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
    <section aria-label="SQLite Manager" className="lv-sqlite-manager" style={{ display: "grid", gap: "0.85rem" }}>
      <header>
        <h3 style={{ margin: 0 }}>SQLite Manager</h3>
        <p className="lv-muted" style={{ margin: "0.25rem 0 0" }}>
          Operator control plane over CONTROL / KNOWLEDGE / MARKET. Reads are hardened; writes require explicit domain confirmation.
        </p>
      </header>

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }} role="tablist" aria-label="Database domain">
        {DOMAINS.map((item) => {
          const db = databases.find((d) => d.domain === item);
          const pressed = domain === item;
          return (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={pressed}
              aria-pressed={pressed}
              onClick={() => switchDomain(item)}
              style={{
                fontWeight: pressed ? 700 : 500,
                outline: pressed ? "2px solid currentColor" : undefined,
                outlineOffset: 2,
              }}
            >
              {item}
              {db?.exists ? ` · v${db.schemaVersion}` : " · missing"}
            </button>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }} role="tablist" aria-label="Manager section">
        {(
          [
            ["overview", "Overview"],
            ["explorer", "Explorer"],
            ["sql", "SQL Console"],
            ["integrity", "Integrity"],
            ["runtime", "Runtime"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={section === id}
            onClick={() => setSection(id)}
          >
            {label}
          </button>
        ))}
        <button type="button" onClick={() => void load()} disabled={busy}>
          Refresh
        </button>
      </div>

      {error ? (
        <p role="alert" style={{ color: "#b00020", margin: 0 }}>
          {error}
        </p>
      ) : null}

      {section === "overview" ? (
        <div style={{ display: "grid", gap: "0.75rem" }}>
          <p className="lv-muted" style={{ margin: 0 }}>
            Selected: <strong>{domain}</strong>
            {selectedDb?.ownershipDescription ? ` — ${selectedDb.ownershipDescription}` : ""}
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  {[
                    "Domain",
                    "Health",
                    "Path",
                    "Size",
                    "WAL",
                    "SHM",
                    "Schema",
                    "Tables",
                    "Journal",
                  ].map((h) => (
                    <th key={h} style={{ textAlign: "left", padding: "0.35rem", borderBottom: "1px solid #4444" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {databases.map((db) => (
                  <tr
                    key={db.domain}
                    style={{
                      background: db.domain === domain ? "rgba(0,0,0,0.06)" : undefined,
                      fontWeight: db.domain === domain ? 600 : 400,
                    }}
                  >
                    <td style={{ padding: "0.35rem" }}>{db.domain}{db.domain === domain ? " ←" : ""}</td>
                    <td style={{ padding: "0.35rem" }}>{db.health ?? "UNMEASURED"} / {db.readiness ?? "UNMEASURED"}</td>
                    <td style={{ padding: "0.35rem", fontFamily: "monospace", fontSize: 11 }}>{db.path}</td>
                    <td style={{ padding: "0.35rem" }}>{db.exists ? formatBytes(db.sizeBytes) : "missing"}</td>
                    <td style={{ padding: "0.35rem" }}>
                      {db.walExists ? formatBytes(db.walSizeBytes) : "—"}
                    </td>
                    <td style={{ padding: "0.35rem" }}>{db.shmExists ? "yes" : "—"}</td>
                    <td style={{ padding: "0.35rem" }}>{db.schemaVersion}</td>
                    <td style={{ padding: "0.35rem" }}>{db.tableCount ?? "UNMEASURED"}</td>
                    <td style={{ padding: "0.35rem" }}>{db.journalMode ?? "UNMEASURED"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {section === "explorer" ? (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(180px, 240px) 1fr", gap: "0.75rem" }}>
          <div>
            <h4 style={{ margin: "0 0 0.35rem" }}>Tables ({domain})</h4>
            {tables == null ? (
              <p className="lv-muted">Loading tables…</p>
            ) : tables.length === 0 ? (
              <p className="lv-muted">No tables in {domain}.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0, maxHeight: 420, overflow: "auto" }}>
                {tables.map((t) => (
                  <li key={t.name}>
                    <button
                      type="button"
                      aria-pressed={selectedTable === t.name}
                      onClick={() => {
                        setSelectedTable(t.name);
                        setRowOffset(0);
                        setEditIdentity(null);
                      }}
                      style={{
                        width: "100%",
                        textAlign: "left",
                        fontWeight: selectedTable === t.name ? 700 : 400,
                        fontSize: 12,
                      }}
                    >
                      {t.name}
                      <span className="lv-muted"> · {t.ownershipState ?? "?"}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div style={{ display: "grid", gap: "0.65rem", minWidth: 0 }}>
            {!selectedTable ? (
              <p className="lv-muted">Select a table to inspect schema and browse rows.</p>
            ) : (
              <>
                {tableDetail ? (
                  <div>
                    <h4 style={{ margin: "0 0 0.35rem" }}>
                      {tableDetail.name}{" "}
                      <span className="lv-muted">
                        ({tableDetail.type}
                        {tableDetail.isVirtual ? ", virtual" : ""} · owner{" "}
                        {tableDetail.owningDomain ?? "n/a"} · {tableDetail.ownershipState})
                      </span>
                    </h4>
                    <p className="lv-muted" style={{ margin: 0, fontSize: 12 }}>
                      PK: {tableDetail.primaryKey.length ? tableDetail.primaryKey.join(", ") : "none"} · row count:{" "}
                      {tableDetail.rowCountState === "ESTIMATED"
                        ? `~${tableDetail.rowCount} (estimated)`
                        : tableDetail.rowCountState ?? "UNMEASURED"}
                      {!tableDetail.rowEditAvailable ? " · ROW_EDIT_UNAVAILABLE" : ""}
                    </p>
                    <div style={{ overflowX: "auto", marginTop: "0.4rem" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                        <thead>
                          <tr>
                            {["Column", "Type", "Null", "PK"].map((h) => (
                              <th key={h} style={{ textAlign: "left", padding: "0.25rem", borderBottom: "1px solid #4444" }}>
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {tableDetail.columns.map((c) => (
                            <tr key={c.name}>
                              <td style={{ padding: "0.25rem" }}>{c.name}</td>
                              <td style={{ padding: "0.25rem" }}>{c.type || "—"}</td>
                              <td style={{ padding: "0.25rem" }}>{c.notnull ? "NOT NULL" : "NULL"}</td>
                              <td style={{ padding: "0.25rem" }}>{c.pk || ""}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {tableDetail.indexes.length ? (
                      <p className="lv-muted" style={{ fontSize: 12, margin: "0.35rem 0 0" }}>
                        Indexes:{" "}
                        {tableDetail.indexes
                          .map((i) => `${i.name}${i.unique ? " (unique)" : ""}`)
                          .join(", ")}
                      </p>
                    ) : null}
                  </div>
                ) : (
                  <p className="lv-muted">Loading schema…</p>
                )}

                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                  <label>
                    Search{" "}
                    <input
                      value={rowSearch}
                      onChange={(e) => {
                        setRowOffset(0);
                        setRowSearch(e.target.value);
                      }}
                    />
                  </label>
                  <label>
                    Page size{" "}
                    <select
                      value={pageSize}
                      onChange={(e) => {
                        setRowOffset(0);
                        setPageSize(Number(e.target.value));
                      }}
                    >
                      {[25, 50, 100, 200].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={rowOffset <= 0 || busy}
                    onClick={() => setRowOffset(Math.max(0, rowOffset - pageSize))}
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    disabled={!rowsPage?.truncated || busy}
                    onClick={() => setRowOffset(rowOffset + pageSize)}
                  >
                    Next
                  </button>
                  <span className="lv-muted" style={{ fontSize: 12 }}>
                    offset {rowOffset}
                    {rowsPage ? ` · ${rowsPage.rowCount} rows` : ""}
                    {rowsPage?.truncated ? " · truncated" : ""}
                  </span>
                </div>

                {rowsPage ? (
                  <div style={{ overflow: "auto", maxHeight: 320 }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <thead>
                        <tr>
                          {rowsPage.columns.map((c) => (
                            <th key={c} style={{ textAlign: "left", padding: "0.25rem", borderBottom: "1px solid #4444" }}>
                              {c}
                            </th>
                          ))}
                          <th style={{ padding: "0.25rem" }} />
                        </tr>
                      </thead>
                      <tbody>
                        {rowsPage.rows.map((row, idx) => (
                          <tr key={idx}>
                            {rowsPage.columns.map((c) => (
                              <td
                                key={c}
                                style={{ padding: "0.25rem", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis" }}
                                title={cellDisplay(row.values[c])}
                                onDoubleClick={() => {
                                  void navigator.clipboard?.writeText(cellDisplay(row.values[c]));
                                }}
                              >
                                {cellDisplay(row.values[c])}
                              </td>
                            ))}
                            <td style={{ padding: "0.25rem" }}>
                              {rowsPage.rowEditAvailable && row.identity ? (
                                <button
                                  type="button"
                                  onClick={() => {
                                    setEditIdentity(row.identity);
                                    const draft: Record<string, string> = {};
                                    for (const c of rowsPage.columns) {
                                      const cell = row.values[c];
                                      draft[c] =
                                        !cell || cell.kind === "null" ? "" : String(cell.value ?? "");
                                    }
                                    setEditDraft(draft);
                                  }}
                                >
                                  Edit
                                </button>
                              ) : null}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="lv-muted">No row page loaded.</p>
                )}

                {editIdentity && tableDetail?.rowEditAvailable ? (
                  <div style={{ display: "grid", gap: "0.35rem", borderTop: "1px solid #4444", paddingTop: "0.5rem" }}>
                    <strong>Edit row (parameterized)</strong>
                    {Object.keys(editDraft).map((col) => (
                      <label key={col} style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "0.35rem" }}>
                        <span>{col}</span>
                        <input
                          value={editDraft[col] ?? ""}
                          disabled={tableDetail.primaryKey.includes(col)}
                          onChange={(e) => setEditDraft((d) => ({ ...d, [col]: e.target.value }))}
                        />
                      </label>
                    ))}
                    <label>
                      Confirm domain{" "}
                      <input
                        value={confirmDomain}
                        placeholder={domain}
                        onChange={(e) => setConfirmDomain(e.target.value)}
                      />
                    </label>
                    <div style={{ display: "flex", gap: "0.4rem" }}>
                      <button type="button" disabled={busy} onClick={() => void saveRowEdit()}>
                        Save
                      </button>
                      <button type="button" disabled={busy} onClick={() => void deleteSelectedRow()}>
                        Delete
                      </button>
                      <button type="button" onClick={() => { setEditIdentity(null); setEditDraft({}); }}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : null}

                {tableDetail && !tableDetail.isVirtual && tableDetail.type === "table" ? (
                  <details>
                    <summary>Insert row into {selectedTable}</summary>
                    <div style={{ display: "grid", gap: "0.35rem", marginTop: "0.4rem" }}>
                      {tableDetail.columns.map((c) => (
                        <label key={c.name} style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "0.35rem" }}>
                          <span>{c.name}</span>
                          <input
                            value={insertDraft[c.name] ?? ""}
                            onChange={(e) => setInsertDraft((d) => ({ ...d, [c.name]: e.target.value }))}
                          />
                        </label>
                      ))}
                      <label>
                        Confirm domain{" "}
                        <input
                          value={confirmDomain}
                          placeholder={domain}
                          onChange={(e) => setConfirmDomain(e.target.value)}
                        />
                      </label>
                      <button type="button" disabled={busy} onClick={() => void insertRow()}>
                        Insert
                      </button>
                    </div>
                  </details>
                ) : null}
              </>
            )}
          </div>
        </div>
      ) : null}

      {section === "sql" ? (
        <div style={{ display: "grid", gap: "0.85rem" }}>
          <div style={{ display: "grid", gap: "0.4rem" }}>
            <h4 style={{ margin: 0 }}>Read query — {domain}</h4>
            <p className="lv-muted" style={{ margin: 0, fontSize: 12 }}>
              SELECT / WITH…SELECT / safe PRAGMA only. Results are bounded by the backend.
            </p>
            <textarea value={readSql} onChange={(e) => setReadSql(e.target.value)} rows={4} />
            <button type="button" disabled={busy} onClick={() => void runReadQuery()}>
              {busy ? "Running…" : "Run read"}
            </button>
            {queryResult ? (
              <pre style={{ maxHeight: 240, overflow: "auto", fontSize: 12, margin: 0 }}>{queryResult}</pre>
            ) : null}
          </div>
          <div style={{ display: "grid", gap: "0.4rem", borderTop: "1px solid #4444", paddingTop: "0.75rem" }}>
            <h4 style={{ margin: 0 }}>Controlled write — {domain}</h4>
            <p className="lv-muted" style={{ margin: 0, fontSize: 12 }}>
              INSERT / UPDATE / DELETE only. No schema DDL. Requires confirmDomain = {domain}. Write class: CONTROL_WRITE.
            </p>
            <textarea value={writeSql} onChange={(e) => setWriteSql(e.target.value)} rows={3} />
            <label>
              Confirm domain{" "}
              <input
                value={confirmDomain}
                placeholder={domain}
                onChange={(e) => setConfirmDomain(e.target.value)}
              />
            </label>
            <button type="button" disabled={busy} onClick={() => void runWriteMutation()}>
              {busy ? "Running…" : "Execute mutation"}
            </button>
            {mutateResult ? (
              <pre style={{ maxHeight: 160, overflow: "auto", fontSize: 12, margin: 0 }}>{mutateResult}</pre>
            ) : null}
          </div>
        </div>
      ) : null}

      {section === "integrity" ? (
        <div style={{ display: "grid", gap: "0.65rem" }}>
          <h4 style={{ margin: 0 }}>Integrity — {domain}</h4>
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
            <button type="button" disabled={busy} onClick={() => void runIntegrity("quick_check")}>
              quick_check
            </button>
            <button type="button" disabled={busy} onClick={() => void runIntegrity("integrity_check")}>
              integrity_check
            </button>
            <button type="button" disabled={busy} onClick={() => void runIntegrity("foreign_key_check")}>
              foreign_key_check
            </button>
            <button type="button" disabled={busy} onClick={() => void runOwnershipAudit()}>
              Ownership audit (all DBs)
            </button>
          </div>
          {integrityResult ? (
            <pre style={{ maxHeight: 200, overflow: "auto", fontSize: 12, margin: 0 }}>
              {JSON.stringify(integrityResult, null, 2)}
            </pre>
          ) : null}
          {ownershipAudit ? (
            <div>
              <p style={{ margin: 0 }}>
                Audit ok: <strong>{String(ownershipAudit.ok)}</strong> · findings: {ownershipAudit.findings.length}
              </p>
              <pre style={{ maxHeight: 260, overflow: "auto", fontSize: 12, margin: "0.35rem 0 0" }}>
                {JSON.stringify(ownershipAudit, null, 2)}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}

      {section === "runtime" ? (
        <div style={{ display: "grid", gap: "0.65rem" }}>
          <h4 style={{ margin: 0 }}>Runtime</h4>
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
            <button type="button" disabled={busy} onClick={() => void loadRuntime()}>
              Refresh runtime
            </button>
            <label>
              Confirm domain for checkpoint{" "}
              <input
                value={confirmDomain}
                placeholder={domain}
                onChange={(e) => setConfirmDomain(e.target.value)}
              />
            </label>
            <button type="button" disabled={busy} onClick={() => void runCheckpoint()}>
              WAL checkpoint PASSIVE ({domain})
            </button>
          </div>
          {runtime ? (
            <pre style={{ maxHeight: 360, overflow: "auto", fontSize: 12, margin: 0 }}>
              {JSON.stringify(runtime, null, 2)}
            </pre>
          ) : (
            <p className="lv-muted">Load runtime to inspect WAL/contention/DB Commit/backup truth.</p>
          )}
        </div>
      ) : null}
    </section>
  );
}

/** Pure helpers exported for contract tests. */
export function sqliteManagerClearsOnDomainSwitch(prevDomain: string, nextDomain: string): boolean {
  return prevDomain !== nextDomain;
}

export function sqliteManagerWriteConfirmOk(selected: string, typed: string): boolean {
  return typed.trim().toUpperCase() === selected.toUpperCase();
}
