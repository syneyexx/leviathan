import { AlertTriangle, Loader2 } from "lucide-react";
import { Panel, StatusBadge } from "@/components/hades/ui";
import type { SpecialistContract } from "@/lib/hades-api";
import { ioSummary } from "./helpers";

type SpecialistContractsPanelProps = {
  specialists: SpecialistContract[];
  loading: boolean;
  error: string | null;
};

export function SpecialistContractsPanel({ specialists, loading, error }: SpecialistContractsPanelProps) {
  return (
    <Panel
      className="mt-3"
      title="Specialist-contracten"
      eyebrow="Backend routing & I/O"
      actions={<StatusBadge tone="info">{specialists.length} contracten</StatusBadge>}
    >
      {loading ? (
        <div className="table-empty"><Loader2 className="spin muted-icon" /> Contracten laden…</div>
      ) : error ? (
        <div className="inline-error" role="alert"><AlertTriangle />{error}</div>
      ) : specialists.length ? (
        <div className="specialist-contracts-grid">
          {specialists.map((contract) => (
            <div className="specialist-contract-card" key={contract.agent_id}>
              <div className="specialist-contract-head">
                <strong>{contract.name}</strong>
                <code>{contract.agent_id}</code>
              </div>
              <small className="specialist-contract-role">{contract.responsibility}</small>
              <p className="specialist-contract-io">{ioSummary(contract)}</p>
              <div className="specialist-contract-badges">
                <StatusBadge tone={contract.planned_only ? "warning" : contract.enabled ? "success" : "neutral"}>
                  {contract.planned_only ? "planned_only" : contract.enabled ? "enabled" : "disabled"}
                </StatusBadge>
                <StatusBadge tone="neutral">{contract.model_profile}</StatusBadge>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-copy">Geen specialist-contracten van de backend.</p>
      )}
    </Panel>
  );
}
