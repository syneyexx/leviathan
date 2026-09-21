import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { StatusBadge, type StatusTone } from "@/components/hades/ui";

export function toneForStatus(status: string | undefined | null): StatusTone {
  switch ((status || "").toLowerCase()) {
    case "completed":
    case "succeeded":
    case "pass":
    case "validated":
    case "paper":
    case "confirmed":
    case "supported":
    case "implemented":
      return "success";
    case "failed":
    case "cancelled":
    case "fail":
    case "refused":
    case "contradicted":
    case "rejected":
    case "blocked_missing_data":
    case "not_supported":
      return "danger";
    case "running":
    case "queued":
    case "paused":
    case "proposed":
    case "tested":
      return "info";
    case "insufficient_evidence":
    case "draft":
    case "researched":
    case "unavailable":
    case "weakened":
    case "retired":
    case "superseded":
    case "reused":
    case "implemented_needs_data":
      return "warning";
    default:
      return "neutral";
  }
}

export function num(value: unknown, digits = 2): string {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return parsed.toLocaleString("nl-NL", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(value: unknown, digits = 2): string {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return `${(parsed * 100).toFixed(digits)}%`;
}

export function shortTime(value: unknown): string {
  if (!value) return "—";
  const text = String(value);
  return text.length > 19 ? text.slice(0, 19).replace("T", " ") : text.replace("T", " ");
}

export function text(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

/** Reads a nested value without throwing on the loosely typed API payloads. */
export function pick(source: unknown, path: string): unknown {
  let cursor: unknown = source;
  for (const key of path.split(".")) {
    if (cursor === null || typeof cursor !== "object") return undefined;
    cursor = (cursor as Record<string, unknown>)[key];
  }
  return cursor;
}

export function LabEmpty({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="lab-empty">
      <strong>{title}</strong>
      <span>{hint}</span>
    </div>
  );
}

export function LabStats({ items }: { items: Array<{ label: string; value: string; note?: string }> }) {
  return (
    <div className="lab-stat-grid">
      {items.map((item) => (
        <div key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
          {item.note ? <small>{item.note}</small> : null}
        </div>
      ))}
    </div>
  );
}

export function LabKeyValues({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className="lab-kv">
      {rows.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function LabTable<T>({
  columns,
  rows,
  keyOf,
  empty,
}: {
  columns: Array<{ header: string; cell: (row: T) => ReactNode; align?: "right" }>;
  rows: T[];
  keyOf: (row: T, index: number) => string;
  empty: ReactNode;
}) {
  if (rows.length === 0) return <>{empty}</>;
  return (
    <div className="lab-table-wrap">
      <table className="lab-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.header} className={column.align === "right" ? "is-right" : undefined}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={keyOf(row, index)}>
              {columns.map((column) => (
                <td key={column.header} className={column.align === "right" ? "is-right" : undefined}>
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LabStatus({ value }: { value: string | undefined | null }) {
  return <StatusBadge tone={toneForStatus(value)}>{text(value, "onbekend")}</StatusBadge>;
}

export function LabNotice({ tone = "info", children }: { tone?: "info" | "warning" | "danger"; children: ReactNode }) {
  return <div className={`lab-notice lab-notice--${tone}`}>{children}</div>;
}

export function LabJson({ value, label }: { value: unknown; label?: string }) {
  if (value === null || value === undefined) return null;
  return (
    <details className="lab-json">
      <summary>{label || "Ruwe respons"}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export function LabField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="lab-field">
      <span>{label}</span>
      {children}
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}

/** Small async data hook: keeps one in-flight request, reports failures honestly. */
export function useLabResource<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await loaderRef.current());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}

export async function runAction<T>(
  action: () => Promise<T>,
  options: { busy: (value: boolean) => void; success?: (result: T) => string | null; failure: string },
): Promise<T | null> {
  options.busy(true);
  try {
    const result = await action();
    const message = options.success ? options.success(result) : null;
    if (message) toast.success(message);
    return result;
  } catch (reason) {
    toast.error(reason instanceof Error ? reason.message : options.failure);
    return null;
  } finally {
    options.busy(false);
  }
}

/** Refusals travel as `{started:false, reason}` / `{created:false, reason}` rather than as exceptions. */
export function refusalOf(result: Record<string, unknown> | null): string | null {
  if (!result) return null;
  const refused = result.started === false || result.created === false || result.promoted === false || result.ok === false || result.branched === false;
  if (!refused) return null;
  return typeof result.reason === "string" ? result.reason : "geweigerd zonder opgegeven reden";
}
