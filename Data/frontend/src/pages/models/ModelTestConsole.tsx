import { useState } from "react";
import { api, ApiError } from "../../api/client";
import type { ModelInferenceTestResult } from "../../types/api";

export function ModelTestConsole({
  modelId,
  displayName,
  busy: parentBusy,
}: {
  modelId: string;
  displayName: string;
  busy?: boolean;
}) {
  const [prompt, setPrompt] = useState("ping");
  const [maxTokens, setMaxTokens] = useState(64);
  const [stream, setStream] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ModelInferenceTestResult | null>(null);

  const disabled = Boolean(parentBusy) || running || !prompt.trim();

  async function onRun() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.testModel(modelId, {
        prompt: prompt.trim(),
        maxTokens,
        stream,
      });
      setResult(res.result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Inference test failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="lv-models-profile" aria-label="Model test console">
      <p className="lv-muted">
        Real gateway inference against <strong>{displayName}</strong>. Failures surface honestly — no
        fabricated completions.
      </p>
      <label>
        Prompt
        <textarea
          className="lv-input lv-models-prompt"
          rows={4}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={running}
        />
      </label>
      <label>
        Max tokens
        <input
          className="lv-input"
          type="number"
          min={1}
          max={2048}
          value={maxTokens}
          onChange={(e) => setMaxTokens(Number(e.target.value) || 64)}
          disabled={running}
        />
      </label>
      <label className="lv-models-check">
        <input
          type="checkbox"
          checked={stream}
          onChange={(e) => setStream(e.target.checked)}
          disabled={running}
        />
        Request stream (may fall back to non-stream if unsupported)
      </label>
      <div className="lv-row-actions">
        <button className="lv-btn lv-btn-gold" type="button" disabled={disabled} onClick={() => void onRun()}>
          {running ? "Running…" : "Run test"}
        </button>
      </div>
      {error ? (
        <div className="lv-models-banner is-error" role="alert">
          <strong>Test failed</strong>
          <span>{error}</span>
        </div>
      ) : null}
      {result ? (
        <div>
          <div className="lv-meta-grid">
            <div className="lv-meta-item">
              <span>OK</span>
              <strong>{result.ok ? "yes" : "no"}</strong>
            </div>
            <div className="lv-meta-item">
              <span>Latency</span>
              <strong>
                {result.totalLatencyMs == null ? "—" : `${Math.round(result.totalLatencyMs)} ms`}
              </strong>
            </div>
            <div className="lv-meta-item">
              <span>Finish</span>
              <strong>{result.finishReason ?? "—"}</strong>
            </div>
            <div className="lv-meta-item">
              <span>Stream</span>
              <strong>
                {result.streamRequested
                  ? result.streamImplemented
                    ? "implemented"
                    : "requested (not implemented)"
                  : "off"}
              </strong>
            </div>
          </div>
          {result.note ? <p className="lv-muted">{result.note}</p> : null}
          <h3>Preview</h3>
          {result.preview ? (
            <pre className="lv-code-block" style={{ whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto" }}>
              {result.preview}
            </pre>
          ) : (
            <p className="lv-muted">Provider returned an empty preview.</p>
          )}
        </div>
      ) : !error && !running ? (
        <p className="lv-muted">No test result yet.</p>
      ) : null}
    </div>
  );
}
