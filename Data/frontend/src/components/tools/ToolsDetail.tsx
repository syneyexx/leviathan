import { Button, Badge } from "../ui";
import type { ToolsCapabilityDetail, ToolsLibraryItem } from "../../types/api";
import type { ToolsDetailTab } from "../../pages/tools/useToolsWorkspace";
import { CapabilitySchemaForm } from "./CapabilitySchemaForm";

type Props = {
  selected: ToolsLibraryItem | null;
  detail: ToolsCapabilityDetail | null;
  loading?: boolean;
  tab: ToolsDetailTab;
  onTab: (t: ToolsDetailTab) => void;
  testArgs: Record<string, unknown>;
  onTestArgs: (v: Record<string, unknown>) => void;
  onTest: () => void;
  onEdit: () => void;
  testing?: boolean;
  testResult?: string | null;
};

const TABS: Array<{ id: ToolsDetailTab; label: string }> = [
  { id: "overview", label: "Overzicht" },
  { id: "parameters", label: "Parameters" },
  { id: "schema", label: "Schema" },
  { id: "example", label: "Voorbeeld" },
  { id: "logs", label: "Logs" },
  { id: "dependencies", label: "Afhankelijkheden" },
];

function schemaParams(detail: ToolsCapabilityDetail | null) {
  const schema = detail?.capability.input_schema;
  const props = (schema?.properties ?? {}) as Record<
    string,
    { type?: string; description?: string; default?: unknown; enum?: unknown[] }
  >;
  const required = new Set((schema?.required as string[] | undefined) ?? []);
  return Object.entries(props).map(([name, spec]) => ({
    name,
    type: Array.isArray(spec.enum) ? "enum" : String(spec.type ?? "any"),
    required: required.has(name),
    description: String(spec.description ?? ""),
    default: spec.default,
  }));
}

function formatMs(ms?: number | null): string {
  if (ms == null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

export function ToolsDetail({
  selected,
  detail,
  loading,
  tab,
  onTab,
  testArgs,
  onTestArgs,
  onTest,
  onEdit,
  testing,
  testResult,
}: Props) {
  if (!selected) {
    return (
      <section className="lv-v2-tools-detail" aria-label="Tool Details">
        <p className="lv-muted">Selecteer een tool om details te bekijken.</p>
      </section>
    );
  }

  const cap = detail?.capability;
  const usage = detail?.usage;
  const params = schemaParams(detail);
  const tags = [
    selected.category_label,
    selected.source_label,
    selected.version,
    cap?.execution_class,
  ].filter(Boolean) as string[];

  const testBlocked = detail?.testability?.allowed === false;
  const editBlocked = detail?.editability?.editable === false;

  return (
    <section className="lv-v2-tools-detail" aria-label="Tool Details">
      <header className="lv-v2-tools-detail__head">
        <div>
          <div className="lv-v2-tools-detail__title">
            <h3>{selected.name}</h3>
            <Badge tone={selected.status === "active" ? "success" : "danger"}>
              {selected.status_label ?? "—"}
            </Badge>
          </div>
          <p className="lv-muted">{cap?.description || selected.description || "—"}</p>
          <div className="lv-v2-tools-tags">
            {tags.map((t) => (
              <span key={t} className="lv-v2-tools-chip">
                {t}
              </span>
            ))}
          </div>
        </div>
        <div className="lv-v2-tools-detail__actions">
          <Button
            variant="secondary"
            size="sm"
            disabled={testBlocked || testing}
            title={detail?.testability?.reason ?? undefined}
            onClick={onTest}
          >
            {testing ? "Testen…" : "Testen"}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={editBlocked}
            title={detail?.editability?.reason ?? undefined}
            onClick={onEdit}
          >
            Bewerken
          </Button>
        </div>
      </header>

      <div className="lv-v2-tools-tabs" role="tablist" aria-label="Tool detail tabs">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? "is-active" : undefined}
            onClick={() => onTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="lv-v2-tools-detail__body" role="tabpanel">
        {loading && !detail ? <p className="lv-muted">Detail laden…</p> : null}

        {tab === "overview" ? (
          <div className="lv-v2-tools-overview">
            <div className="lv-v2-tools-overview__main">
              <h4>Beschrijving</h4>
              <p>{cap?.description || selected.description || "—"}</p>
              <p className="lv-muted">
                id: {selected.id}
                {cap?.provider_kind ? ` · ${cap.provider_kind}` : ""}
                {cap?.provider_ref ? `:${cap.provider_ref}` : ""}
                {cap?.execution_class ? ` · ${cap.execution_class}` : ""}
              </p>
              <h4>Parameters</h4>
              <table className="lv-v2-tools-mini-table">
                <thead>
                  <tr>
                    <th>Naam</th>
                    <th>Type</th>
                    <th>Beschrijving</th>
                  </tr>
                </thead>
                <tbody>
                  {params.length === 0 ? (
                    <tr>
                      <td colSpan={3}>Geen parameters.</td>
                    </tr>
                  ) : (
                    params.map((p) => (
                      <tr key={p.name}>
                        <td>
                          {p.name}
                          {p.required ? " *" : ""}
                        </td>
                        <td>{p.type}</td>
                        <td>{p.description || "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <aside className="lv-v2-tools-overview__side">
              <div className="lv-v2-tools-statbox">
                <h4>Gebruiksstatistieken</h4>
                <dl>
                  <div>
                    <dt>Total calls</dt>
                    <dd>{usage?.total_calls ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Success</dt>
                    <dd>{usage?.completed ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Failed</dt>
                    <dd>{usage?.failed ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Avg response</dt>
                    <dd>{formatMs(usage?.avg_latency_ms)}</dd>
                  </div>
                </dl>
              </div>
              <div className="lv-v2-tools-statbox">
                <h4>Providers</h4>
                <ul className="lv-v2-tools-provider-list">
                  {(detail?.providers ?? []).length === 0 ? <li className="lv-muted">Geen providerdata.</li> : null}
                  {(detail?.providers ?? []).map((p) => (
                    <li key={String(p.name)}>
                      <span className={`lv-v2-tools-status ${p.state === "available" || p.state === "measured" ? "is-active" : "is-unavailable"}`}>
                        <i />
                      </span>
                      <strong>{p.name}</strong>
                      <span className="lv-muted">{p.calls != null ? `${p.calls} calls` : "—"}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </aside>
          </div>
        ) : null}

        {tab === "parameters" ? (
          <div className="lv-v2-tools-params">
            <CapabilitySchemaForm
              schema={cap?.input_schema}
              value={testArgs}
              onChange={onTestArgs}
            />
            {testResult ? (
              <pre className="lv-v2-tools-code">{testResult}</pre>
            ) : null}
          </div>
        ) : null}

        {tab === "schema" ? (
          <div className="lv-v2-tools-schema">
            <div className="lv-v2-tools-schema__meta">
              <span>schema hash: {cap?.schema_hash ?? "—"}</span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  void navigator.clipboard.writeText(
                    JSON.stringify(
                      { input_schema: cap?.input_schema, output_schema: cap?.output_schema },
                      null,
                      2,
                    ),
                  )
                }
              >
                Kopieer
              </Button>
            </div>
            <h4>Input Schema</h4>
            <pre className="lv-v2-tools-code">{JSON.stringify(cap?.input_schema ?? {}, null, 2)}</pre>
            <h4>Output Schema</h4>
            <pre className="lv-v2-tools-code">{JSON.stringify(cap?.output_schema ?? {}, null, 2)}</pre>
          </div>
        ) : null}

        {tab === "example" ? (
          <div className="lv-v2-tools-example">
            <p className="lv-muted">{detail?.examples?.label ?? "Geen voorbeeld"}</p>
            <pre className="lv-v2-tools-code">
              {JSON.stringify(detail?.examples?.examples ?? [], null, 2)}
            </pre>
          </div>
        ) : null}

        {tab === "logs" ? (
          <div className="lv-v2-tools-logs">
            <table className="lv-v2-tools-mini-table">
              <thead>
                <tr>
                  <th>Tijd</th>
                  <th>Status</th>
                  <th>Duur</th>
                  <th>Caller</th>
                  <th>Request</th>
                </tr>
              </thead>
              <tbody>
                {(detail?.recent_receipts ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={5}>Nog geen tool-aanroepen.</td>
                  </tr>
                ) : (
                  (detail?.recent_receipts ?? []).map((row) => (
                    <tr key={row.receipt_id ?? `${row.request_id}-${row.recorded_at}`}>
                      <td>{row.recorded_at ?? "—"}</td>
                      <td>{row.status_label ?? row.status}</td>
                      <td>{formatMs(row.latency_ms)}</td>
                      <td>{row.requested_by ?? "—"}</td>
                      <td title={row.request_id ?? undefined}>
                        {(row.request_id ?? "—").slice(0, 8)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        ) : null}

        {tab === "dependencies" ? (
          <div className="lv-v2-tools-deps">
            <ul>
              {(detail?.dependencies?.items ?? []).map((item, idx) => (
                <li key={idx}>
                  <strong>{String(item.label ?? item.kind)}:</strong>{" "}
                  {typeof item.value === "string" || typeof item.value === "number"
                    ? String(item.value)
                    : JSON.stringify(item.value)}
                  {item.version ? ` (v${String(item.version)})` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}
