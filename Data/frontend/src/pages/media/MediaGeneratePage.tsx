import { useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { Button, Panel } from "../../components/ui";
import { AppShell } from "../../layouts/AppShell";
import { MediaTruthBanner } from "../../components/media/MediaTruthBanner";

const TOOL_ACTIONS: Record<string, { action: string; label: string; needsPrompt: boolean }> = {
  image: { action: "IMAGE_GENERATE", label: "Afbeelding", needsPrompt: true },
  video: { action: "VIDEO_PROCESS", label: "Video", needsPrompt: false },
  audio: { action: "AUDIO_PROCESS", label: "Audio", needsPrompt: false },
};

/**
 * Minimal production-ready media generation studio.
 * Submits through POST /api/media/request (JobRuntime) — no fake progress.
 */
export function MediaGeneratePage() {
  const [params] = useSearchParams();
  const initialTool = params.get("tool") || "image";
  const [tool, setTool] = useState(initialTool in TOOL_ACTIONS ? initialTool : "image");
  const [prompt, setPrompt] = useState("");
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const meta = useMemo(() => TOOL_ACTIONS[tool] ?? TOOL_ACTIONS.image, [tool]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const payload: {
        action: string;
        prompt?: string;
        path?: string;
        wait_seconds?: number;
      } = {
        action: meta.action,
        wait_seconds: 15,
      };
      if (meta.needsPrompt) payload.prompt = prompt.trim() || "Leviathan media concept";
      if (path.trim()) payload.path = path.trim();
      const res = await api.mediaRequest(payload);
      const state = String(res.state ?? (res.job as { status?: string } | undefined)?.status ?? "queued");
      const jobId = String(res.job_id ?? (res.job as { job_id?: string } | undefined)?.job_id ?? "—");
      setResult(`Job ${jobId} · ${state}`);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Media request mislukt";
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      variant="v2"
      v2Title="Media Control / Genereren"
      v2Subtitle="Start AI media generatie via de Media JobRuntime."
      v2Online={null}
    >
      <main className="lv-v2-page lv-v2-page--media">
        <MediaTruthBanner>
          Generatie loopt via /api/media/request. Geen gefabriceerde previews.
        </MediaTruthBanner>
        <Panel
          title="Media Studio"
          action={
            <Link to="/media" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm">
              Terug naar Overzicht
            </Link>
          }
        >
          <form className="lv-v2-media-studio" onSubmit={onSubmit}>
            <label className="lv-v2-media-studio__field">
              <span>Tool</span>
              <select
                className="lv-v2-select"
                value={tool}
                onChange={(e) => setTool(e.target.value)}
              >
                <option value="image">Afbeelding Generatie</option>
                <option value="video">Video Generatie / Process</option>
                <option value="audio">Audio Process</option>
              </select>
            </label>
            {meta.needsPrompt ? (
              <label className="lv-v2-media-studio__field">
                <span>Prompt</span>
                <textarea
                  className="lv-v2-input"
                  rows={4}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Beschrijf de media die je wilt genereren…"
                />
              </label>
            ) : (
              <label className="lv-v2-media-studio__field">
                <span>Bronpad (optioneel)</span>
                <input
                  className="lv-v2-input"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  placeholder="/pad/naar/bestand"
                />
              </label>
            )}
            <div className="lv-v2-media-studio__actions">
              <Button variant="primary" type="submit" loading={busy}>
                Start {meta.label}
              </Button>
              <Button variant="secondary" type="button" onClick={() => window.location.assign("/media/library")}>
                Open bibliotheek
              </Button>
            </div>
            {error ? (
              <p className="lv-v2-media-studio__error" role="alert" data-truth="unavailable">
                {error}
              </p>
            ) : null}
            {result ? (
              <p className="lv-v2-media-studio__ok" role="status">
                {result}
              </p>
            ) : null}
          </form>
        </Panel>
      </main>
    </AppShell>
  );
}
