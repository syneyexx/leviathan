import { useState } from "react";
import type { NativeModel } from "../types/backend";

const tabs = ["Runtime", "Operations", "Pipeline", "Diagnostics"] as const;

export function NativeRuntimeConsole({ model }: { model: NativeModel }) {
  const [tab, setTab] = useState<(typeof tabs)[number]>("Runtime");
  return (
    <section className="panel" aria-label="Native data plane">
      <header>
        <h2>RUST CONSOLE / NATIVE DATA PLANE</h2>
        <div className="native-tabs">
          {tabs.map((item) => (
            <button key={item} type="button" className={item === tab ? "on" : ""} onClick={() => setTab(item)}>{item}</button>
          ))}
        </div>
      </header>
      <div className="native-body">
        {tab === "Runtime" && (
          <>
            <div className="status-line">probe {model.status} · {model.version}</div>
            <div>role: Worker Fabric accelerator, not a control plane</div>
            <div>daemon: none</div>
            <div>binary: {model.binaryPath || "BUILD MISSING"}</div>
            <div>{model.detail || "No probe detail."}</div>
            {model.recent.map((row, index) => (
              <div key={`${row.at}-${index}`}>{row.at} {row.operation} {row.message}</div>
            ))}
          </>
        )}
        {tab === "Operations" && (
          model.recent.length === 0 ? <div>No native operation events in the bounded observability tail.</div> : model.recent.map((row, index) => (
            <div key={`${row.at}-${index}`}>{row.at} {row.operation} {row.message}</div>
          ))
        )}
        {tab === "Pipeline" && (
          <div>
            Supported operations come from the probe, not a fabricated pipeline.
            {model.operations.length === 0 ? " None reported." : ` ${model.operations.join(", ")}`}
          </div>
        )}
        {tab === "Diagnostics" && (
          <div>GPU/SIMD claims are omitted unless the probe reports them. Status {model.status} is the authority. A binary path is not availability.</div>
        )}
      </div>
    </section>
  );
}
