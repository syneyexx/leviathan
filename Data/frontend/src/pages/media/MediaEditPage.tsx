import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { MediaTruthBanner } from "../../components/media/MediaTruthBanner";
import { Button, Panel } from "../../components/ui";
import { AppShell } from "../../layouts/AppShell";

/** Minimal edit studio — IMAGE_EDIT via media JobRuntime. */
export function MediaEditPage() {
  const [path, setPath] = useState("");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.mediaRequest({
        action: "IMAGE_EDIT",
        path: path.trim() || undefined,
        instruction: instruction.trim() || "Enhance clarity and contrast",
        wait_seconds: 15,
      });
      const state = String(res.state ?? "queued");
      const jobId = String(res.job_id ?? "—");
      setResult(`Job ${jobId} · ${state}`);
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : "Edit request mislukt");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      variant="v2"
      v2Title="Media Control / Bewerken"
      v2Subtitle="AI edit / enhance via media.image_edit."
      v2Online={null}
    >
      <main className="lv-v2-page lv-v2-page--media">
        <MediaTruthBanner>Bewerken gebruikt IMAGE_EDIT — geen gefabriceerde before/after.</MediaTruthBanner>
        <Panel
          title="Media Bewerken"
          action={
            <Link to="/media" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm">
              Terug naar Overzicht
            </Link>
          }
        >
          <form className="lv-v2-media-studio" onSubmit={onSubmit}>
            <label className="lv-v2-media-studio__field">
              <span>Bronpad / artifact pad</span>
              <input
                className="lv-v2-input"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="/pad/naar/media"
              />
            </label>
            <label className="lv-v2-media-studio__field">
              <span>Instructie</span>
              <textarea
                className="lv-v2-input"
                rows={4}
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="Wat moet er aangepast worden?"
              />
            </label>
            <div className="lv-v2-media-studio__actions">
              <Button variant="primary" type="submit" loading={busy}>
                Start bewerking
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
