/**
 * Lightweight JSON-schema form for capability test invocation.
 * Unknown constructs fall back to raw JSON.
 */

import { useMemo, useState } from "react";

type Props = {
  schema?: Record<string, unknown>;
  value: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
};

function isObjectSchema(schema?: Record<string, unknown>): boolean {
  if (!schema) return false;
  if (schema.type === "object") return true;
  return Boolean(schema.properties && typeof schema.properties === "object");
}

export function CapabilitySchemaForm({ schema, value, onChange }: Props) {
  const [advanced, setAdvanced] = useState(false);
  const [raw, setRaw] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [rawError, setRawError] = useState<string | null>(null);

  const properties = useMemo(() => {
    const props = (schema?.properties ?? {}) as Record<string, Record<string, unknown>>;
    return Object.entries(props);
  }, [schema]);

  const required = useMemo(
    () => new Set(((schema?.required as string[]) ?? []).map(String)),
    [schema],
  );

  if (!isObjectSchema(schema) || advanced) {
    return (
      <div className="lv-v2-schema-form">
        {!isObjectSchema(schema) ? (
          <p className="lv-muted">Onbekend schema-construct — raw JSON editor.</p>
        ) : (
          <button type="button" className="lv-v2-linkish" onClick={() => setAdvanced(false)}>
            Terug naar formuliervelden
          </button>
        )}
        <textarea
          className="lv-v2-input lv-v2-tools-code"
          rows={10}
          value={raw}
          spellCheck={false}
          onChange={(e) => {
            setRaw(e.target.value);
            try {
              const parsed = JSON.parse(e.target.value) as unknown;
              if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
                setRawError("Arguments must be a JSON object");
                return;
              }
              setRawError(null);
              onChange(parsed as Record<string, unknown>);
            } catch {
              setRawError("Invalid JSON");
            }
          }}
          aria-label="Capability arguments JSON"
        />
        {rawError ? (
          <p className="lv-v2-warn" role="alert">
            {rawError}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="lv-v2-schema-form">
      <div className="lv-v2-schema-form__grid">
        {properties.map(([name, spec]) => {
          const type = String(spec.type ?? "string");
          const enums = Array.isArray(spec.enum) ? (spec.enum as unknown[]) : null;
          const current = value[name];
          const label = `${name}${required.has(name) ? " *" : ""}`;
          return (
            <label key={name} className="lv-v2-schema-form__field">
              <span>{label}</span>
              {enums ? (
                <select
                  className="lv-v2-select"
                  value={current == null ? "" : String(current)}
                  onChange={(e) => onChange({ ...value, [name]: e.target.value })}
                >
                  <option value="">—</option>
                  {enums.map((opt) => (
                    <option key={String(opt)} value={String(opt)}>
                      {String(opt)}
                    </option>
                  ))}
                </select>
              ) : type === "boolean" ? (
                <input
                  type="checkbox"
                  checked={Boolean(current)}
                  onChange={(e) => onChange({ ...value, [name]: e.target.checked })}
                />
              ) : type === "integer" || type === "number" ? (
                <input
                  className="lv-v2-input"
                  type="number"
                  value={current == null ? "" : String(current)}
                  min={spec.minimum != null ? Number(spec.minimum) : undefined}
                  max={spec.maximum != null ? Number(spec.maximum) : undefined}
                  onChange={(e) => {
                    const n = e.target.value === "" ? undefined : Number(e.target.value);
                    onChange({ ...value, [name]: n });
                  }}
                />
              ) : (
                <input
                  className="lv-v2-input"
                  type="text"
                  value={current == null ? "" : String(current)}
                  onChange={(e) => onChange({ ...value, [name]: e.target.value })}
                />
              )}
              {spec.description ? <small className="lv-muted">{String(spec.description)}</small> : null}
            </label>
          );
        })}
      </div>
      <button
        type="button"
        className="lv-v2-linkish"
        onClick={() => {
          setRaw(JSON.stringify(value ?? {}, null, 2));
          setAdvanced(true);
        }}
      >
        Geavanceerd JSON
      </button>
    </div>
  );
}
