import type { ReactNode } from "react";
import type { Chip, ControlRoomModel } from "./viewModel";

export type ControlRoomPhase = "loading" | "error" | "empty" | "ready";

const PHASE_COPY: Record<Exclude<ControlRoomPhase, "ready">, string> = {
  loading: "Loading snapshot…",
  error: "Snapshot unavailable.",
  empty: "No snapshot returned.",
};

type Props = {
  phase: ControlRoomPhase;
  error?: string | null;
  model: ControlRoomModel | null;
  image: string;
  refreshing?: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onRefresh: () => void;
};

export function ControlRoomView({
  phase,
  error,
  model,
  image,
  refreshing = false,
  selectedId,
  onSelect,
  onRefresh,
}: Props) {
  const pending = phase === "ready" ? null : PHASE_COPY[phase];
  return (
    <div className="lv-cr" data-phase={phase}>
      <Hero image={image} generatedAt={model?.generatedAt ?? "—"} refreshing={refreshing || phase === "loading"} onRefresh={onRefresh} />
      {error ? (
        <div className="lv-cr-banner" role="alert">
          {error}
        </div>
      ) : null}
      {model ? (
        <Ready model={model} selectedId={selectedId} onSelect={onSelect} />
      ) : (
        <Pending message={pending ?? PHASE_COPY.empty} />
      )}
    </div>
  );
}

function Hero({
  image,
  generatedAt,
  refreshing,
  onRefresh,
}: {
  image: string;
  generatedAt: string;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <section className="lv-cr-hero" aria-label="Control Room">
      <div className="lv-cr-hero-media">
        <img src={image} alt="" />
      </div>
      <div className="lv-cr-hero-shade" />
      <div className="lv-cr-hero-content">
        <h1>CONTROL ROOM</h1>
        <p className="lv-cr-kicker">INSTITUTIONAL OVERSIGHT • RISK • AUDIT • QUALIFICATION</p>
        <p className="lv-cr-sub">
          Oversee system readiness, compliance, evidence, and autonomous research from a unified command center.
        </p>
      </div>
      <aside className="lv-cr-hero-rail" aria-label="Institutional principles">
        <span>Trusted data</span>
        <span>Verifiable reasoning</span>
        <span>Reproducible results</span>
        <span>Institutional readiness</span>
      </aside>
      <div className="lv-cr-hero-actions">
        <span className="lv-cr-generated">{generatedAt}</span>
        <button type="button" className="lv-cr-btn" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>
    </section>
  );
}

function Ready({
  model,
  selectedId,
  onSelect,
}: {
  model: ControlRoomModel;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <>
      <section className="lv-cr-kpis" aria-label="Control Room status" data-section="status-strip">
        {model.kpis.map((kpi) => (
          <article key={kpi.id} className="lv-cr-kpi" data-kpi={kpi.id}>
            <span className="lv-cr-kpi-label">{kpi.label}</span>
            <strong className={`lv-cr-kpi-value is-${kpi.tone}`} data-tone={kpi.tone}>
              {kpi.value}
            </strong>
            <span className="lv-cr-kpi-foot">{kpi.foot}</span>
          </article>
        ))}
      </section>

      <div className="lv-cr-grid">
        <div className="lv-cr-col">
          <GuardColumn model={model} />
        </div>
        <div className="lv-cr-col">
          <QualificationColumn model={model} />
        </div>
        <div className="lv-cr-col">
          <IntegrityColumn model={model} selectedId={selectedId} onSelect={onSelect} />
        </div>
      </div>

      <div className="lv-cr-bottom">
        <TimelinePanel model={model} selectedId={selectedId} onSelect={onSelect} />
        <FabricPanel model={model} />
      </div>
      <p className="lv-cr-truth" data-section="truth">
        snapshot_from_real_state · unmeasured_panels_stay_unmeasured · no_fake_green · guard {model.guard.state.label}
      </p>
    </>
  );
}

function GuardColumn({ model }: { model: ControlRoomModel }) {
  return (
    <>
      <Card title="Live Trading Guard" extra={<Pill chip={model.guard.state} />} section="live-guard">
        <p className="lv-cr-copy">{model.guard.detail}</p>
        <div className="lv-cr-flags">
          {model.guard.flags.map((flag) => (
            <span key={flag.label} className="lv-cr-flag">
              <em>{flag.label}</em>
              <strong className={`is-${flag.tone}`} data-tone={flag.tone}>
                {flag.value}
              </strong>
            </span>
          ))}
        </div>
        <div className="lv-cr-inline" data-section="health">
          <span>System health</span>
          <Pill chip={model.health} />
          {model.guard.assurance ? (
            <span className="lv-cr-muted">assurance {model.guard.assurance.label}</span>
          ) : (
            <span className="lv-cr-muted">assurance UNMEASURED</span>
          )}
        </div>
      </Card>

      <Card title="Capability Gap Matrix" extra={<span className="lv-cr-muted">open {model.gaps.open}</span>} section="capability-gaps">
        <div className="lv-cr-buckets">
          <span>
            <em>Total</em>
            <strong>{model.gaps.total}</strong>
          </span>
          {model.gaps.buckets.map((bucket) => (
            <span key={bucket.id} title={bucket.hint}>
              <em>{bucket.label}</em>
              <strong>{bucket.value}</strong>
            </span>
          ))}
        </div>
        {model.gaps.statuses.length ? (
          <div className="lv-cr-status-row">
            {model.gaps.statuses.map((status) => (
              <span key={status.label} className={`lv-cr-mini is-${status.tone}`} data-tone={status.tone}>
                {status.label} {status.count}
              </span>
            ))}
          </div>
        ) : (
          <Empty>No gap status breakdown.</Empty>
        )}
      </Card>

      <Card title="Multi-Asset Readiness" extra={<Pill chip={model.multiAssetStatus} />} section="multi-asset">
        {model.families.length ? (
          <ul className="lv-cr-list">
            {model.families.map((family) => (
              <li key={family.family}>
                <span>{family.family}</span>
                <Pill chip={family.historical} />
                <em className={`is-${family.live.tone}`}>live {family.live.label}</em>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No asset families in this snapshot.</Empty>
        )}
      </Card>

      <Card title="Data Plane Certification" extra={<Pill chip={model.dataPlane.status} />} section="data-plane">
        <dl className="lv-cr-metrics">
          <div>
            <dt>Certified in sample</dt>
            <dd>{model.dataPlane.certifiedInSample}</dd>
          </div>
          <div>
            <dt>Sample size</dt>
            <dd>{model.dataPlane.sampleCount}</dd>
          </div>
          <div>
            <dt>Point-in-time</dt>
            <dd>
              <Pill chip={model.dataPlane.pit} />
            </dd>
          </div>
          <div>
            <dt>Survivorship</dt>
            <dd>
              <Pill chip={model.dataPlane.survivorship} />
            </dd>
          </div>
          <div>
            <dt>Recency</dt>
            <dd>{model.dataPlane.recency}</dd>
          </div>
        </dl>
      </Card>
    </>
  );
}

function QualificationColumn({ model }: { model: ControlRoomModel }) {
  return (
    <>
      <Card
        title="Qualification Pipeline"
        section="qualification-pipeline"
        extra={
          <span className="lv-cr-actions">
            <button type="button" className="lv-cr-btn" disabled title={model.actions.viewPipeline.reason}>
              View pipeline
            </button>
            <a className="lv-cr-btn" href={model.actions.researchLab.href}>
              {model.actions.researchLab.label}
            </a>
          </span>
        }
      >
        <p className="lv-cr-hint">{model.actions.viewPipeline.reason}</p>
        <div className="lv-cr-gates" aria-label="Qualification gates">
          {model.gates.map((gate) => (
            <div key={gate.code} className={`lv-cr-gate is-${gate.visual}`} data-gate={gate.code} data-visual={gate.visual}>
              <i />
              <span>{gate.code}</span>
            </div>
          ))}
        </div>
        <p className="lv-cr-copy">{model.gateCaption}</p>
      </Card>

      <div className="lv-cr-mini-kpis" data-section="research-kpis">
        {model.researchKpis.map((kpi) => (
          <article key={kpi.id}>
            <span>{kpi.label}</span>
            <strong className={`is-${kpi.tone}`} data-tone={kpi.tone}>
              {kpi.value}
            </strong>
            <em>{kpi.foot}</em>
          </article>
        ))}
      </div>

      <Card title="Current Qualification State" extra={<Pill chip={model.qualification.status} />} section="qualification-state">
        <dl className="lv-cr-metrics">
          <div>
            <dt>Current gate</dt>
            <dd>{model.qualification.gate}</dd>
          </div>
          <div>
            <dt>Decision</dt>
            <dd>{model.qualification.decision}</dd>
          </div>
        </dl>
        {model.qualification.blockers.length ? (
          <ul className="lv-cr-notes">
            {model.qualification.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        ) : (
          <Empty>No rejection reasons in this snapshot.</Empty>
        )}
        {model.qualification.sealed.length ? (
          <ul className="lv-cr-list">
            {model.qualification.sealed.map((row) => (
              <li key={row.id}>
                <span>{row.id}</span>
                <Pill chip={row.status} />
                <em>{row.strategyId}</em>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No sealed candidate in this snapshot.</Empty>
        )}
      </Card>

      <Card title="Research Experiments" section="experiments">
        {model.experiments.length ? (
          <ul className="lv-cr-list lv-cr-scroll">
            {model.experiments.map((row) => (
              <li key={`${row.id}-${row.detail}`}>
                <span className="lv-cr-mono">{row.id}</span>
                <Pill chip={row.status} />
                <em>{row.detail}</em>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No research runs in this snapshot.</Empty>
        )}
      </Card>
    </>
  );
}

function IntegrityColumn({
  model,
  selectedId,
  onSelect,
}: {
  model: ControlRoomModel;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <>
      <Card title="Reconciliation Breaks" extra={<Pill chip={model.breakStatus} />} section="breaks">
        <DataTable
          headers={["Time", "Source", "Type", "Description"]}
          empty="No open breaks."
          rows={model.breaks.map((row) => ({
            id: row.id,
            cells: [row.time, row.source, row.type, row.description],
            tone: row.severity,
          }))}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      </Card>
      <Card title="Exceptions" extra={<Pill chip={model.exceptionStatus} />} section="exceptions">
        <DataTable
          headers={["Time", "Kind", "Severity", "Status"]}
          empty="No open exceptions."
          rows={model.exceptions.map((row) => ({
            id: row.id,
            cells: [row.time, row.kind, row.severity.label, row.status.label],
            tone: row.severity,
          }))}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      </Card>
      <Card title="Audit Chain" section="audit">
        <ul className="lv-cr-audit">
          {model.auditRows.map((row) => (
            <li key={row.label}>
              <span>{row.label}</span>
              <strong className={`is-${row.tone}`} data-tone={row.tone}>
                {row.value}
              </strong>
              <em>{row.detail}</em>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Operator Attention" section="attention">
        {model.attention.length ? (
          <ul className="lv-cr-notes">
            {model.attention.map((item) => (
              <li key={item.id}>
                <Pill chip={item.severity} />
                <span>{item.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No derived operator attention items.</Empty>
        )}
      </Card>
      <Card
        title="Snapshot Notes"
        section="notes"
        extra={
          <button type="button" className="lv-cr-btn" disabled title={model.actions.addNote.reason}>
            Add note
          </button>
        }
      >
        <p className="lv-cr-hint">{model.actions.addNote.reason}</p>
        {model.notes.length ? (
          <ul className="lv-cr-notes">
            {model.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : (
          <Empty>No snapshot notes.</Empty>
        )}
      </Card>
    </>
  );
}

function TimelinePanel({
  model,
  selectedId,
  onSelect,
}: {
  model: ControlRoomModel;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <Card title="Institutional Events & Evidence Timeline" section="timeline">
      <DataTable
        headers={["Time", "Type", "Description", "Entity"]}
        empty="No institutional events in this snapshot."
        rows={model.timeline.map((row) => ({
          id: row.id,
          cells: [row.time, row.type, row.description, row.entity],
          tone: row.severity,
        }))}
        selectedId={selectedId}
        onSelect={onSelect}
      />
    </Card>
  );
}

function FabricPanel({ model }: { model: ControlRoomModel }) {
  return (
    <Card title="API & Event Fabric" section="api-fabric">
      <p className="lv-cr-hint">{model.fabricNote}</p>
      <h3>API contracts</h3>
      {model.apiRows.length ? (
        <div className="lv-cr-scroll">
          <table className="lv-cr-table">
            <thead>
              <tr>
                <th>Service</th>
                <th>Status</th>
                <th>Latency</th>
              </tr>
            </thead>
            <tbody>
              {model.apiRows.map((row) => (
                <tr key={row.id}>
                  <td>{row.service}</td>
                  <td>
                    <Pill chip={row.status} />
                  </td>
                  <td className="is-neutral" data-tone="neutral">
                    {row.latency}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>No API contracts in this snapshot.</Empty>
      )}
      <h3>Event contracts</h3>
      {model.eventRows.length ? (
        <div className="lv-cr-scroll">
          <table className="lv-cr-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Status</th>
                <th>Throughput</th>
              </tr>
            </thead>
            <tbody>
              {model.eventRows.map((row) => (
                <tr key={row.id}>
                  <td>{row.service}</td>
                  <td>
                    <Pill chip={row.status} />
                  </td>
                  <td className="is-neutral" data-tone="neutral">
                    {row.throughput}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>No event contracts in this snapshot.</Empty>
      )}
    </Card>
  );
}

function Pending({ message }: { message: string }) {
  const titles = [
    "Live Trading Guard",
    "Capability Gap Matrix",
    "Multi-Asset Readiness",
    "Data Plane Certification",
    "Qualification Pipeline",
    "Current Qualification State",
    "Research Experiments",
    "Reconciliation Breaks",
    "Exceptions",
    "Audit Chain",
    "Operator Attention",
    "Snapshot Notes",
    "Institutional Events & Evidence Timeline",
    "API & Event Fabric",
  ];
  return (
    <div className="lv-cr-pending" data-section="pending">
      <p className="lv-cr-pending-lead">{message}</p>
      <div className="lv-cr-pending-grid">
        {titles.map((title) => (
          <section key={title} className="lv-cr-card">
            <header className="lv-cr-card-head">
              <h2>{title}</h2>
            </header>
            <Empty>{message}</Empty>
          </section>
        ))}
      </div>
    </div>
  );
}

function Card({
  title,
  extra,
  section,
  children,
}: {
  title: string;
  extra?: ReactNode;
  section: string;
  children: ReactNode;
}) {
  return (
    <section className="lv-cr-card" data-section={section}>
      <header className="lv-cr-card-head">
        <h2>{title}</h2>
        {extra}
      </header>
      {children}
    </section>
  );
}

function Pill({ chip }: { chip: Chip }) {
  return (
    <span className={`lv-cr-pill is-${chip.tone}`} data-tone={chip.tone}>
      {chip.label}
    </span>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="lv-cr-empty">{children}</p>;
}

function DataTable({
  headers,
  rows,
  empty,
  selectedId,
  onSelect,
}: {
  headers: string[];
  rows: { id: string; cells: string[]; tone: Chip }[];
  empty: string;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  if (!rows.length) return <Empty>{empty}</Empty>;
  const selected = rows.find((row) => row.id === selectedId) ?? null;
  return (
    <div className="lv-cr-scroll">
      <table className="lv-cr-table">
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isSelected = selectedId === row.id;
            return (
              <tr
                key={row.id}
                data-row={row.id}
                data-tone={row.tone.tone}
                className={isSelected ? "is-selected" : undefined}
                aria-selected={isSelected}
                tabIndex={0}
                onClick={() => onSelect(isSelected ? null : row.id)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  event.preventDefault();
                  onSelect(isSelected ? null : row.id);
                }}
              >
                {row.cells.map((cell, index) => (
                  <td key={`${row.id}-${index}`}>{cell}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {selected ? <p className="lv-cr-detail">{selected.cells.join(" · ")}</p> : null}
    </div>
  );
}
