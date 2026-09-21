"use client";

import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { hadesApi, type Gen2EvalRun } from "@/lib/hades-api";

/**
 * Settings → Advanced → Meet dit model
 * Compares / measures local model quality. Never fabricates PASS without a live model.
 */
export function MeetDitModelPanel() {
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<Gen2EvalRun | null>(null);
  const [abBusy, setAbBusy] = useState(false);
  const [abNote, setAbNote] = useState<string | null>(null);

  const qualityLabel = (): { tone: "neutral" | "success" | "warning" | "danger"; text: string } => {
    if (!report) return { tone: "neutral", text: "Quality = UNMEASURED" };
    const status = String(report.status || "").toLowerCase();
    const summary = report.summary || {};
    if (status === "unmeasured" || summary.model_invoked === false) {
      return { tone: "neutral", text: "Quality = UNMEASURED" };
    }
    if (typeof summary.pass_rate === "number") {
      const rate = Math.round(summary.pass_rate * 100);
      return {
        tone: rate >= 70 ? "success" : rate >= 40 ? "warning" : "danger",
        text: `Quality gemeten · pass_rate ${rate}%`,
      };
    }
    return { tone: "warning", text: `Status: ${report.status}` };
  };

  const runMeet = async () => {
    setBusy(true);
    setAbNote(null);
    try {
      const models = await hadesApi.models();
      const modelId = models.active_profile?.model_id || models.models[0]?.id || "";
      if (!modelId) {
        setReport({
          id: "local-unmeasured",
          suite: "meet_dit_model",
          status: "unmeasured",
          model_id: null,
          summary: {
            model_invoked: false,
            note: "Geen geladen lokaal model — Quality = UNMEASURED (geen FAIL van software).",
          },
        });
        toast.message("Geen live model — Quality = UNMEASURED");
        return;
      }
      const result = await hadesApi.gen2RunEvals({
        suite: "quality",
        mode: "live_model",
        model_id: modelId,
      });
      setReport(result);
      if (String(result.status).toLowerCase() === "unmeasured" || result.summary?.model_invoked === false) {
        toast.message("Quality = UNMEASURED");
      } else {
        toast.success("Meet dit model voltooid");
      }
    } catch (reason) {
      setReport({
        id: "local-unmeasured-error",
        suite: "meet_dit_model",
        status: "unmeasured",
        model_id: null,
        summary: {
          model_invoked: false,
          note: reason instanceof Error ? reason.message : "Meting mislukt — UNMEASURED",
        },
      });
      toast.message("Quality = UNMEASURED");
    } finally {
      setBusy(false);
    }
  };

  const runAb = async () => {
    setAbBusy(true);
    try {
      const models = await hadesApi.models();
      const modelId = models.active_profile?.model_id || models.models[0]?.id || "";
      if (!modelId) {
        setAbNote("Geen live model — A/B blijft UNMEASURED.");
        return;
      }
      // Same local model: naked vs HADES-assisted labels via eval lab A/B when available.
      const result = await hadesApi.gen2EvalAb({
        strategy_a: `naked:${modelId}`,
        strategy_b: `hades:${modelId}`,
        suite: "quality",
        model_id: modelId,
      });
      setAbNote(
        `A/B gestart voor ${modelId}. Claim nooit Anthropic/OpenAI/xAI-pariteit. `
        + `run=${String((result as { id?: string }).id || "—")}`,
      );
      toast.message("A/B aangevraagd — bekijk scores eerlijk");
    } catch (reason) {
      setAbNote(reason instanceof Error ? reason.message : "A/B niet beschikbaar");
      toast.message("A/B UNMEASURED / mislukt");
    } finally {
      setAbBusy(false);
    }
  };

  const badge = qualityLabel();

  return (
    <Panel
      title="Meet dit model"
      actions={<StatusBadge tone={badge.tone}>{badge.text}</StatusBadge>}
    >
      <p className="panel-copy">
        Vergelijk het geladen lokale model met HADES-context/tools waar mogelijk.
        Zonder compatibel live model blijft Quality = UNMEASURED — nooit een verzonnen PASS.
      </p>
      <div className="button-row" style={{ flexWrap: "wrap", gap: 8 }}>
        <Button type="button" onClick={() => void runMeet()} disabled={busy}>
          {busy ? <Loader2 className="spin" /> : <FlaskConical />}
          Meet dit model
        </Button>
        <Button type="button" variant="outline" onClick={() => void runAb()} disabled={abBusy || busy}>
          {abBusy ? <Loader2 className="spin" /> : null}
          HADES vs naked (A/B)
        </Button>
      </div>
      {report ? (
        <div className="log-view" style={{ marginTop: 12 }}>
          <code>model: {report.model_id || "—"}</code>
          <code>suite: {report.suite}</code>
          <code>status: {report.status}</code>
          {report.summary?.total != null ? <code>tasks: {report.summary.total}</code> : null}
          {report.summary?.passed != null ? <code>passed: {report.summary.passed}</code> : null}
          {report.summary?.failed != null ? <code>failed: {report.summary.failed}</code> : null}
          {report.summary?.note ? <code>{String(report.summary.note)}</code> : null}
        </div>
      ) : null}
      {abNote ? <small style={{ display: "block", marginTop: 8 }}>{abNote}</small> : null}
    </Panel>
  );
}
