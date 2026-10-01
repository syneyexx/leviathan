import { useRef } from "react";
import {
  RD_COMPOSER_MODES,
  RD_CONTEXT_CHIPS,
  RD_INPUT_TABS,
  RD_TYPE_PRESETS,
} from "../../config/research";
import type { ResearchWorkspace } from "../../hooks/useResearchWorkspace";
import { UPLOAD_ACCEPT } from "../../pages/research/researchHelpers";
import { Button, Panel } from "../ui";

type Props = {
  ws: ResearchWorkspace;
};

export function ResearchComposer({ ws }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const customLimits = ws.budgetCatalog?.execution_modes.custom.limits;

  return (
    <Panel
      className="lv-v2-research-composer"
      title="Nieuw Onderzoek"
    >
      <div
        ref={(el) => {
          ws.composerRef.current = el;
        }}
        className="lv-v2-research-composer__inner"
      >
        <div className="lv-v2-segmented lv-v2-segmented--modes" role="tablist" aria-label="Onderzoeksmodus">
          {RD_COMPOSER_MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="tab"
              aria-selected={ws.composerMode === m.id}
              className={ws.composerMode === m.id ? "is-active" : undefined}
              onClick={() => ws.setComposerMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>

        <label className="lv-v2-field">
          <span>Onderzoeksvraag</span>
          <textarea
            value={ws.query}
            onChange={(e) => ws.setQuery(e.target.value)}
            placeholder="Wat wil je onderzoeken? Bijv. ‘Vergelijk vector databases voor private LLM infrastructuur’"
            aria-label="Onderzoeksvraag"
            rows={4}
          />
        </label>

        <div className="lv-v2-type-cards" role="group" aria-label="Onderzoekstype">
          {RD_TYPE_PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`lv-v2-type-card${ws.typePreset === p.id ? " is-selected" : ""}`}
              aria-pressed={ws.typePreset === p.id}
              onClick={() => ws.applyTypePreset(p.id)}
            >
              <strong>{p.label}</strong>
              <span>{p.description}</span>
            </button>
          ))}
        </div>

        <div className="lv-v2-research-composer__selects">
          <label className="lv-v2-field">
            <span>Gebruik Agents</span>
            <select
              value={ws.executionMode}
              aria-label="Gebruik Agents"
              onChange={(e) => ws.setExecutionMode(e.target.value as typeof ws.executionMode)}
            >
              <option value="normal">Research Agent (Standaard)</option>
              <option value="custom">Custom workers</option>
              <option value="team">Team mode</option>
            </select>
          </label>
          <label className="lv-v2-field">
            <span>Kennisbronnen</span>
            <select
              aria-label="Kennisbronnen"
              value={
                ws.context.web && ws.context.files
                  ? "all"
                  : ws.context.web
                    ? "web"
                    : ws.context.files
                      ? "files"
                      : "none"
              }
              onChange={(e) => {
                const v = e.target.value;
                if (v === "all") {
                  if (!ws.context.web) ws.toggleContext("web");
                  if (!ws.context.files) ws.toggleContext("files");
                } else if (v === "web") {
                  if (!ws.context.web) ws.toggleContext("web");
                  if (ws.context.files) ws.toggleContext("files");
                } else if (v === "files") {
                  if (ws.context.web) ws.toggleContext("web");
                  if (!ws.context.files) ws.toggleContext("files");
                }
              }}
            >
              <option value="all">Alle bronnen</option>
              <option value="web">Web</option>
              <option value="files">Lokale / uploads</option>
            </select>
          </label>
        </div>

        <div className="lv-v2-research-composer__footer">
          <button
            type="button"
            className="lv-v2-brain-link lv-v2-research-advanced-toggle"
            aria-expanded={ws.advancedOpen}
            onClick={() => ws.setAdvancedOpen(!ws.advancedOpen)}
          >
            Geavanceerde opties
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d={ws.advancedOpen ? "m6 14 6-6 6 6" : "m6 10 6 6 6-6"} />
            </svg>
          </button>
          <Button
            variant="primary"
            loading={ws.busy}
            disabled={ws.busy || !ws.query.trim()}
            onClick={() => void ws.onStartResearch()}
          >
            ▶ Onderzoek starten
          </Button>
        </div>

        {ws.advancedOpen ? (
          <div className="lv-v2-research-advanced">
            <div className="lv-v2-segmented" role="tablist" aria-label="Bron-tabs">
              {RD_INPUT_TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={ws.inputTab === tab}
                  className={ws.inputTab === tab ? "is-active" : undefined}
                  onClick={() => {
                    ws.setInputTab(tab);
                    if (tab === "Datasets") void ws.loadDatasetsForPicker();
                  }}
                >
                  {tab}
                </button>
              ))}
            </div>

            <div className="lv-v2-chip-row" role="group" aria-label="Context bronnen">
              {RD_CONTEXT_CHIPS.map((chip) => {
                const unavailable = "unavailable" in chip ? chip.unavailable : undefined;
                const on = !!ws.context[chip.id];
                return (
                  <button
                    key={chip.id}
                    type="button"
                    className={`lv-v2-chip${on ? " is-on" : ""}${unavailable ? " is-disabled" : ""}`}
                    aria-pressed={on}
                    disabled={!!unavailable}
                    title={unavailable}
                    onClick={() => {
                      if (!unavailable) ws.toggleContext(chip.id);
                    }}
                  >
                    {chip.label}
                    {unavailable ? " (n.v.t.)" : ""}
                  </button>
                );
              })}
            </div>

            <div className="lv-v2-research-composer__selects">
              <label className="lv-v2-field">
                <span>Depth</span>
                <select value={ws.depth} aria-label="Depth" onChange={(e) => ws.setDepth(e.target.value)}>
                  <option value="quick">Quick</option>
                  <option value="standard">Standard</option>
                  <option value="deep">Deep</option>
                  <option value="expert">Expert</option>
                </select>
              </label>
              <label className="lv-v2-field">
                <span>Model</span>
                <select value={ws.modelId} aria-label="Model" onChange={(e) => ws.setModelId(e.target.value)}>
                  <option value="">Auto (default LLM)</option>
                  {ws.models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.displayName}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {ws.executionMode === "custom" || ws.executionMode === "team" ? (
              <div className="lv-v2-research-composer__selects">
                <label className="lv-v2-field">
                  <span>Workers ({ws.effectiveWorkers})</span>
                  <input
                    type="range"
                    min={customLimits?.research_workers.min ?? 1}
                    max={customLimits?.research_workers.max ?? 16}
                    value={ws.customWorkers}
                    aria-label="Workers"
                    onChange={(e) => ws.setCustomWorkers(Number(e.target.value))}
                  />
                </label>
                {ws.executionMode === "custom" ? (
                  <label className="lv-v2-field">
                    <span>Rounds ({ws.effectiveRounds ?? "—"})</span>
                    <input
                      type="range"
                      min={customLimits?.rounds.min ?? 1}
                      max={customLimits?.rounds.max ?? 100}
                      value={ws.customRounds}
                      aria-label="Rounds"
                      onChange={(e) => ws.setCustomRounds(Number(e.target.value))}
                    />
                  </label>
                ) : (
                  <p className="lv-v2-muted">Team mode: quality contract (rounds unbounded)</p>
                )}
              </div>
            ) : (
              <p className="lv-v2-muted">
                Standaard: {ws.effectiveWorkers} workers × {ws.effectiveRounds ?? "—"} rounds
              </p>
            )}

            {ws.inputTab === "Files" ? (
              <div
                className={`lv-v2-dropzone${ws.dragOver ? " is-over" : ""}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  ws.setDragOver(true);
                }}
                onDragLeave={() => ws.setDragOver(false)}
                onDrop={ws.onDrop}
              >
                <p>Sleep bestanden hierheen of</p>
                <Button variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()}>
                  Kies bestanden
                </Button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept={UPLOAD_ACCEPT}
                  className="lv-v2-sr-only"
                  onChange={(e) => void ws.onFilesSelected(e.target.files)}
                />
              </div>
            ) : null}

            {ws.inputTab === "URLs" ? (
              <div className="lv-v2-field">
                <span>URL bronnen</span>
                <textarea
                  value={ws.urlDraft}
                  onChange={(e) => ws.setUrlDraft(e.target.value)}
                  placeholder="https://… (één per regel of komma)"
                  rows={3}
                  aria-label="URL bronnen"
                />
                <Button variant="secondary" size="sm" onClick={() => void ws.onAddUrlSource()}>
                  URLs toevoegen
                </Button>
              </div>
            ) : null}

            {ws.inputTab === "Datasets" ? (
              <div className="lv-v2-research-composer__selects">
                <label className="lv-v2-field">
                  <span>Dataset</span>
                  <select
                    value={ws.selectedDatasetId}
                    aria-label="Dataset"
                    onChange={(e) => ws.setSelectedDatasetId(e.target.value)}
                    onFocus={() => void ws.loadDatasetsForPicker()}
                  >
                    <option value="">Selecteer…</option>
                    {ws.datasets.map((d) => (
                      <option key={d.datasetId} value={d.datasetId}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </label>
                <Button variant="secondary" size="sm" onClick={() => void ws.onConnectDataset()}>
                  Verbind dataset
                </Button>
                {ws.connectedDatasetLabel ? (
                  <p className="lv-v2-muted">Verbonden: {ws.connectedDatasetLabel}</p>
                ) : null}
              </div>
            ) : null}

            {ws.inputTab === "Code" || ws.inputTab === "Images" ? (
              <p className="lv-v2-muted">
                {ws.inputTab === "Code"
                  ? "Code analysis is not wired into Research yet."
                  : "Image research is not available yet."}
              </p>
            ) : null}

            {ws.webReadiness && !ws.webReadiness.search_available ? (
              <p className="lv-v2-muted" role="status">
                Web readiness: {ws.webReadiness.operator_summary || "search unavailable"}
                {ws.webProbeExecution.phase !== "idle" ? (
                  <> · probe {ws.webProbeExecution.phase}</>
                ) : null}
                <Button
                  variant="ghost"
                  size="sm"
                  loading={ws.webProbeBusy}
                  onClick={() => void ws.probeWeb()}
                >
                  Test web research
                </Button>
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
