import { useState } from "react";
import { Dialog } from "../ui";
import { CapabilitySchemaForm } from "./CapabilitySchemaForm";
import type { ToolsCapabilityDetail, ToolsLibraryItem, ToolsRecentCall } from "../../types/api";

type NewToolProps = {
  open: boolean;
  onClose: () => void;
  busy?: boolean;
  wrapCandidates: ToolsLibraryItem[];
  onCreateWrapper: (payload: {
    name: string;
    description?: string;
    wraps_capability_id: string;
    capability_id?: string;
  }) => void;
  onOpenMcp: () => void;
  onOpenModules: () => void;
};

export function ToolsNewToolDialog({
  open,
  onClose,
  busy,
  wrapCandidates,
  onCreateWrapper,
  onOpenMcp,
  onOpenModules,
}: NewToolProps) {
  const [mode, setMode] = useState<"wrapper" | "mcp" | "module">("wrapper");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [wraps, setWraps] = useState(wrapCandidates[0]?.id ?? "");
  const [customId, setCustomId] = useState("");

  return (
    <Dialog
      open={open}
      title="Nieuwe tool"
      description="Alleen veilige, canonieke authorities. Geen arbitrary code execution."
      confirmLabel={mode === "wrapper" ? "Aanmaken" : "Doorgaan"}
      busy={busy}
      onClose={onClose}
      onConfirm={() => {
        if (mode === "mcp") {
          onClose();
          onOpenMcp();
          return;
        }
        if (mode === "module") {
          onClose();
          onOpenModules();
          return;
        }
        if (!name.trim() || !wraps) return;
        onCreateWrapper({
          name: name.trim(),
          description: description.trim() || undefined,
          wraps_capability_id: wraps,
          capability_id: customId.trim() || undefined,
        });
      }}
    >
      <div className="lv-v2-tools-dialog">
        <div className="lv-v2-tools-dialog__modes" role="radiogroup" aria-label="Tool type">
          <label>
            <input type="radio" checked={mode === "wrapper"} onChange={() => setMode("wrapper")} />
            Declaratieve wrapper (bestaande capability)
          </label>
          <label>
            <input type="radio" checked={mode === "mcp"} onChange={() => setMode("mcp")} />
            MCP server toevoegen
          </label>
          <label>
            <input type="radio" checked={mode === "module"} onChange={() => setMode("module")} />
            Module / plugin laden
          </label>
        </div>
        {mode === "wrapper" ? (
          <div className="lv-v2-schema-form__grid">
            <label className="lv-v2-schema-form__field">
              <span>Naam *</span>
              <input className="lv-v2-input" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="lv-v2-schema-form__field">
              <span>Wrapt capability *</span>
              <select className="lv-v2-select" value={wraps} onChange={(e) => setWraps(e.target.value)}>
                {wrapCandidates.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.id})
                  </option>
                ))}
              </select>
            </label>
            <label className="lv-v2-schema-form__field">
              <span>Capability ID (optioneel)</span>
              <input
                className="lv-v2-input"
                value={customId}
                placeholder="custom.my_tool"
                onChange={(e) => setCustomId(e.target.value)}
              />
            </label>
            <label className="lv-v2-schema-form__field">
              <span>Beschrijving</span>
              <textarea
                className="lv-v2-input"
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
          </div>
        ) : (
          <p className="lv-muted">
            {mode === "mcp"
              ? "Opent de canonieke MCP-registratieflow. Tools verschijnen na discovery in CapabilityCatalog."
              : "Opent Runtime & Tools / Modules voor canonieke module/plugin loading."}
          </p>
        )}
      </div>
    </Dialog>
  );
}

type TestProps = {
  open: boolean;
  onClose: () => void;
  detail: ToolsCapabilityDetail | null;
  args: Record<string, unknown>;
  onArgs: (v: Record<string, unknown>) => void;
  onExecute: () => void;
  busy?: boolean;
  result?: string | null;
};

export function ToolsTestDialog({
  open,
  onClose,
  detail,
  args,
  onArgs,
  onExecute,
  busy,
  result,
}: TestProps) {
  const cap = detail?.capability;
  const blocked = detail?.testability?.allowed === false;
  return (
    <Dialog
      open={open}
      title={`Testen — ${cap?.name ?? "tool"}`}
      description={
        blocked
          ? detail?.testability?.reason ?? "Test niet beschikbaar"
          : `Provider ${cap?.provider_kind}:${cap?.provider_ref}. Side effects: ${(cap?.side_effects ?? []).join(", ") || "geen"}.`
      }
      confirmLabel={busy ? "Bezig…" : "Uitvoeren"}
      busy={busy}
      onClose={onClose}
      onConfirm={() => {
        if (!blocked) onExecute();
      }}
    >
      <div className="lv-v2-tools-dialog">
        {blocked ? (
          <p className="lv-v2-warn" role="status">
            {detail?.testability?.reason}
          </p>
        ) : (
          <CapabilitySchemaForm schema={cap?.input_schema} value={args} onChange={onArgs} />
        )}
        {result ? <pre className="lv-v2-tools-code">{result}</pre> : null}
      </div>
    </Dialog>
  );
}

type McpProps = {
  open: boolean;
  onClose: () => void;
  onCreate: (payload: Record<string, unknown>) => void;
};

export function ToolsMcpAddDialog({ open, onClose, onCreate }: McpProps) {
  const [displayName, setDisplayName] = useState("");
  const [transport, setTransport] = useState("stdio");
  const [command, setCommand] = useState("");
  const [url, setUrl] = useState("");

  return (
    <Dialog
      open={open}
      title="MCP Server toevoegen"
      description="Registreert via canonieke MCP store — geen frontend-only rij."
      confirmLabel="Toevoegen"
      onClose={onClose}
      onConfirm={() => {
        onCreate({
          display_name: displayName || undefined,
          transport,
          command: transport === "stdio" ? command : undefined,
          args: [],
          url: transport !== "stdio" ? url : undefined,
          enabled: true,
        });
      }}
    >
      <div className="lv-v2-schema-form__grid">
        <label className="lv-v2-schema-form__field">
          <span>Naam</span>
          <input className="lv-v2-input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </label>
        <label className="lv-v2-schema-form__field">
          <span>Transport</span>
          <select className="lv-v2-select" value={transport} onChange={(e) => setTransport(e.target.value)}>
            <option value="stdio">stdio</option>
            <option value="sse">sse</option>
            <option value="http">http</option>
          </select>
        </label>
        {transport === "stdio" ? (
          <label className="lv-v2-schema-form__field">
            <span>Command</span>
            <input className="lv-v2-input" value={command} onChange={(e) => setCommand(e.target.value)} />
          </label>
        ) : (
          <label className="lv-v2-schema-form__field">
            <span>URL</span>
            <input className="lv-v2-input" value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
        )}
      </div>
    </Dialog>
  );
}

type HistoryProps = {
  open: boolean;
  onClose: () => void;
  calls: ToolsRecentCall[];
};

export function ToolsHistoryDialog({ open, onClose, calls }: HistoryProps) {
  return (
    <Dialog open={open} title="Tool-aanroepgeschiedenis" cancelLabel="Sluiten" onClose={onClose}>
      <div className="lv-v2-tools-table-wrap" style={{ maxHeight: 360, overflow: "auto" }}>
        <table className="lv-v2-tools-table lv-v2-tools-table--compact">
          <thead>
            <tr>
              <th>Tijd</th>
              <th>Tool</th>
              <th>Status</th>
              <th>Duur</th>
              <th>Agent</th>
            </tr>
          </thead>
          <tbody>
            {calls.length === 0 ? (
              <tr>
                <td colSpan={5}>Nog geen tool-aanroepen.</td>
              </tr>
            ) : (
              calls.map((row, i) => (
                <tr key={row.receipt_id ?? `${row.capability_id}-${i}`}>
                  <td>{row.recorded_at ?? "—"}</td>
                  <td>{row.tool_name || row.capability_id}</td>
                  <td>{row.status_label ?? row.status}</td>
                  <td>{row.latency_ms != null ? `${Math.round(row.latency_ms)}ms` : "—"}</td>
                  <td>{row.requested_by ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Dialog>
  );
}

type EditProps = {
  open: boolean;
  onClose: () => void;
  detail: ToolsCapabilityDetail | null;
  onSave: (payload: { name?: string; description?: string; enabled?: boolean; version?: string }) => void;
  onDelete: () => void;
};

export function ToolsEditDialog({ open, onClose, detail, onSave, onDelete }: EditProps) {
  const editable = detail?.editability?.editable === true;
  const [name, setName] = useState(detail?.capability.name ?? "");
  const [description, setDescription] = useState(detail?.capability.description ?? "");
  const [enabled, setEnabled] = useState(detail?.capability.enabled !== false);
  const [version, setVersion] = useState(String(detail?.summary.version ?? "1.0.0"));

  if (!editable) {
    return (
      <Dialog open={open} title="Bewerken" cancelLabel="Sluiten" onClose={onClose}>
        <p className="lv-muted">{detail?.editability?.reason ?? "Niet bewerkbaar"}</p>
        {detail?.editability?.navigate ? (
          <p>
            <a href={detail.editability.navigate}>Open provider configuratie</a>
          </p>
        ) : null}
      </Dialog>
    );
  }

  return (
    <Dialog
      open={open}
      title="Custom tool bewerken"
      confirmLabel="Opslaan"
      onClose={onClose}
      onConfirm={() => onSave({ name, description, enabled, version })}
    >
      <div className="lv-v2-schema-form__grid">
        <label className="lv-v2-schema-form__field">
          <span>Naam</span>
          <input className="lv-v2-input" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="lv-v2-schema-form__field">
          <span>Versie</span>
          <input className="lv-v2-input" value={version} onChange={(e) => setVersion(e.target.value)} />
        </label>
        <label className="lv-v2-schema-form__field">
          <span>Beschrijving</span>
          <textarea className="lv-v2-input" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label className="lv-v2-schema-form__field">
          <span>Enabled</span>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        </label>
        <button type="button" className="lv-v2-warn" onClick={onDelete}>
          Verwijderen
        </button>
      </div>
    </Dialog>
  );
}
