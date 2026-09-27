import { useState } from "react";
import type { NativeModel } from "../types/backend";

const tabs = ["Runtime", "Operations", "Pipeline", "Diagnostics"] as const;

export function NativeRuntimeConsole({ model }: { model: NativeModel }) {
  const [tab, setTab] = useState<(typeof tabs)[number]>("Runtime");
  return (
    <section className="panel" aria-label="Native data plane">
      <header>
        <div className="panel-head">
          <h2>RUST CONSOLE / NATIVE RUNTIME</h2>
          <span className="sub">Native pipeline output. Worker-owned accelerator, not a control plane.</span>
        </div>
        <div className="native-tabs">
          {tabs.map((item) => (
            <button key={item} type="button" className={item === tab ? "on" : ""} onClick={() => setTab(item)}>{item}</button>
          ))}
        </div>
      </header>
      <div className="native-body">
        {tab === "Runtime" && (
          <>
            {model.status !== "AVAILABLE" && <div className="status-line">{model.status} · {model.version}</div>}
            {(model.status === "BUILD_MISSING" || model.binaryPath == null) && <div>BUILD MISSING</div>}
            {model.recent.length === 0 && <div>{model.detail || "No native runtime events."}</div>}
            {model.recent.map((row, index) => (
              <div key={`${row.at}-${index}`}><span className="ts">{row.at}</span> <span className="tag">[rust]</span> {row.message}</div>
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
          <div>
            <div>role: Worker Fabric accelerator, not a control plane</div>
            <div>daemon: none</div>
            <div>binary: {model.binaryPath || "BUILD MISSING"}</div>
            <div>probe: {model.status} · {model.version}</div>
            <div>{model.detail || "No probe detail."}</div>
            <div>GPU/SIMD claims are omitted unless the probe reports them. A binary path is not availability.</div>
          </div>
        )}
      </div>
    </section>
  );
}
